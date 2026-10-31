#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-58 件①：small→big＝小块打分、大段进模型（只量、零模型、app/ 零 diff）。

切法（可复现、无随机）：
  1) 按句切：以中文句末标点「。！？；」及英文 `.!?` 为界，保留标点在块尾；
  2) 若整段无句界或某块仍 > CHUNK_MAX＝120 字，再按定长窗 120 字切（尾块可短）；
  3) 空段不产块。块 id 仅探针内部用，**不**当作新段进提示词。

打分：
  - A 臂＝现码 `rank_segments`（段级 BM25＋多问 RRF）；
  - B 臂＝把所有小块当作 BM25 文档，对同一查询打分，再按所属段取 **max** 回聚合。

装箱：两臂都走 `pack_material`，预算＝产物 `accounting.pack_window.budget`
（不许自定）。B 臂临时把 `rank_segments` 换成回聚合分表。

读数：装箱前候选池命中（score>0 的金标段数）＋装箱后 L2；lost＝A∩金标 − B∩金标。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c58_small_to_big.py \\
    --run-dir /tmp/six2
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bm25 import (  # noqa: E402
    _B, _K1, expand_query, fuse_rankings, _tokens,
)
from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material, pack_search_queries  # noqa: E402
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD,
    discover_reports,
    gold_paras_for_question,
)

CHUNK_MAX = 120
_SENT_SPLIT = re.compile(r"(?<=[。！？；.!?])")


def split_into_chunks(text: str, *, chunk_max: int = CHUNK_MAX) -> list[str]:
    """可复现切块：先按句，超长再定长窗。"""
    raw = text or ""
    if not raw.strip():
        return []
    parts = [p for p in _SENT_SPLIT.split(raw) if p]
    if not parts:
        parts = [raw]
    out: list[str] = []
    for p in parts:
        if len(p) <= chunk_max:
            out.append(p)
            continue
        for i in range(0, len(p), chunk_max):
            out.append(p[i:i + chunk_max])
    return out


def _bm25_score_docs(
    docs: list[tuple[str, list[str]]],
    q_terms: set[str],
) -> dict[str, float]:
    """对已分词文档集打 BM25；docs＝[(doc_id, tokens)]。"""
    n_docs = len(docs)
    if n_docs == 0:
        return {}
    df: dict[str, int] = {}
    for _, toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    avgdl = sum(len(toks) for _, toks in docs) / n_docs
    out: dict[str, float] = {}
    for doc_id, toks in docs:
        dl = len(toks)
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for term in q_terms:
            freq = tf.get(term)
            if not freq:
                continue
            idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * freq * (_K1 + 1.0) / (
                freq + _K1 * (1.0 - _B + _B * dl / avgdl))
        out[doc_id] = round(score, 6)
    return out


def chunk_max_scores(
    dossier: Dossier,
    *,
    query: str | None = None,
    queries: list[str] | None = None,
) -> dict[str, float]:
    """块级 BM25 → 按段取 max。多问时对各路做 max 后再 RRF 不合——与段级一致走 RRF：
    各路先得段分（块 max），再 fuse_rankings。"""
    # 建块语料
    chunks: list[tuple[str, str, list[str]]] = []  # (chunk_id, seg_id, toks)
    for src in dossier.sources:
        for seg in src.segments:
            for i, ch in enumerate(split_into_chunks(seg.text or "")):
                cid = f"{seg.id}::c{i}"
                chunks.append((cid, seg.id, _tokens(ch)))
    if not chunks:
        return {seg.id: 0.0 for src in dossier.sources for seg in src.segments}

    docs = [(cid, toks) for cid, _sid, toks in chunks]
    cid_to_seg = {cid: sid for cid, sid, _ in chunks}

    def _one_query(q: str) -> list[tuple[str, float]]:
        q_terms = set(_tokens(q))
        c_scores = _bm25_score_docs(docs, q_terms)
        seg_best: dict[str, float] = {}
        for cid, sc in c_scores.items():
            sid = cid_to_seg[cid]
            if sc > seg_best.get(sid, 0.0):
                seg_best[sid] = sc
        # 补零：无块命中的段
        for src in dossier.sources:
            for seg in src.segments:
                seg_best.setdefault(seg.id, 0.0)
        ranked = sorted(seg_best.items(), key=lambda x: (-x[1], x[0]))
        return ranked

    if queries:
        cleaned = [str(q).strip() for q in queries if str(q).strip()]
        if len(cleaned) > 1:
            return dict(fuse_rankings([_one_query(q) for q in cleaned]))
        if len(cleaned) == 1:
            return dict(_one_query(cleaned[0]))

    raw = query if query is not None else dossier.question
    qtext = expand_query(raw) if query is None else raw
    return dict(_one_query(qtext))


def _budget_from_report(rep: dict) -> int:
    pw = (rep.get("accounting") or {}).get("pack_window") or {}
    b = pw.get("budget")
    if b is None:
        raise ValueError("report 缺 accounting.pack_window.budget")
    return int(b)


def _gold_hit(gold_keys: set[tuple[str, str]], paras: set[str]) -> int:
    return sum(1 for _d, p in gold_keys if p in paras)


