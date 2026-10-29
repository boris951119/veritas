#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-94：纯自切通路只量（召回→精排→装箱全在 hier-v1；映回伪 L2）。

Boyu 要测：整条链路跑在自切上，**不用**官方 para_id 当候选池／装箱单位。
正式 L2／交卷仍只认官方段——本票产出的是**映回伪分**，不得写入主 L2 过线表。

一对多归并（与 C-93 同形，写死）：
  1. 自切段 [s,e) ∩ 官方段 [os,oe) 交叠 ov>0 ⇒ 映射到该 para_id；
  2. 一条自切可映多个官方段（全保留）；
  3. 装箱选中的自切集合 → 并集其映射 para_id → 与金标求交＝映回伪 L2；
  4. ov==0 或定位失败 ⇒ 该自切段不计金标覆盖（map_fail）。

对照臂：
  A0         官方切 + pack_material → **真 L2**
  S_self     自切案卷 + pack_material（现产密度键）→ 映回伪 L2
  S_self_pri 自切案卷 + 分主序装箱（可选变体）→ 映回伪 L2

解读门槛（本票专用，非生产 gate_b）：
  伪 L2≤A0 或 lost 大 ⇒ 问题不在「官方切太碎／太粗」；
  伪 L2 明显高于 A0 且 lost↓ ⇒ 仅可讨论赛道外双轨叙事，仍不得合入交卷。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c94_self_cut_pack.py \\
      --run-dir /tmp/six2 --smoke --out-dir /tmp/c94_self
  PYTHONPATH=. .venv/bin/python scripts/probe_c94_self_cut_pack.py \\
      --run-dir /tmp/six2 --out-dir /tmp/c94_self
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bm25 import rank_segments  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from app.ingest.segment import SEGMENTER_VERSION  # noqa: E402
from scripts.probe_c66_multi_box import (  # noqa: E402
    _budget_from_report,
    l2_hits,
    selected_locs,
)
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_c91_mono_pack import _pack_score_primary  # noqa: E402
from scripts.probe_c93_dual_cut import (  # noqa: E402
    _load_raw_docs,
    build_self_cut_dossier,
)
from scripts.probe_recall_funnel import DEFAULT_GOLD, discover_reports  # noqa: E402

# C-93 六案最好臂（交账并排）
C93_BEST = {"arm": "union_rrf", "l2_hits": 47, "lost_n": 7, "a0_probe": 46}


def _para_to_gold_key(
    para_id: str, official_paras: dict[str, dict],
) -> tuple[str, str] | None:
    meta = official_paras.get(para_id)
    if meta:
        return str(meta["doc_id"]), str(para_id)
    # 退化：para_id 形如 doc_001#p3
    if "#" in para_id:
        doc = para_id.split("#", 1)[0]
        return doc, para_id
    return None


def map_selected_self_to_gold_locs(
    selected: set[str],
    self_to_official: dict[str, list[str]],
    official_paras: dict[str, dict],
) -> tuple[set[tuple[str, str]], dict[str, int]]:
    """自切选中集 → 官方金标键集合；附映射统计。"""
    locs: set[tuple[str, str]] = set()
    stats = Counter()
    for sid in selected:
        targets = self_to_official.get(sid) or []
        if not targets:
            stats["selected_unmapped"] += 1
            continue
        stats["selected_mapped"] += 1
        for pid in targets:
            key = _para_to_gold_key(pid, official_paras)
            if key is None:
                stats["para_key_fail"] += 1
                continue
            locs.add(key)
            stats["mapped_para_n"] += 1
    return locs, dict(stats)


