#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-87c：测两件未测项（吉隆；六案需另打标）。

  1) 约束修标后，对高频 path **重新 LLM 扩写**（不是滤旧扩写）
  2) 标签侧改向量召回（bge-m3 余弦）对照标签 BM25／原文 BM25／双路

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c87c_reexpand_vector.py \\
      --c87-dir /tmp/c87_jilong --c87b-dir /tmp/c87b_constrain \\
      --out-dir /tmp/c87c_reexpand --reexpand --embed --measure
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from scripts.probe_c62_rerank_arms import _bm25_table  # noqa: E402
from scripts.probe_c66_multi_box import selected_locs  # noqa: E402
from scripts.probe_c84_llm_rerank import _lock_local  # noqa: E402
from scripts.probe_c85_anchor_review import (  # noqa: E402
    DEFAULT_MODEL,
    _gold_keys,
    _ollama_chat,
)
from scripts.probe_c87_bilateral_tag_expand import (  # noqa: E402
    GATE_HOTWORD_MAX,
    GATE_SUBSTANCE_MIN,
    _bm25_over_docs,
    _has_substance,
    _hot_terms,
    _hotword_overlap,
    _parse_json_obj,
    _rrf_fuse,
)
from scripts.probe_c87b_constrain_dual import (  # noqa: E402
    build_synth,
    repair_label_expansions,
    repair_tags,
)
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
EMBED_MODEL = "bge-m3:latest"


def _embed(text: str, *, model: str = EMBED_MODEL) -> list[float]:
    body = {"model": model, "prompt": text[:2000]}
    req = urllib.request.Request(
        f"{OLLAMA}/api/embeddings",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    emb = data.get("embedding") or []
    if not emb:
        raise RuntimeError("empty embedding")
    return [float(x) for x in emb]


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(x * x for x in b)) or 1e-9
    return dot / (na * nb)


def _expand_prompt(path: str, ents: list[str], hot_block: str) -> str:
    return "\n".join([
        "检索助理。为切片标签扩写检索用语。不要答题。",
        "硬约束：",
        "1) 禁止只吐议题热词／通稿套话；",
        "2) 每条必须含可核验实体、时间、量名或因果链词；",
        "3) 实体必须来自「允许实体」列表或 path 字面，禁止捏造新数字／新日期；",
        "4) 不要写与 path 切面无关的伤亡通稿（除非切面本身是伤亡）。",
        f"path：{path}",
        f"允许实体：{json.dumps(ents[:10], ensure_ascii=False)}",
        f"议题热词（禁止只围着转）：{hot_block}",
        '只输出 JSON：{"expand":[".."],"keywords":[".."]}',
        "expand 3～6 条；keywords≤10。",
    ])