def measure_question(
    rp: Path, gold_dir: Path,
) -> dict:
    case, qid = rp.parts[-4], rp.parts[-2]
    rep = json.loads(rp.read_text(encoding="utf-8"))
    dossier = Dossier.from_dict(rep)
    gold, _sk = gold_paras_for_question(gold_dir / case, qid)
    if not gold:
        return {"case": case, "qid": qid, "denom": 0}
    gold_keys = set(gold.keys())
    budget = _budget_from_report(rep)
    queries = pack_search_queries(dossier)

    # ---- A：现码 ----
    from app.core import bm25 as bm25_mod
    from app.core import material as mat_mod
    scores_a = dict(
        bm25_mod.rank_segments(dossier, queries=queries)
        if queries else bm25_mod.rank_segments(dossier))
    pack_a = pack_material(dossier, budget_chars=budget)
    sel_a = {str(x) for x in (pack_a.get("selected") or [])}
    pool_a = {sid for sid, sc in scores_a.items() if sc > 0}

    # ---- B：块级 max ----
    scores_b = chunk_max_scores(
        dossier, queries=queries if queries else None)

    def _fake_rank(dossier_, query=None, queries=None):
        ranked = sorted(scores_b.items(), key=lambda x: (-x[1], x[0]))
        return ranked

    real_rank = bm25_mod.rank_segments
    real_mat_rank = getattr(mat_mod, "rank_segments", real_rank)
    bm25_mod.rank_segments = _fake_rank
    mat_mod.rank_segments = _fake_rank
    try:
        pack_b = pack_material(dossier, budget_chars=budget)
    finally:
        bm25_mod.rank_segments = real_rank
        mat_mod.rank_segments = real_rank

    sel_b = {str(x) for x in (pack_b.get("selected") or [])}
    pool_b = {sid for sid, sc in scores_b.items() if sc > 0}

    gold_paras = {p for _d, p in gold_keys}
    a_l2 = gold_paras & sel_a
    b_l2 = gold_paras & sel_b
    lost = sorted(a_l2 - b_l2)
    gained = sorted(b_l2 - a_l2)

    return {
        "case": case, "qid": qid, "denom": len(gold_keys),
        "budget": budget,
        "pool_a": _gold_hit(gold_keys, pool_a),
        "pool_b": _gold_hit(gold_keys, pool_b),
        "l2_a": len(a_l2),
        "l2_b": len(b_l2),
        "lost": lost,
        "gained": gained,
        "a_keys": sorted(a_l2),
        "b_keys": sorted(b_l2),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="C-58 small→big 件① 探针")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    args = p.parse_args(argv)
    run_dir, gold_dir = Path(args.run_dir), Path(args.gold_dir)
    if not run_dir.is_dir():
        print(f"跑次不存在：{run_dir}", file=sys.stderr)
        return 2

    rows = []
    for rp in discover_reports(run_dir):
        rows.append(measure_question(rp, gold_dir))

    tot = Counter()
    per_case: dict[str, Counter] = {}
    all_lost: list[tuple[str, str, str]] = []
    all_gained: list[tuple[str, str, str]] = []
    for r in rows:
        if not r.get("denom"):
            continue
        c = per_case.setdefault(r["case"], Counter())
        for k in ("denom", "pool_a", "pool_b", "l2_a", "l2_b"):
            c[k] += r[k]
            tot[k] += r[k]
        for para in r["lost"]:
            all_lost.append((r["case"], r["qid"], para))
        for para in r["gained"]:
            all_gained.append((r["case"], r["qid"], para))

    print(f"=== C-58 件① run={run_dir} ===")
    print(f"分母={tot['denom']}  "
          f"A池={tot['pool_a']}/{tot['denom']}  A L2={tot['l2_a']}/{tot['denom']}  "
          f"B池={tot['pool_b']}/{tot['denom']}  B L2={tot['l2_b']}/{tot['denom']}")
    print(f"ΔL2＝{tot['l2_b'] - tot['l2_a']:+d}  "
          f"lost={len(all_lost)}  gained={len(all_gained)}")
    a_ok = tot["l2_a"] == 48 and tot["denom"] == 105
    b_ok = tot["l2_b"] >= 51 and len(all_lost) == 0
    print(f"判据 a（A L2=48/105）：{'✅' if a_ok else '❌'}")
    print(f"判据 b（B L2≥51 且 lost=0）：{'✅' if b_ok else '❌ → 件② 逃逸披露'}")
    print()
    print(f"{'case':32} {'den':>4} {'A池':>4} {'AL2':>4} {'B池':>4} {'BL2':>4}")
    for case, c in sorted(per_case.items()):
        print(f"  {case[:30]:30} {c['denom']:4} {c['pool_a']:4} {c['l2_a']:4} "
              f"{c['pool_b']:4} {c['l2_b']:4}")

    if all_lost:
        print("\nlost 段键（A 有、B 无）：")
        for case, qid, para in all_lost[:40]:
            print(f"  {case[:16]}/{qid} {para}")
    if all_gained:
        print("\ngained 段键（B 有、A 无）：")
        for case, qid, para in all_gained[:40]:
            print(f"  {case[:16]}/{qid} {para}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
