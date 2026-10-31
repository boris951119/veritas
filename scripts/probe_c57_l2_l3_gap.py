#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-57 件①：L2→L3 漏掉的金标段四桶归因（只量、零模型、app/ 零 diff）。

分母＝金标 (doc_id, para_id)；缺口＝L2 命中集 − L3 命中集（须复现 34）。
四桶（互斥，优先级 a→c→d→b→miss）：
  a  SEGMENT_MAX=650 截断后金标句不可见
  b  提示词内，但同源另段被引用（邻近竞争）
  c  分析师引了，被 citation_check 逐字闸打回（report.rejected）
  d  曾挂在结论上，后在归并／冲突／不足路径上消解（不足结论／conflict_drops）
  miss 可见且无上述痕迹＝模型未引（仍报条数；不算主因桶 a 的逃逸）

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c57_l2_l3_gap.py \\
    --run-dir /tmp/s4runs/c57-baseline-105
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.citation_check import normalize  # noqa: E402
from app.core.evidence import Dossier  # noqa: E402
from app.ingest.segment import SEGMENT_MAX  # noqa: E402
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD,
    cited_hits,
    discover_reports,
    gold_paras_for_question,
    reconstruct_pack_selected,
)

_SID_IN_PROB = re.compile(r"（([^）]+)）|\(([^)]+)\)")


def _seg_source_map(dossier: Dossier) -> dict[str, str]:
    out: dict[str, str] = {}
    for src in dossier.sources:
        for seg in src.segments:
            out[str(seg.id)] = src.id
    return out


def _visible_prefix(text: str, cap: int = SEGMENT_MAX) -> str:
    return (text or "")[: int(cap)]


def _bucket_a(seg_text: str, gold_quotes: set[str]) -> bool:
    """金标句只在 650 字之后才出现（模型看不见）。"""
    full = seg_text or ""
    vis = _visible_prefix(full)
    n_full, n_vis = normalize(full), normalize(vis)
    for q in gold_quotes:
        qn = normalize(q)
        if not qn:
            continue
        in_full = qn in n_full
        in_vis = qn in n_vis
        if in_full and not in_vis:
            return True
        # 无归一化原文索引：找 raw 第一次出现
        raw_i = full.find(q) if q else -1
        if raw_i >= SEGMENT_MAX:
            return True
    return False


def _rejected_paras(rep: dict) -> set[str]:
    """从 report.rejected 抽出被闸打回的 segment_id。"""
    out: set[str] = set()
    for row in rep.get("rejected") or []:
        for prob in row.get("problems") or []:
            for m in _SID_IN_PROB.finditer(str(prob)):
                sid = m.group(1) or m.group(2) or ""
                if sid:
                    out.add(sid)
        # 若有显式字段
        for sid in row.get("segment_ids") or []:
            out.add(str(sid))
    return out


def _rejected_quotes(rep: dict) -> set[str]:
    return {normalize(str(r.get("quote") or ""))
            for r in (rep.get("rejected") or [])
            if normalize(str(r.get("quote") or ""))}


def _insufficient_paras(dossier: Dossier) -> set[str]:
    """status=insufficient 结论上仍挂着的段（证据已被摘光时看 statement 不够，
    回看 accounting 不够——用 conclusions 里仍残留的 segment 关联：
    不足结论通常 evidences 已空；退而求其次：看 panel 原始？此处用
    rejected 已覆盖引文闸；d 再看 conflict_drops 名单。"""
    out: set[str] = set()
    for con in dossier.conclusions:
        if getattr(con, "status", None) != "insufficient":
            continue
        for ev in dossier.evidences_of(con.id):
            for sid in ev.segment_ids or []:
                out.add(str(sid))
    return out


def _conflict_drop_paras(rep: dict) -> set[str]:
    drops = ((rep.get("accounting") or {}).get("conflict_drops") or {})
    out: set[str] = set()
    for key in ("dropped_segment_ids", "segment_ids", "dropped_paras"):
        for sid in drops.get(key) or []:
            out.add(str(sid))
    for row in drops.get("dropped") or []:
        if isinstance(row, dict):
            for sid in row.get("segment_ids") or []:
                out.add(str(sid))
            para = row.get("para_id") or row.get("segment_id")
            if para:
                out.add(str(para))
        elif isinstance(row, str):
            out.add(row)
    return out


def classify_gap(
    para: str,
    *,
    seg_text: str,
    gold_quotes: set[str],
    src_id: str,
    l3_paras: set[str],
    seg2src: dict[str, str],
    rejected_paras: set[str],
    rejected_quotes: set[str],
    insuff_paras: set[str],
    conflict_paras: set[str],
) -> str:
    if _bucket_a(seg_text, gold_quotes):
        return "a"
    if para in rejected_paras or any(
            normalize(q) in rejected_quotes for q in gold_quotes if q):
        return "c"
    if para in insuff_paras or para in conflict_paras:
        return "d"
    # 同源另段在 L3
    sib_cited = any(
        p != para and seg2src.get(p) == src_id
        for p in l3_paras
    )
    if sib_cited:
        return "b"
    return "miss"