def reexpand_paths(
    tags: dict[str, dict],
    questions: list[str],
    *,
    model: str,
    llm_min_count: int = 3,
    llm_top_n: int = 60,
    out_dir: Path,
) -> dict[str, dict]:
    _lock_local()
    by_path: dict[str, list[str]] = defaultdict(list)
    path_count: Counter[str] = Counter()
    for rec in tags.values():
        p = str(rec.get("p") or "")
        path_count[p] += 1
        for e in rec.get("e") or []:
            if e and e not in by_path[p]:
                by_path[p].append(str(e))

    hot: set[str] = set()
    for q in questions:
        hot |= _hot_terms(q)
    hot_block = "、".join(sorted(hot)[:24])

    llm_paths = [
        p for p, _n in sorted(path_count.items(), key=lambda x: (-x[1], x[0]))
        if path_count[p] >= llm_min_count
        and not p.startswith(("短片/", "降级/", "未归类/"))
    ][:llm_top_n]

    cache = out_dir / "label_expansions_rellm.json"
    done: dict[str, dict] = {}
    if cache.is_file():
        done = json.loads(cache.read_text(encoding="utf-8"))

    n_calls = 0
    t0 = time.time()
    print(f"======== 重新 LLM 扩写 path＝{len(llm_paths)} ========", flush=True)
    for i, p in enumerate(llm_paths, 1):
        if p in done and (done[p].get("expand") or done[p].get("keywords")):
            print(f"  [{i}/{len(llm_paths)}] 缓存 {p[:40]}", flush=True)
            continue
        ents = by_path[p][:10]
        prompt = _expand_prompt(p, ents, hot_block)
        raw = _ollama_chat(model, prompt)
        n_calls += 1
        try:
            obj = _parse_json_obj(raw)
        except Exception:
            raw2 = _ollama_chat(model, prompt + "\n再次确认：只输出 JSON，实体不许新造。")
            n_calls += 1
            try:
                obj = _parse_json_obj(raw2)
            except Exception:
                obj = {"expand": ents[:3] or [p], "keywords": ents, "_fallback": True}

        exp = [str(x).strip() for x in (obj.get("expand") or []) if str(x).strip()]
        kws = [str(x).strip() for x in (obj.get("keywords") or []) if str(x).strip()]
        # 硬滤：substance + 热词
        exp = [t for t in exp if _has_substance([t]) and _hotword_overlap([t], hot) <= 0.85][:6]
        kws = [t for t in kws if _has_substance([t]) or t in ents or t in p][:10]
        if not exp:
            exp = ents[:3] or [p]
        done[p] = {"expand": exp, "keywords": kws, "src": "llm_reexpand"}
        cache.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [{i}/{len(llm_paths)}] {p[:40]} n_exp={len(exp)}", flush=True)

    # 长尾规则
    for p in path_count:
        if p in done:
            continue
        ents = by_path[p][:8]
        parts = [x for x in p.split("/") if x and x not in ("未知", "其他", "未归类")]
        done[p] = {
            "expand": ents[:3] or parts[:3] or [p],
            "keywords": list(dict.fromkeys(parts + ents))[:12],
            "src": "rule",
        }
    cache.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")

    # gates
    substance_hit = 0
    hot_rates = []
    for exp in done.values():
        terms = list(exp.get("expand") or []) + list(exp.get("keywords") or [])
        if _has_substance(terms):
            substance_hit += 1
        hot_rates.append(_hotword_overlap(terms, hot))
    n = max(1, len(done))
    meta = {
        "n_paths": len(done),
        "n_llm": len(llm_paths),
        "n_calls": n_calls,
        "elapsed_s": round(time.time() - t0, 1),
        "gates": {
            "gate_substance": {
                "value": round(substance_hit / n, 4),
                "ok": substance_hit / n >= GATE_SUBSTANCE_MIN,
            },
            "gate_hotword": {
                "value": round(sum(hot_rates) / max(1, len(hot_rates)), 4),
                "ok": (sum(hot_rates) / max(1, len(hot_rates))) <= GATE_HOTWORD_MAX,
            },
        },
    }
    (out_dir / "reexpand_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"重扩写完成 calls={n_calls} {meta['gates']}", flush=True)
    return done


def embed_corpus(
    synth: dict[str, str], out_dir: Path, *, model: str = EMBED_MODEL,
) -> dict[str, list[float]]:
    cache = out_dir / "doc_embeddings.json"
    done: dict[str, list[float]] = {}
    if cache.is_file():
        done = json.loads(cache.read_text(encoding="utf-8"))
    todo = [sid for sid in synth if sid not in done]
    print(f"======== 向量化伪文档 待＝{len(todo)} 已有＝{len(done)} ========", flush=True)
    t0 = time.time()
    for i, sid in enumerate(todo, 1):
        try:
            done[sid] = _embed(synth[sid], model=model)
        except Exception as exc:
            print(f"  embed fail {sid}: {exc}", flush=True)
            done[sid] = []
        if i % 100 == 0 or i == len(todo):
            cache.write_text(json.dumps(done), encoding="utf-8")
            print(
                f"  embed [{i}/{len(todo)}] elapsed={round(time.time()-t0,0):.0f}s",
                flush=True,
            )
    cache.write_text(json.dumps(done), encoding="utf-8")
    return done


def vector_rank(
    doc_emb: dict[str, list[float]], query: str, *, model: str = EMBED_MODEL,
) -> list[tuple[str, float]]:
    qe = _embed(query, model=model)
    out = []
    for sid, de in doc_emb.items():
        if not de:
            out.append((sid, 0.0))
            continue
        out.append((sid, float(_cos(qe, de))))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


def measure(
    *,
    dossier: Dossier,
    qjobs: list[dict],
    q_exp: dict[str, dict],
    synth: dict[str, str],
    doc_emb: dict[str, list[float]] | None,
    gold_dir: Path,
    k: int,
    bm25_k: int,
) -> dict[str, Any]:
    docs = list(synth.items())
    bm25_ranking = _bm25_table(dossier)
    rows = []
    for job in qjobs:
        key = f"{job['case']}::{job['qid']}"
        gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
        exp = q_exp.get(key) or {}
        queries = [str(q).strip() for q in (exp.get("queries") or []) if str(q).strip()]
        if not queries:
            queries = [job["query"]]
        extra = list(exp.get("keywords") or []) + list(exp.get("answer_shape") or [])
        if extra:
            queries = list(dict.fromkeys(queries + [" ".join(extra[:12])]))

        label_bm25 = _rrf_fuse([_bm25_over_docs(docs, q) for q in queries])
        # 向量：多路 query 取 max 分再排
        vec_ranking = None
        if doc_emb is not None:
            best: dict[str, float] = defaultdict(float)
            for q in queries:
                for sid, sc in vector_rank(doc_emb, q):
                    if sc > best[sid]:
                        best[sid] = sc
            vec_ranking = sorted(best.items(), key=lambda x: (-x[1], x[0]))

        def hits(pool: set[str]) -> int:
            return len(selected_locs(dossier, pool) & gold)

        bm25_pool = {sid for sid, _ in bm25_ranking[:bm25_k]}
        label_pool = {sid for sid, _ in label_bm25[:k]}
        dual = _rrf_fuse([bm25_ranking, label_bm25])
        dual_pool = {sid for sid, _ in dual[:k]}

        row: dict[str, Any] = {
            "qid": job["qid"],
            "denom": denom,
            "bm25": hits(bm25_pool),
            "label_bm25": hits(label_pool),
            "dual_bm25": hits(dual_pool),
            "label_unique": len(
                (selected_locs(dossier, label_pool) & gold)
                - (selected_locs(dossier, bm25_pool) & gold)
            ),
            "dual_unique": len(
                (selected_locs(dossier, dual_pool) & gold)
                - (selected_locs(dossier, bm25_pool) & gold)
            ),
        }
        if vec_ranking is not None:
            vec_pool = {sid for sid, _ in vec_ranking[:k]}
            # 向量∥原文 BM25
            dual_vec = _rrf_fuse([bm25_ranking, vec_ranking])
            dual_vec_pool = {sid for sid, _ in dual_vec[:k]}
            row["label_vec"] = hits(vec_pool)
            row["dual_vec"] = hits(dual_vec_pool)
            row["vec_unique"] = len(
                (selected_locs(dossier, vec_pool) & gold)
                - (selected_locs(dossier, bm25_pool) & gold)
            )
            row["dual_vec_unique"] = len(
                (selected_locs(dossier, dual_vec_pool) & gold)
                - (selected_locs(dossier, bm25_pool) & gold)
            )
        rows.append(row)
        print(
            f"  {job['qid']}: BM25={row['bm25']}/{denom} "
            f"标签BM25={row['label_bm25']}(独有{row['label_unique']}) "
            f"双BM25={row['dual_bm25']}(独有{row['dual_unique']})"
            + (
                f" 标签向量={row['label_vec']}(独有{row['vec_unique']}) "
                f"双向量={row['dual_vec']}(独有{row['dual_vec_unique']})"
                if vec_ranking is not None else ""
            ),
            flush=True,
        )

    tot = {
        "denom": sum(r["denom"] for r in rows),
        "bm25": sum(r["bm25"] for r in rows),
        "label_bm25": sum(r["label_bm25"] for r in rows),
        "dual_bm25": sum(r["dual_bm25"] for r in rows),
        "label_unique": sum(r["label_unique"] for r in rows),
        "dual_unique": sum(r["dual_unique"] for r in rows),
    }
    if rows and "label_vec" in rows[0]:
        tot["label_vec"] = sum(r["label_vec"] for r in rows)
        tot["dual_vec"] = sum(r["dual_vec"] for r in rows)
        tot["vec_unique"] = sum(r["vec_unique"] for r in rows)
        tot["dual_vec_unique"] = sum(r["dual_vec_unique"] for r in rows)
    return {"rows": rows, "totals": tot, "k": k, "bm25_k": bm25_k}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--c87-dir", default="/tmp/c87_jilong")
    ap.add_argument("--c87b-dir", default="/tmp/c87b_constrain")
    ap.add_argument("--out-dir", default="/tmp/c87c_reexpand")
    ap.add_argument("--gold-dir", default="")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--embed-model", default=EMBED_MODEL)
    ap.add_argument("--k", type=int, default=120)
    ap.add_argument("--bm25-k", type=int, default=60)
    ap.add_argument("--reexpand", action="store_true")
    ap.add_argument("--embed", action="store_true")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all:
        args.reexpand = args.embed = args.measure = True

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    c87 = Path(args.c87_dir)
    c87b = Path(args.c87b_dir)
    gold_dir = Path(args.gold_dir) if args.gold_dir else DEFAULT_GOLD

    # tags: prefer repaired
    tags_path = c87b / "tags_repaired.json"
    if tags_path.is_file():
        tags = json.loads(tags_path.read_text(encoding="utf-8"))
    else:
        old = json.loads((c87 / "tags.json").read_text(encoding="utf-8"))
        segs = json.loads((c87 / "segments.json").read_text(encoding="utf-8"))
        text_of = {s["id"]: s.get("text") or "" for s in segs["segs"]}
        tags, _ = repair_tags(old, text_of)

    qjobs = json.loads((c87 / "question_jobs.json").read_text(encoding="utf-8"))
    questions = [j["query"] for j in qjobs]
    # 议题扩写：用 c87b 约束版
    q_exp_path = c87b / "question_expansions_repaired.json"
    if q_exp_path.is_file():
        q_exp = json.loads(q_exp_path.read_text(encoding="utf-8"))
    else:
        q_exp = json.loads((c87 / "question_expansions.json").read_text(encoding="utf-8"))

    lab_exp = None
    if args.reexpand:
        lab_exp = reexpand_paths(
            tags, questions, model=args.model, out_dir=out)
    else:
        p = out / "label_expansions_rellm.json"
        if p.is_file():
            lab_exp = json.loads(p.read_text(encoding="utf-8"))
        else:
            # 回退：c87b 过滤版
            lab_exp = json.loads(
                (c87b / "label_expansions_repaired.json").read_text(encoding="utf-8"))

    synth = build_synth(tags, lab_exp)
    (out / "synth_docs.json").write_text(
        json.dumps(synth, ensure_ascii=False), encoding="utf-8")

    doc_emb = None
    if args.embed:
        doc_emb = embed_corpus(synth, out, model=args.embed_model)

    if args.measure:
        dossier = Dossier.from_dict(
            json.loads(Path(qjobs[0]["report"]).read_text(encoding="utf-8")))
        if doc_emb is None and (out / "doc_embeddings.json").is_file():
            doc_emb = json.loads((out / "doc_embeddings.json").read_text(encoding="utf-8"))
        print("======== 量尺 ========", flush=True)
        summary = measure(
            dossier=dossier, qjobs=qjobs, q_exp=q_exp, synth=synth,
            doc_emb=doc_emb, gold_dir=gold_dir, k=args.k, bm25_k=args.bm25_k,
        )
        # 对照旧数
        summary["baselines"] = {
            "c87_label_gold": 2,
            "c87b_label_gold_after_filter": 2,
            "bm25_60": 6,
            "bm25_120": 7,
            "note": "六案未测＝无另五案打标；本票只吉隆。",
        }
        t = summary["totals"]
        summary["verdict"] = {
            "reexpand_beats_old_label": t["label_bm25"] > 2,
            "reexpand_beats_bm25": t["label_bm25"] > t["bm25"],
            "vec_beats_label_bm25": t.get("label_vec", -1) > t["label_bm25"],
            "vec_beats_bm25": t.get("label_vec", -1) > t["bm25"],
            "any_unique_gold": (
                t["label_unique"] > 0
                or t.get("vec_unique", 0) > 0
            ),
        }
        (out / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "totals": t, "verdict": summary["verdict"], "baselines": summary["baselines"],
        }, ensure_ascii=False, indent=2), flush=True)
        print(f"落盘 {out / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
