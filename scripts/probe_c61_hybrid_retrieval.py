#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-61：真·混合检索（BM25＋向量 RRF）离线量 L2。

两臂同一分母（六案 105 金标段）、同一 pack_window.budget／SEGMENT_MAX／议题槽位：
  A 臂＝现行 BM25 密度键装箱（生产 pack_material）
  H 臂＝BM25 名次表 ∪ 向量名次表，按 RRF 1/(k+rank)、k＝60（复用
        app.core.bm25.fuse_rankings）融合后，monkeypatch rank_segments
        再走同一套 pack_material

向量：只走本机 ollama embedding（默认 bge-m3）；零现金；不新增 Python 依赖。
构造侧 gold_root 必须为 None（判据 e）；只有判分一侧读金标。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c61_hybrid_retrieval.py \\
    --run-dir /tmp/six2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bm25 import fuse_rankings, rank_segments  # noqa: E402
from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material, pack_search_queries  # noqa: E402
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD,
    discover_reports,
    gold_paras_for_question,
)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_EMBED = os.environ.get("C61_EMBED_MODEL", "bge-m3")
RRF_K = 60


# ---------------------------------------------------------------- ollama ----

def _ollama_list_models() -> list[str]:
    url = f"{OLLAMA_HOST.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"无可用向量、本单停手（无法列模型：{exc}）") from exc
    names = []
    for m in data.get("models") or []:
        name = str(m.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _pick_embed_model(preferred: str) -> str:
    names = _ollama_list_models()
    if not names:
        raise SystemExit("无可用向量、本单停手（ollama list 为空）")
    # 精确／去 tag／子串匹配 embedding 候选
    pref = preferred.strip()
    for n in names:
        if n == pref or n.startswith(pref + ":") or n.split(":")[0] == pref:
            return n
    # 回退：名字里带 bge／embed／e5／nomic 的
    for n in names:
        low = n.lower()
        if any(k in low for k in ("bge", "embed", "e5", "nomic", "mxbai")):
            return n
    raise SystemExit(
        f"无可用向量、本单停手（无 embedding 模型；已有={names}；要过的={pref!r}）"
    )


_EMBED_BATCH = 32
_EMBED_CHAR_CAP = 2000  # 只截 embedding 输入；装箱仍用全文 seg.text


def _embed_batch(model: str, texts: list[str], *, cache: dict[str, list[float]]) -> list[list[float]]:
    """本机 ollama /api/embed；按文本 sha 缓存；超长截断；分批 ≤32（整批过长会 400）。"""
    out: list[list[float] | None] = [None] * len(texts)
    miss_idx: list[int] = []
    miss_texts: list[str] = []
    for i, t in enumerate(texts):
        raw = t or ""
        clipped = raw if len(raw) <= _EMBED_CHAR_CAP else raw[:_EMBED_CHAR_CAP]
        key = hashlib.sha256(clipped.encode("utf-8")).hexdigest()
        if key in cache:
            out[i] = cache[key]
        else:
            miss_idx.append(i)
            miss_texts.append(clipped)
    url = f"{OLLAMA_HOST.rstrip('/')}/api/embed"
    for start in range(0, len(miss_texts), _EMBED_BATCH):
        chunk = miss_texts[start:start + _EMBED_BATCH]
        body = json.dumps({"model": model, "input": chunk}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SystemExit(f"无可用向量、本单停手（embed 失败：{exc}）") from exc
        embs = data.get("embeddings")
        if not isinstance(embs, list) or len(embs) != len(chunk):
            raise SystemExit(
                f"无可用向量、本单停手（embed 返回条数不对：期望 {len(chunk)} 实得 "
                f"{len(embs) if isinstance(embs, list) else type(embs)}）"
            )
        for j, emb in enumerate(embs):
            vec = [float(x) for x in emb]
            key = hashlib.sha256(chunk[j].encode("utf-8")).hexdigest()
            cache[key] = vec
            out[miss_idx[start + j]] = vec
    return [v if v is not None else [] for v in out]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return round(dot / math.sqrt(na * nb), 6)


# ------------------------------------------------------------- construct ----

def _budget_from_report(rep: dict) -> int:
    pw = (rep.get("accounting") or {}).get("pack_window") or {}
    b = pw.get("budget")
    if b is None:
        raise ValueError("report 缺 accounting.pack_window.budget")
    return int(b)


def _vector_ranking(
    dossier: Dossier,
    *,
    model: str,
    cache: dict[str, list[float]],
) -> list[tuple[str, float]]:
    """向量名次表：议题（expand 前原问）vs 各段 cosine；分＞0 才进 RRF。"""
    segs = [(seg.id, seg.text or "") for src in dossier.sources for seg in src.segments]
    if not segs:
        return []
    q = (dossier.question or "").strip() or " "
    texts = [q] + [t for _sid, t in segs]
    vecs = _embed_batch(model, texts, cache=cache)
    qv = vecs[0]
    scored: list[tuple[str, float]] = []
    for i, (sid, _t) in enumerate(segs):
        cos = _cosine(qv, vecs[i + 1])
        # 保证进 fuse_rankings（只要有向量就给正分＝cosine 平移到 (0,2]）
        score = cos + 1.0  # ∈(0, 2]
        scored.append((sid, round(score, 6)))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


def _hybrid_scores(
    dossier: Dossier,
    *,
    model: str,
    cache: dict[str, list[float]],
) -> tuple[dict[str, float], list[tuple[str, float]], dict[str, int]]:
    """返回 (融合分 dict, BM25 名次表, BM25 1-based 位次)。"""
    queries = pack_search_queries(dossier)
    bm25_ranked = list(
        rank_segments(dossier, queries=queries) if queries else rank_segments(dossier))
    bm25_rank = {sid: i + 1 for i, (sid, _sc) in enumerate(bm25_ranked)}
    vec_ranked = _vector_ranking(dossier, model=model, cache=cache)
    fused_list = fuse_rankings([bm25_ranked, vec_ranked], k=RRF_K)
    return dict(fused_list), bm25_ranked, bm25_rank


def _pack_with_scores(dossier: Dossier, budget: int, scores: dict[str, float]) -> set[str]:
    import app.core.bm25 as bm25_mod
    import app.core.material as mat_mod

    def _fake_rank(dossier_, query=None, queries=None):
        return sorted(scores.items(), key=lambda x: (-x[1], x[0]))

    real_b = bm25_mod.rank_segments
    real_m = mat_mod.rank_segments
    bm25_mod.rank_segments = _fake_rank
    mat_mod.rank_segments = _fake_rank
    try:
        pack = pack_material(dossier, budget_chars=budget)
    finally:
        bm25_mod.rank_segments = real_b
        mat_mod.rank_segments = real_m
    return {str(x) for x in (pack.get("selected") or [])}


def construct_selections(
    run_dir: Path,
    *,
    gold_root: Path | None,
    embed_model: str,
    cache: dict[str, list[float]],
) -> dict:
    """构造两臂选中集合。金标路径必须为 None（判据 e）。"""
    assert gold_root is None, "判据 e：构造侧 gold_root 必须为 None"
    rows = []
    construct_files: list[str] = []
    reports = discover_reports(run_dir)
    for i, rp in enumerate(reports, 1):
        construct_files.append(str(rp.resolve()))
        case, qid = rp.parts[-4], rp.parts[-2]
        print(f"  [{i}/{len(reports)}] {case[:18]}/{qid} …", flush=True)
        rep = json.loads(rp.read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(rep)
        budget = _budget_from_report(rep)

        # A：现行
        pack_a = pack_material(dossier, budget_chars=budget)
        sel_a = {str(x) for x in (pack_a.get("selected") or [])}

        # H：融合
        fused, bm25_ranked, bm25_rank = _hybrid_scores(
            dossier, model=embed_model, cache=cache)
        sel_h = _pack_with_scores(dossier, budget, fused)

        rows.append({
            "case": case,
            "qid": qid,
            "budget": budget,
            "sel_a": sorted(sel_a),
            "sel_h": sorted(sel_h),
            "bm25_rank": bm25_rank,
            "n_bm25_pos": sum(1 for _s, sc in bm25_ranked if sc > 0),
            "n_fused": len(fused),
        })
    return {
        "run_dir": str(run_dir),
        "embed_model": embed_model,
        "n_questions": len(rows),
        "rows": rows,
        "construct_files": construct_files,
    }


# ---------------------------------------------------------------- score ----

def score_pack(pack: dict, gold_dir: Path) -> dict:
    """判分侧：打开金标，算 L2／lost／gained。"""
    tot = Counter()
    per_case: dict[str, Counter] = {}
    gained_detail: list[dict] = []
    lost_detail: list[dict] = []
    identical = 0
    for r in pack["rows"]:
        gold, _sk = gold_paras_for_question(gold_dir / r["case"], r["qid"])
        if not gold:
            continue
        gold_paras = {p for _d, p in gold.keys()}
        denom = len(gold)
        sel_a = set(r["sel_a"])
        sel_h = set(r["sel_h"])
        a_l2 = gold_paras & sel_a
        h_l2 = gold_paras & sel_h
        lost = sorted(a_l2 - h_l2)
        gained = sorted(h_l2 - a_l2)
        if sel_a == sel_h:
            identical += 1
        c = per_case.setdefault(r["case"], Counter())
        for k, v in (("denom", denom), ("l2_a", len(a_l2)), ("l2_h", len(h_l2))):
            c[k] += v
            tot[k] += v
        for para in lost:
            lost_detail.append({"case": r["case"], "qid": r["qid"], "para": para})
        for para in gained:
            gained_detail.append({
                "case": r["case"],
                "qid": r["qid"],
                "para": para,
                "bm25_rank": r["bm25_rank"].get(para),
            })
    return {
        "denom": int(tot["denom"]),
        "l2_a": int(tot["l2_a"]),
        "l2_h": int(tot["l2_h"]),
        "lost_n": len(lost_detail),
        "gained_n": len(gained_detail),
        "lost": lost_detail,
        "gained": gained_detail,
        "per_case": {k: dict(v) for k, v in sorted(per_case.items())},
        "n_identical_selected": identical,
        "n_questions": pack["n_questions"],
    }


def _fingerprint(pack: dict) -> str:
    """两遍对比用：选中集合＋预算的稳定指纹。"""
    payload = [
        {
            "case": r["case"], "qid": r["qid"], "budget": r["budget"],
            "sel_a": r["sel_a"], "sel_h": r["sel_h"],
        }
        for r in pack["rows"]
    ]
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--run-dir", default="/tmp/six2")
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--embed-model", default=DEFAULT_EMBED)
    ap.add_argument("--out", default="/tmp/c61_hybrid_retrieval")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir)
    gold_dir = Path(args.gold_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not run_dir.is_dir():
        print(f"跑次不存在：{run_dir}", file=sys.stderr)
        return 2

    embed_model = _pick_embed_model(args.embed_model)
    print(f"embedding 模型＝{embed_model}（ollama@{OLLAMA_HOST}）", flush=True)

    # —— 第一遍构造（判据 e）——
    cache: dict[str, list[float]] = {}
    print("[构造 pass1] gold_root=None …", flush=True)
    pack1 = construct_selections(
        run_dir, gold_root=None, embed_model=embed_model, cache=cache)
    print(f"判据 e：构造未读金标＝True；构造读 report 数＝{len(pack1['construct_files'])}",
          flush=True)
    fp1 = _fingerprint(pack1)

    # —— 判分 ——
    scored1 = score_pack(pack1, gold_dir)
    print(f"\n=== C-61 pass1 run={run_dir} embed={embed_model} ===")
    print(f"分母={scored1['denom']}  A L2={scored1['l2_a']}/{scored1['denom']}  "
          f"H L2={scored1['l2_h']}/{scored1['denom']}")
    print(f"ΔL2＝{scored1['l2_h'] - scored1['l2_a']:+d}  "
          f"lost={scored1['lost_n']}  gained={scored1['gained_n']}  "
          f"选中集合完全相同的题数＝{scored1['n_identical_selected']}/{scored1['n_questions']}")

    a_ok = scored1["l2_a"] == 48 and scored1["denom"] == 105
    print(f"判据 a（A L2=48/105）：{'✅' if a_ok else '❌'}")
    if not a_ok:
        print("口径飘了，停手。读数与口径原样交回，不报 H 臂门槛。", flush=True)
        (out_dir / "pass1.json").write_text(
            json.dumps({"pack": pack1, "scored": scored1, "embed_model": embed_model},
                       ensure_ascii=False, indent=1),
            encoding="utf-8")
        return 3

    b_ok = scored1["l2_h"] >= 54 and scored1["lost_n"] == 0
    print(f"判据 b（H L2≥54 且 lost=0）：{'✅' if b_ok else '❌ → 逃逸披露，件② 不做'}")

    # 判据 c
    if scored1["n_identical_selected"] == scored1["n_questions"]:
        print("判据 c：❌ H 与 A 选中集合在全部题上完全相同＝向量路没生效", flush=True)
        c_ok = False
    else:
        c_ok = True
        print("判据 c：✅ 至少一题选中集合不同", flush=True)
    print("H 相对 A 新命中金标段（及 BM25 原位次）：")
    if not scored1["gained"]:
        print("  （无）")
    for g in scored1["gained"][:60]:
        print(f"  {g['case'][:16]}/{g['qid']} {g['para']}  bm25_rank={g['bm25_rank']}")

    # —— 第二遍（判据 d）——
    print("\n[构造 pass2] 同输入再跑一遍 …", flush=True)
    cache2: dict[str, list[float]] = {}  # 新缓存，但仍应得到相同排序
    pack2 = construct_selections(
        run_dir, gold_root=None, embed_model=embed_model, cache=cache2)
    fp2 = _fingerprint(pack2)
    scored2 = score_pack(pack2, gold_dir)
    d_ok = (fp1 == fp2
            and scored1["l2_a"] == scored2["l2_a"]
            and scored1["l2_h"] == scored2["l2_h"]
            and scored1["lost_n"] == scored2["lost_n"]
            and scored1["gained_n"] == scored2["gained_n"])
    print(f"判据 d（两遍逐字相同）：{'✅' if d_ok else '❌'}")
    print(f"  fp1={fp1}")
    print(f"  fp2={fp2}")
    print(f"  pass2 L2 A={scored2['l2_a']} H={scored2['l2_h']} "
          f"lost={scored2['lost_n']} gained={scored2['gained_n']}")

    print("\n逐案：")
    print(f"  {'case':32} {'den':>4} {'AL2':>4} {'HL2':>4}")
    for case, c in scored1["per_case"].items():
        print(f"  {case[:30]:30} {c['denom']:4} {c['l2_a']:4} {c['l2_h']:4}")

    summary = {
        "embed_model": embed_model,
        "run_dir": str(run_dir),
        "pass1": scored1,
        "pass2": {
            "l2_a": scored2["l2_a"], "l2_h": scored2["l2_h"],
            "lost_n": scored2["lost_n"], "gained_n": scored2["gained_n"],
        },
        "fp1": fp1,
        "fp2": fp2,
        "criteria": {
            "a": a_ok, "b": b_ok, "c": c_ok, "d": d_ok,
            "e": True, "f_model": embed_model,
        },
        "escape": (not b_ok),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "pass1_rows.json").write_text(
        json.dumps(pack1["rows"], ensure_ascii=False, indent=1), encoding="utf-8")
    report = (
        f"C-61 embed={embed_model}\n"
        f"A L2={scored1['l2_a']}/{scored1['denom']}  "
        f"H L2={scored1['l2_h']}/{scored1['denom']}  "
        f"lost={scored1['lost_n']} gained={scored1['gained_n']}\n"
        f"判据 a={'PASS' if a_ok else 'FAIL'}  b={'PASS' if b_ok else 'ESCAPE'}  "
        f"c={'PASS' if c_ok else 'FAIL'}  d={'PASS' if d_ok else 'FAIL'}\n"
        f"fp1={fp1}\nfp2={fp2}\n"
    )
    (out_dir / "report.txt").write_text(report, encoding="utf-8")
    print(f"\n[wrote] {out_dir}", flush=True)
    return 0 if (a_ok and c_ok and d_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