def run_question(
    *,
    case: str,
    qid: str,
    query: str,
    budget: int,
    gold_dir: Path,
    case_dir: Path,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    raw = _load_raw_docs(case_dir)
    off_d = load_official_case(case_dir)
    off_d.question = query
    self_d, cut_meta = build_self_cut_dossier(raw)
    self_d.question = query

    gold, denom = _gold_keys(gold_dir, case, qid)
    if denom == 0:
        return {"case": case, "qid": qid, "skip": True}

    # ---- A0 真 L2 ----
    p0 = pack_material(off_d, budget_chars=budget)
    sel_a0 = {str(x) for x in (p0.get("selected") or [])}
    loc_a0 = selected_locs(off_d, sel_a0)
    hits_a0 = l2_hits(gold, loc_a0)

    n_off = sum(len(s.segments) for s in off_d.sources)
    n_self = cut_meta["n_self"]

    # ---- S_self：纯自切装箱 ----
    p_self = pack_material(self_d, budget_chars=budget)
    sel_self = {str(x) for x in (p_self.get("selected") or [])}
    loc_pseudo, map_stats = map_selected_self_to_gold_locs(
        sel_self, cut_meta["self_to_official"], cut_meta["official_paras"])
    hits_pseudo = l2_hits(gold, loc_pseudo)
    lost_pseudo = len((gold & loc_a0) - loc_pseudo)
    gained_pseudo = len((gold & loc_pseudo) - loc_a0)

    # 自切池内「碰到金标」的选中段数（overlap 映到任一金标 para）
    gold_paras = {p for _d, p in gold}
    n_self_hit_gold = 0
    for sid in sel_self:
        targets = set(cut_meta["self_to_official"].get(sid) or [])
        if targets & gold_paras:
            n_self_hit_gold += 1

    # ---- S_self_pri：分主序变体 ----
    ranked = rank_segments(self_d)
    scores = {sid: float(sc) for sid, sc in ranked}
    for src in self_d.sources:
        for seg in src.segments:
            scores.setdefault(seg.id, 0.0)
    sel_pri = _pack_score_primary(self_d, budget, scores)
    loc_pri, map_stats_pri = map_selected_self_to_gold_locs(
        sel_pri, cut_meta["self_to_official"], cut_meta["official_paras"])
    hits_pri = l2_hits(gold, loc_pri)
    lost_pri = len((gold & loc_a0) - loc_pri)
    gained_pri = len((gold & loc_pri) - loc_a0)

    return {
        "case": case, "qid": qid, "denom": denom, "budget": budget,
        "skip": False,
        "score_kind": "pseudo_L2_via_overlap_map",
        "a0_true_l2": hits_a0,
        "a0_n": len(sel_a0),
        "n_official_segs": n_off,
        "n_self_segs": n_self,
        "n_locate_fail": cut_meta["n_locate_fail"],
        "n_map_empty_segs": cut_meta["n_map_empty"],
        "S_self_pseudo_l2": hits_pseudo,
        "S_self_lost_vs_a0": lost_pseudo,
        "S_self_gained_vs_a0": gained_pseudo,
        "S_self_n": len(sel_self),
        "S_self_selected_unmapped": map_stats.get("selected_unmapped", 0),
        "S_self_selected_mapped": map_stats.get("selected_mapped", 0),
        "S_self_n_hit_gold_seg": n_self_hit_gold,
        "S_self_pri_pseudo_l2": hits_pri,
        "S_self_pri_lost_vs_a0": lost_pri,
        "S_self_pri_gained_vs_a0": gained_pri,
        "S_self_pri_n": len(sel_pri),
        "elapsed_s": round(time.perf_counter() - t0, 3),
    }


def collect_jobs(run_dir: Path, *, smoke: bool) -> list[dict]:
    jobs = []
    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        jobs.append({
            "case": case, "qid": qid,
            "query": str(rep.get("question") or ""),
            "budget": _budget_from_report(rep),
        })
    jobs.sort(key=lambda j: (j["case"], j["qid"]))
    if smoke:
        want = []
        for pref in ("吉隆", "刘翔"):
            for j in jobs:
                if pref in j["case"] and j["qid"] == "q_001":
                    want.append(j)
                    break
        return want or jobs[:2]
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", default="/tmp/six2")
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--out-dir", default="/tmp/c94_self")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gold_dir = Path(args.gold_dir)

    jobs = collect_jobs(Path(args.run_dir), smoke=args.smoke)
    print(
        f"======== C-94 纯自切通路只量（伪分）"
        f"{'（烟雾）' if args.smoke else ''} ========",
        flush=True,
    )
    print(
        f"⚠ 本票 L2 为映回伪分，非正式赛道 L2；segmenter={SEGMENTER_VERSION}",
        flush=True,
    )

    rows = []
    tot = Counter()
    t_all = time.perf_counter()
    for job in jobs:
        case_dir = gold_dir / job["case"]
        if not (case_dir / "raw_documents.json").is_file():
            continue
        row = run_question(
            case=job["case"], qid=job["qid"], query=job["query"],
            budget=job["budget"], gold_dir=gold_dir, case_dir=case_dir,
        )
        if row.get("skip"):
            continue
        rows.append(row)
        tot["denom"] += row["denom"]
        tot["a0"] += row["a0_true_l2"]
        tot["pseudo"] += row["S_self_pseudo_l2"]
        tot["lost"] += row["S_self_lost_vs_a0"]
        tot["gained"] += row["S_self_gained_vs_a0"]
        tot["pri"] += row["S_self_pri_pseudo_l2"]
        tot["pri_lost"] += row["S_self_pri_lost_vs_a0"]
        tot["pri_gained"] += row["S_self_pri_gained_vs_a0"]
        tot["n_off"] += row["n_official_segs"]
        tot["n_self"] += row["n_self_segs"]
        tot["locate_fail"] += row["n_locate_fail"]
        tot["map_empty"] += row["n_map_empty_segs"]
        tot["sel_unmap"] += row["S_self_selected_unmapped"]
        tot["sel_map"] += row["S_self_selected_mapped"]
        print(
            f"  {row['case'][:14]} {row['qid']}: "
            f"A0真={row['a0_true_l2']}/{row['denom']} "
            f"S伪={row['S_self_pseudo_l2']}"
            f"(L{row['S_self_lost_vs_a0']}G{row['S_self_gained_vs_a0']}) "
            f"pri伪={row['S_self_pri_pseudo_l2']} "
            f"segs {row['n_self_segs']}/{row['n_official_segs']} "
            f"unmap_sel={row['S_self_selected_unmapped']} "
            f"{row['elapsed_s']}s",
            flush=True,
        )

    denom = int(tot["denom"])
    a0 = int(tot["a0"])
    pseudo = int(tot["pseudo"])
    lost = int(tot["lost"])
    gained = int(tot["gained"])
    # 解读门槛
    if pseudo <= a0 or lost > 0:
        verdict = (
            "解读＝伪L2未优于A0或lost>0 ⇒ 问题不在「官方切太碎／太粗」；"
            "默认不进生产"
        )
        escape = True
    else:
        verdict = (
            "解读＝伪L2明显高于A0且lost↓ ⇒ 仅可讨论赛道外双轨叙事；"
            "仍不得合入交卷／默认关"
        )
        escape = False

    summary = {
        "ticket": "C-94",
        "score_kind": "pseudo_L2_via_overlap_map_NOT_official_L2",
        "smoke": bool(args.smoke),
        "n_questions": len(rows),
        "denom": denom,
        "A0_true_l2": a0,
        "S_self_pseudo_l2": pseudo,
        "S_self_lost_vs_a0": lost,
        "S_self_gained_vs_a0": gained,
        "S_self_pri_pseudo_l2": int(tot["pri"]),
        "S_self_pri_lost_vs_a0": int(tot["pri_lost"]),
        "S_self_pri_gained_vs_a0": int(tot["pri_gained"]),
        "vs_a0_delta_pseudo": pseudo - a0,
        "segs": {
            "n_official_sum": int(tot["n_off"]),
            "n_self_sum": int(tot["n_self"]),
            "ratio_self_over_off": round(
                tot["n_self"] / max(tot["n_off"], 1), 4),
        },
        "mapping": {
            "n_locate_fail": int(tot["locate_fail"]),
            "n_map_empty_segs": int(tot["map_empty"]),
            "selected_mapped": int(tot["sel_map"]),
            "selected_unmapped": int(tot["sel_unmap"]),
            "selected_unmap_rate": round(
                tot["sel_unmap"] / max(tot["sel_map"] + tot["sel_unmap"], 1), 4),
        },
        "c93_best_side_by_side": C93_BEST,
        "interpretation_escape": escape,
        "interpretation": verdict,
        "elapsed_s": round(time.perf_counter() - t_all, 3),
        "segmenter": SEGMENTER_VERSION,
        "rows": rows,
    }

    print("-------- 合计（伪分表）--------", flush=True)
    print(f"A0 真 L2 = {a0}/{denom}", flush=True)
    print(
        f"S_self 映回伪 L2 = {pseudo}/{denom} "
        f"lost={lost} gained={gained} ΔA0={pseudo - a0:+d}",
        flush=True,
    )
    print(
        f"S_self_pri 伪 L2 = {int(tot['pri'])}/{denom} "
        f"lost={int(tot['pri_lost'])} gained={int(tot['pri_gained'])}",
        flush=True,
    )
    print(
        f"段数合计 自切/官方 = {int(tot['n_self'])}/{int(tot['n_off'])}",
        flush=True,
    )
    print("映射:", json.dumps(summary["mapping"], ensure_ascii=False), flush=True)
    print(
        f"并排 C-93 最好臂 {C93_BEST['arm']}: "
        f"L2={C93_BEST['l2_hits']} lost={C93_BEST['lost_n']} "
        f"(当时探针A0={C93_BEST['a0_probe']})",
        flush=True,
    )
    print(verdict, flush=True)
    print(f"耗时 {summary['elapsed_s']}s", flush=True)

    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"落盘 {out / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
