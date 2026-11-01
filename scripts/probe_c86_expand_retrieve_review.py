#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-86：跳过切片打标——议题扩写 → BM25 多路召回 → C-85 先锚后审（只量）。

协议（相对 C-85 只换召回侧）：
  1) 本地 LLM 从议题扩同义／别称／关键词（多路问句，金标不进提示词）
  2) BM25 对「原问＋扩写问句」做 RRF 融合，取前 K（默认 120）
  3) 复用 C-85：抽锚（可复用文件）→ 按锚批审 → 装箱
  4) 若 B 的 L2>A0 → 自动弱锚补召回（同 C-85-C）

判据：a＝A0 48/105；b＝臂≥54 且 lost=0。对照 C-85 K60-C＝52／K180-C＝57。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c86_expand_retrieve_review.py \\
      --run-dir /tmp/six2 --auto --out-dir /tmp/c86_expand \\
      --copy-anchors-from /tmp/c85_auto/anchors.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bm25 import fuse_rankings, rank_segments  # noqa: E402
from app.core.evidence import Dossier  # noqa: E402
from scripts.probe_c62_rerank_arms import _query_of  # noqa: E402
from scripts.probe_c84_llm_rerank import _budget, _lock_local  # noqa: E402
from scripts.probe_c85_anchor_review import (  # noqa: E402
    DEFAULT_BATCH,
    DEFAULT_MODEL,
    DEFAULT_REFILL,
    _ollama_chat,
    _parse_json_obj,
    judge,
    run_measure,
    score_b,
    score_c_refill,
    _print_summary,
)
from scripts.probe_recall_funnel import discover_reports  # noqa: E402

DEFAULT_K = 120
TARGET_A0 = 48


def _expand_prompt(question: str) -> str:
    return "\n".join([
        "你是检索助理。任务：为后面的关键词／BM25 召回扩写检索问句，不要答题。",
        "围绕议题的主体、争点、别称、同义说法、可能出现的官方表述，写出多条短检索句。",
        "不要编造议题未出现的实体；不要写长文章。",
        f"议题：{question}",
        "只输出 JSON：",
        '{"queries":["原意改写1","别称/同义检索句2",...],'
        '"keywords":["关键词1","关键词2",...]}',
        "queries 3～8 条；keywords 最多 16 个。",
    ])