_FIXABLE = {
    "a": "不可修（本票禁抬 SEGMENT_MAX；逃逸口）",
    "b": "可修（prompts／second_pass focus）",
    "c": "可修（repair 触发；禁弱化逐字闸）",
    "d": "可修边缘（归并／冲突路径；本票白名单外需另开）",
    "miss": "可修（prompts／second_pass；模型未引）",
}


def measure(run_dir: Path, gold_dir: Path) -> dict:
    per_case: dict[str, dict] = {}
    tot = Counter()
    gaps: list[dict] = []

    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(rep)
        gold, _sk = gold_paras_for_question(gold_dir / case, qid)
        if not gold:
            continue
        pack_sel, _n = reconstruct_pack_selected(dossier)
        _hp, _hq, hit_either = cited_hits(gold, dossier)
        l2_keys = {(d, p) for d, p in gold if p in pack_sel}
        l3_keys = {k for k in gold if k in hit_either}
        gap_keys = l2_keys - l3_keys

        c = per_case.setdefault(case, {
            "denom": 0, "l2": 0, "l3": 0, "gap": 0, "buckets": Counter(),
        })
        c["denom"] += len(gold)
        c["l2"] += len(l2_keys)
        c["l3"] += len(l3_keys)
        c["gap"] += len(gap_keys)
        tot["denom"] += len(gold)
        tot["l2"] += len(l2_keys)
        tot["l3"] += len(l3_keys)
        tot["gap"] += len(gap_keys)

        seg2src = _seg_source_map(dossier)
        l3_paras = {p for _d, p in l3_keys}
        rej_paras = _rejected_paras(rep)
        rej_quotes = _rejected_quotes(rep)
        insuff = _insufficient_paras(dossier)
        confl = _conflict_drop_paras(rep)

        for doc, para in sorted(gap_keys):
            seg = dossier.segment(para)
            text = seg.text if seg else ""
            src_id = seg2src.get(para, "")
            b = classify_gap(
                para,
                seg_text=text,
                gold_quotes=gold[(doc, para)],
                src_id=src_id,
                l3_paras=l3_paras,
                seg2src=seg2src,
                rejected_paras=rej_paras,
                rejected_quotes=rej_quotes,
                insuff_paras=insuff,
                conflict_paras=confl,
            )
            c["buckets"][b] += 1
            tot[f"b_{b}"] += 1
            gaps.append({
                "case": case, "qid": qid, "doc": doc, "para": para,
                "src": src_id, "bucket": b, "fix": len(text),
                "fixable": _FIXABLE[b],
            })

    return {"per_case": per_case, "tot": dict(tot), "gaps": gaps}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="C-57 L2→L3 四桶归因")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    args = p.parse_args(argv)
    run_dir, gold_dir = Path(args.run_dir), Path(args.gold_dir)
    out = measure(run_dir, gold_dir)
    tot = out["tot"]
    print(f"=== C-57 件① run={run_dir} ===")
    print(f"分母={tot.get('denom', 0)}  L2={tot.get('l2', 0)}  "
          f"L3={tot.get('l3', 0)}  gap(L2−L3)={tot.get('gap', 0)}")
    print(f"判据 a 复现 34：{'✅' if tot.get('gap') == 34 else '❌'}")
    print()
    print("四桶合计：")
    for b in ("a", "b", "c", "d", "miss"):
        n = tot.get(f"b_{b}", 0)
        print(f"  {b}: {n:3d}  {_FIXABLE[b]}")
    print()
    print(f"{'case':32} {'den':>4} {'L2':>3} {'L3':>3} {'gap':>3} "
          f"{'a':>3} {'b':>3} {'c':>3} {'d':>3} {'miss':>4}")
    for case, c in sorted(out["per_case"].items()):
        bk = c["buckets"]
        print(f"  {case[:30]:30} {c['denom']:4} {c['l2']:3} {c['l3']:3} "
              f"{c['gap']:3} {bk.get('a', 0):3} {bk.get('b', 0):3} "
              f"{bk.get('c', 0):3} {bk.get('d', 0):3} {bk.get('miss', 0):4}")

    # 主因桶
    counts = {b: tot.get(f"b_{b}", 0) for b in ("a", "b", "c", "d", "miss")}
    main = max(counts, key=counts.get)
    print()
    print(f"主因桶＝{main}（{counts[main]}）")
    if main == "a":
        print("逃逸口：主因＝截断 ⇒ 件② 不动码，只披露（禁抬 SEGMENT_MAX）")
    else:
        print(f"件② 可动白名单侧（主因 {main}＝{_FIXABLE[main]}）")

    # 逐段（截断打印）
    print("\n逐段缺口（前 40）：")
    for g in out["gaps"][:40]:
        print(f"  {g['case'][:14]}/{g['qid']} {g['para']:20} "
                f"bucket={g['bucket']} len={g['len']} {g['fixable']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