def expand_queries(
    out_dir: Path, *, model: str, limit: int | None,
) -> dict[str, dict]:
    _lock_local()
    jobs = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
    if limit is not None:
        jobs = jobs[: max(1, limit)]
    path = out_dir / "expansions.json"
    done: dict[str, dict] = {}
    if path.is_file():
        done = json.loads(path.read_text(encoding="utf-8"))
    t0 = time.time()
    n_calls = 0
    for ji, job in enumerate(jobs, 1):
        key = f"{job['case']}::{job['qid']}"
        if key in done and (done[key].get("queries") or done[key].get("keywords")):
            print(f"  扩 [{ji}/{len(jobs)}] {key[:36]} 缓存", flush=True)
            continue
        prompt = _expand_prompt(job["query"])
        raw = _ollama_chat(model, prompt)
        n_calls += 1
        try:
            obj = _parse_json_obj(raw)
        except Exception:
            raw2 = _ollama_chat(model, prompt + "\n再次确认：只输出 JSON。")
            n_calls += 1
            try:
                obj = _parse_json_obj(raw2)
            except Exception:
                obj = {"queries": [job["query"]], "keywords": [], "_fallback": True}
        qs = [str(x).strip() for x in (obj.get("queries") or []) if str(x).strip()]
        kws = [str(x).strip() for x in (obj.get("keywords") or []) if str(x).strip()]
        if job["query"] not in qs:
            qs = [job["query"]] + qs
        # 关键词拼成一路短问，避免空
        if kws:
            qs.append(" ".join(kws[:12]))
        # 去重保序、上限
        seen, uniq = set(), []
        for q in qs:
            if q not in seen:
                seen.add(q)
                uniq.append(q)
        obj["queries"] = uniq[:10]
        obj["keywords"] = kws[:16]
        done[key] = obj
        path.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  扩 [{ji}/{len(jobs)}] {key[:36]} n_q={len(obj['queries'])}", flush=True)
    meta = {
        "phase": "expand", "model": model, "n_calls": n_calls,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (out_dir / "expand_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"扩写墙钟＝{meta['elapsed_s']}s 调用＝{n_calls} → {path}")
    return done


def prepare_expand_retrieve(
    run_dir: Path,
    out_dir: Path,
    *,
    k: int,
    model: str,
    limit: int | None,
    expansions: dict[str, dict] | None = None,
) -> dict:
    """先占位 jobs（原问），扩写后重算 BM25 多路候选写入 score_input。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    # 第一遍：骨架
    skeletons = []
    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(rep)
        query = _query_of(dossier)
        skeletons.append({
            "case": case,
            "qid": qid,
            "query": query,
            "budget": _budget(rep),
            "report": str(rp.resolve()),
        })
    if limit is not None:
        skeletons = skeletons[: max(1, limit)]

    # 临时 score_input 供 expand_queries 读 query
    tmp_jobs = [{**s, "ids": [], "texts": [], "bm25_scores": {}} for s in skeletons]
    (out_dir / "score_input.json").write_text(
        json.dumps(tmp_jobs, ensure_ascii=False), encoding="utf-8")

    if expansions is None:
        expansions = expand_queries(out_dir, model=model, limit=limit)
    else:
        (out_dir / "expansions.json").write_text(
            json.dumps(expansions, ensure_ascii=False, indent=2), encoding="utf-8")

    jobs = []
    for s in skeletons:
        key = f"{s['case']}::{s['qid']}"
        dossier = Dossier.from_dict(
            json.loads(Path(s["report"]).read_text(encoding="utf-8")))
        text_of = {
            seg.id: (seg.text or "")
            for src in dossier.sources for seg in src.segments
        }
        exp = expansions.get(key) or {}
        queries = [str(q).strip() for q in (exp.get("queries") or []) if str(q).strip()]
        if not queries:
            queries = [s["query"]]
        # 多路 BM25 → RRF；全表分用融合分；候选＝前 K
        rankings = [rank_segments(dossier, query=q) for q in queries]
        fused = fuse_rankings(rankings)
        bm25_scores = {sid: float(sc) for sid, sc in fused}
        # 未进融合的段补 0，保证 fuse 装箱底表完整
        for sid in text_of:
            bm25_scores.setdefault(sid, 0.0)
        ids = [sid for sid, _ in fused[:k]]
        # 若融合命中不足 K，用单路原问补足
        if len(ids) < k:
            solo = rank_segments(dossier, query=s["query"])
            for sid, _ in solo:
                if sid not in ids:
                    ids.append(sid)
                if len(ids) >= k:
                    break
        jobs.append({
            **s,
            "ids": ids[:k],
            "texts": [text_of.get(i, "") for i in ids[:k]],
            "bm25_scores": bm25_scores,
            "expand_queries": queries,
            "cand_mode": "bm25_rrf_expand",
            "k": k,
        })

    path = out_dir / "score_input.json"
    path.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    meta = {
        "n_questions": len(jobs),
        "k": k,
        "cand_mode": "bm25_rrf_expand",
        "use_bm25_fuse": True,
        "no_bm25": False,
        "score_input": str(path),
        "protocol": "expand→BM25-RRF→C85-review",
    }
    (out_dir / "prepare_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("======== C-86 --prepare ========")
    print(f"题数＝{len(jobs)}｜K＝{k}｜召回＝扩写多路 BM25-RRF → {path}")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", default="/tmp/c86_expand")
    ap.add_argument("--gold-dir", default="")
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--refill-n", type=int, default=DEFAULT_REFILL)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--copy-anchors-from", default="")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--score-b", action="store_true")
    ap.add_argument("--run-b", action="store_true")
    ap.add_argument("--auto", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    from scripts.probe_recall_funnel import DEFAULT_GOLD
    gold_dir = Path(args.gold_dir) if args.gold_dir else DEFAULT_GOLD

    if args.prepare or args.auto:
        prepare_expand_retrieve(
            Path(args.run_dir), out_dir,
            k=args.k, model=args.model, limit=args.limit,
        )
        if args.copy_anchors_from:
            src = Path(args.copy_anchors_from)
            if src.is_file():
                (out_dir / "anchors.json").write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"复用锚 ← {src}")

    if args.score_b or args.auto:
        score_b(
            out_dir, model=args.model, batch_size=args.batch_size, limit=args.limit)

    summary_b = j_b = None
    if args.run_b or args.auto:
        summary_b = run_measure(
            out_dir, gold_dir, scores_name="llm_scores_b.json", arm_key="B")
        j_b = judge(summary_b, "B")
        _print_summary(summary_b, "B", j_b)
        (out_dir / "summary_b.json").write_text(
            json.dumps({"summary": summary_b, "judge": j_b, "protocol": "C-86"},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"落盘 {out_dir / 'summary_b.json'}")

    do_c = False
    if args.auto:
        if j_b and j_b["improved_vs_a0"]:
            print("\n>>> C-86 B 相对 A0 有提升 → 自动开弱锚补召回 C\n", flush=True)
            do_c = True
        else:
            print("\n>>> C-86 B 未提升 → 跳过 C\n", flush=True)

    if do_c:
        score_c_refill(
            out_dir, model=args.model, batch_size=args.batch_size,
            refill_n=args.refill_n, limit=args.limit,
        )
        summary_c = run_measure(
            out_dir, gold_dir, scores_name="llm_scores_c.json", arm_key="C")
        j_c = judge(summary_c, "C")
        _print_summary(summary_c, "C", j_c)
        (out_dir / "summary_c.json").write_text(
            json.dumps({"summary": summary_c, "judge": j_c, "protocol": "C-86"},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"落盘 {out_dir / 'summary_c.json'}")

    if summary_b is not None and not j_b["a"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
