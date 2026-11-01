#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-96：关零分灌满 ± 槽覆盖装箱（刘翔主尺只量）。

Boyu 拍：固定规则槽（claim_slots.extract_slots＝时间／数字／原因／状态／what）、
不满窗可接受、先只量默认关；LLM 标签／因果不上本票。

臂：
  A0          现产 pack_material（密度键＋零分轮转灌满）
  NoFill      fill_zero_score=False（仍密度键）
  NoFillPri   分主序＋关灌满（弱化密度）
  SlotCover   规则槽覆盖贪心 → 再 BM25>0 分主序填剩余 → 关灌满
  SlotOnly    只做槽覆盖（+priority），**不**用 BM25 填满＝真·不满窗

门槛（刘翔尺）：
  - 硬过线＝lost=0 且 L2≥A0
  - 合入候选还要 gained>0（Δ=0 记 FLAT，不算涨分）
只量、生产零 diff；不 commit。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c96_slot_cover.py \\
      --out-dir /tmp/c96_slot
  PYTHONPATH=. .venv/bin/python scripts/probe_c96_slot_cover.py --smoke
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

from app.core.answer_slots import priority_segment_ids  # noqa: E402
from app.core.bm25 import rank_segments  # noqa: E402
from app.core.claim_slots import (  # noqa: E402
    _slot_covered_by_text,
    extract_slots,
)
from app.core.dup_check import duplicate_map  # noqa: E402
from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material, pack_search_queries  # noqa: E402
from app.core.relevance import classify_sources  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from app.ingest.segment import SEGMENT_MAX  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

CASE_SUB = "刘翔"
# 冻结自 /tmp/c85_k180/score_input.json（report 路径可失效；预算／问句仍用）
DEFAULT_C85 = Path("/tmp/c85_k180")
DEFAULT_CASES = DEFAULT_GOLD


def _billing_len(text: str) -> int:
    return min(len(text or ""), int(SEGMENT_MAX))


def _eligible(dossier: Dossier) -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
    """lengths / seg→src / texts。资格线与 pack_material 同形。"""
    dups = duplicate_map(dossier)
    relevance = {s["source_id"]: s for s in classify_sources(dossier)}
    lengths: dict[str, int] = {}
    seg_src: dict[str, str] = {}
    texts: dict[str, str] = {}
    for src in dossier.sources:
        if src.id in dups or (relevance.get(src.id) or {}).get("level") == "zero":
            continue
        for seg in src.segments:
            lengths[seg.id] = _billing_len(seg.text)
            seg_src[seg.id] = src.id
            texts[seg.id] = seg.text or ""
    if not lengths:
        for src in dossier.sources:
            if src.id in dups:
                continue
            for seg in src.segments:
                lengths[seg.id] = _billing_len(seg.text)
                seg_src[seg.id] = src.id
                texts[seg.id] = seg.text or ""
    return lengths, seg_src, texts


def _bm25_scores(dossier: Dossier) -> dict[str, float]:
    queries = pack_search_queries(dossier)
    ranked = (
        rank_segments(dossier, queries=queries)
        if queries else rank_segments(dossier)
    )
    return {str(k): float(v) for k, v in dict(ranked).items()}


def _pack_nofill_pri(
    dossier: Dossier, budget: int, scores: dict[str, float],
) -> dict[str, Any]:
    """分主序 + 关零分灌满；议题 priority 仍先装。"""
    budget = max(1, int(budget))
    lengths, _, _ = _eligible(dossier)
    selected: set[str] = set()
    used = 0

    def _take(seg_id: str) -> bool:
        nonlocal used
        if seg_id in selected or seg_id not in lengths:
            return False
        ln = lengths[seg_id]
        if used + ln > budget:
            return False
        selected.add(seg_id)
        used += ln
        return True

    for seg_id in priority_segment_ids(dossier):
        _take(seg_id)
    scored = [
        g for g in lengths
        if scores.get(g, 0.0) > 0.0 and g not in selected
    ]
    for seg_id in sorted(scored, key=lambda g: (-scores.get(g, 0.0), g)):
        if used >= budget:
            break
        _take(seg_id)
    return {
        "selected": selected,
        "used_chars": used,
        "budget": budget,
        "fill_ratio": round(used / budget, 4) if budget else 0.0,
        "n_selected": len(selected),
    }


def _seg_covers(slot: dict, text: str) -> bool:
    return bool(_slot_covered_by_text(slot, text or ""))


def _pack_slot_cover(
    dossier: Dossier,
    budget: int,
    scores: dict[str, float],
    slots: list[dict],
    *,
    fill_bm25: bool = True,
) -> dict[str, Any]:
    """槽覆盖贪心；fill_bm25=True 再 BM25>0 分主序填剩余；从不零分灌满。"""
    budget = max(1, int(budget))
    lengths, _, texts = _eligible(dossier)
    selected: set[str] = set()
    used = 0
    covered: set[str] = set()
    cover_log: list[dict[str, Any]] = []

    def _take(seg_id: str) -> bool:
        nonlocal used
        if seg_id in selected or seg_id not in lengths:
            return False
        ln = lengths[seg_id]
        if used + ln > budget:
            return False
        selected.add(seg_id)
        used += ln
        return True

    # ① 议题 priority（与生产同形）
    for seg_id in priority_segment_ids(dossier):
        if _take(seg_id):
            newly = []
            for sl in slots:
                sid = sl["id"]
                if sid in covered:
                    continue
                if _seg_covers(sl, texts.get(seg_id, "")):
                    covered.add(sid)
                    newly.append(sid)
            if newly:
                cover_log.append({"seg": seg_id, "phase": "priority", "new": newly})

    # ② 槽覆盖贪心：边际新槽数 ↓、BM25 ↓、id
    pending = [g for g in lengths if g not in selected]
    while used < budget and slots and len(covered) < len(slots):
        best = None
        best_key = None
        for g in pending:
            ln = lengths[g]
            if used + ln > budget:
                continue
            text = texts.get(g, "")
            new_ids = [
                sl["id"] for sl in slots
                if sl["id"] not in covered and _seg_covers(sl, text)
            ]
            if not new_ids:
                continue
            key = (-len(new_ids), -scores.get(g, 0.0), g)
            if best_key is None or key < best_key:
                best_key = key
                best = (g, new_ids)
        if best is None:
            break
        g, new_ids = best
        if not _take(g):
            break
        for sid in new_ids:
            covered.add(sid)
        cover_log.append({"seg": g, "phase": "slot", "new": list(new_ids)})
        pending = [x for x in pending if x != g]

    # ③ 可选：BM25>0 分主序填剩余（关灌满）
    if fill_bm25:
        scored = [
            g for g in lengths
            if scores.get(g, 0.0) > 0.0 and g not in selected
        ]
        for seg_id in sorted(scored, key=lambda g: (-scores.get(g, 0.0), g)):
            if used >= budget:
                break
            if _take(seg_id):
                newly = []
                for sl in slots:
                    sid = sl["id"]
                    if sid in covered:
                        continue
                    if _seg_covers(sl, texts.get(seg_id, "")):
                        covered.add(sid)
                        newly.append(sid)
                if newly:
                    cover_log.append(
                        {"seg": seg_id, "phase": "bm25", "new": newly})

    missed = [sl["id"] for sl in slots if sl["id"] not in covered]
    return {
        "selected": selected,
        "used_chars": used,
        "budget": budget,
        "fill_ratio": round(used / budget, 4) if budget else 0.0,
        "n_selected": len(selected),
        "slots": [{"id": s["id"], "label": s["label"]} for s in slots],
        "covered": sorted(covered),
        "missed": missed,
        "cover_log": cover_log,
        "fill_bm25": fill_bm25,
    }


def _load_lx_jobs(c85_dir: Path) -> list[dict]:
    path = c85_dir / "score_input.json"
    if not path.is_file():
        raise SystemExit(f"缺 {path}（预算／问句冻结源）")
    jobs = json.loads(path.read_text(encoding="utf-8"))
    out = [j for j in jobs if CASE_SUB in j["case"]]
    if len(out) != 3:
        raise SystemExit(f"期望刘翔 3 问，实得 {len(out)}")
    return sorted(out, key=lambda j: j["qid"])


def _eval(
    gold: set, loc_a0: set, dossier: Dossier, selected: set[str],
) -> tuple[int, int, int, set]:
    loc = selected_locs(dossier, selected)
    hits = l2_hits(gold, loc)
    lost = len((gold & loc_a0) - loc)
    gained = len((gold & loc) - loc_a0)
    return hits, lost, gained, loc


def run_all(
    *,
    gold_dir: Path,
    cases_root: Path,
    c85_dir: Path,
    smoke_qid: str | None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    jobs = _load_lx_jobs(c85_dir)
    if smoke_qid:
        jobs = [j for j in jobs if j["qid"] == smoke_qid]
        if not jobs:
            raise SystemExit(f"smoke 无此问 {smoke_qid}")

    rows: list[dict[str, Any]] = []
    tot = Counter()

    for job in jobs:
        case = job["case"]
        qid = job["qid"]
        query = job["query"]
        budget = int(job["budget"])
        case_dir = cases_root / case
        if not case_dir.is_dir():
            raise SystemExit(f"缺案卷目录 {case_dir}")

        dossier = load_official_case(case_dir)
        dossier.question = query
        gold, denom = _gold_keys(gold_dir, case, qid)
        scores = _bm25_scores(dossier)
        slots = extract_slots(query)

        p0 = pack_material(dossier, budget_chars=budget)
        sel_a0 = {str(x) for x in (p0.get("selected") or [])}
        loc_a0 = selected_locs(dossier, sel_a0)
        a0_hits = l2_hits(gold, loc_a0)

        p_nf = pack_material(
            dossier, budget_chars=budget, fill_zero_score=False)
        sel_nf = {str(x) for x in (p_nf.get("selected") or [])}
        h_nf, lo_nf, g_nf, _ = _eval(gold, loc_a0, dossier, sel_nf)

        p_pri = _pack_nofill_pri(dossier, budget, scores)
        sel_pri = p_pri["selected"]
        h_pri, lo_pri, g_pri, _ = _eval(gold, loc_a0, dossier, sel_pri)

        p_sc = _pack_slot_cover(dossier, budget, scores, slots, fill_bm25=True)
        sel_sc = p_sc["selected"]
        h_sc, lo_sc, g_sc, _ = _eval(gold, loc_a0, dossier, sel_sc)

        p_so = _pack_slot_cover(dossier, budget, scores, slots, fill_bm25=False)
        sel_so = p_so["selected"]
        h_so, lo_so, g_so, _ = _eval(gold, loc_a0, dossier, sel_so)

        def _arm_row(h, lo, g, n, used, fill, **extra):
            out = {
                "hits": h, "lost": lo, "gained": g, "n": n,
                "used": used, "fill_ratio": fill,
            }
            out.update(extra)
            return out

        row = {
            "case": case, "qid": qid, "denom": denom, "budget": budget,
            "query": query,
            "slots": p_sc["slots"],
            "A0": {
                "hits": a0_hits, "n": len(sel_a0),
                "used": int(p0.get("used_chars") or 0),
                "fill_ratio": round(
                    int(p0.get("used_chars") or 0) / budget, 4),
                "n_zero_score_in_pack": sum(
                    1 for s in sel_a0 if scores.get(s, 0.0) <= 0.0),
            },
            "NoFill": _arm_row(
                h_nf, lo_nf, g_nf, len(sel_nf),
                int(p_nf.get("used_chars") or 0),
                round(int(p_nf.get("used_chars") or 0) / budget, 4),
            ),
            "NoFillPri": _arm_row(
                h_pri, lo_pri, g_pri, p_pri["n_selected"],
                p_pri["used_chars"], p_pri["fill_ratio"],
            ),
            "SlotCover": _arm_row(
                h_sc, lo_sc, g_sc, p_sc["n_selected"],
                p_sc["used_chars"], p_sc["fill_ratio"],
                covered=p_sc["covered"], missed=p_sc["missed"],
                n_slot_picks=sum(
                    1 for x in p_sc["cover_log"] if x["phase"] == "slot"),
            ),
            "SlotOnly": _arm_row(
                h_so, lo_so, g_so, p_so["n_selected"],
                p_so["used_chars"], p_so["fill_ratio"],
                covered=p_so["covered"], missed=p_so["missed"],
                n_slot_picks=sum(
                    1 for x in p_so["cover_log"] if x["phase"] == "slot"),
            ),
        }
        rows.append(row)
        tot["denom"] += denom
        tot["a0"] += a0_hits
        for arm, h, lo, g in (
            ("NoFill", h_nf, lo_nf, g_nf),
            ("NoFillPri", h_pri, lo_pri, g_pri),
            ("SlotCover", h_sc, lo_sc, g_sc),
            ("SlotOnly", h_so, lo_so, g_so),
        ):
            tot[f"{arm}_hits"] += h
            tot[f"{arm}_lost"] += lo
            tot[f"{arm}_gained"] += g

    def _arm_summary(name: str) -> dict[str, Any]:
        hits = int(tot[f"{name}_hits"])
        lost = int(tot[f"{name}_lost"])
        gained = int(tot[f"{name}_gained"])
        a0 = int(tot["a0"])
        hard = lost == 0 and hits >= a0
        return {
            "hits": hits, "lost": lost, "gained": gained,
            "denom": int(tot["denom"]), "a0": a0,
            "hard_pass": hard,
            "improve_pass": hard and gained > 0,
            "delta_vs_a0": hits - a0,
            "status": (
                "IMPROVE" if hard and gained > 0
                else ("FLAT" if hard else "ESCAPE")
            ),
        }

    arms = ("NoFill", "NoFillPri", "SlotCover", "SlotOnly")
    summary = {
        "ruler": "刘翔",
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "A0_hits": int(tot["a0"]),
        "gate": "hard=lost0∧L2≥A0；合入候选还要 gained>0",
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "note": (
            "只量；生产默认关；LLM 标签／因果不在本票；"
            "槽＝claim_slots.extract_slots（零金标）；"
            "刘翔上 A0 零分灌满段数常为 0⇒NoFill 与 A0 同形属预期"
        ),
    }
    for a in arms:
        summary[a] = _arm_summary(a)
    summary["fill_ratio_mean"] = {
        arm: round(
            sum(r[arm]["fill_ratio"] for r in rows) / max(len(rows), 1), 4)
        for arm in ("A0",) + arms
    }
    a0_zero = sum(r["A0"].get("n_zero_score_in_pack", 0) for r in rows)
    summary["A0_zero_score_segs_total"] = a0_zero
    if any(summary[a]["improve_pass"] for a in arms):
        summary["verdict"] = "PASS_CANDIDATE"
    elif any(summary[a]["hard_pass"] for a in arms):
        summary["verdict"] = "FLAT_no_gain"
    else:
        summary["verdict"] = "ESCAPE"
    return {"summary": summary, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="C-96 slot-cover pack (LiuXiang)")
    ap.add_argument("--out-dir", type=Path, default=Path("/tmp/c96_slot"))
    ap.add_argument("--gold-dir", type=Path, default=None)
    ap.add_argument("--cases-root", type=Path, default=None)
    ap.add_argument("--c85-dir", type=Path, default=DEFAULT_C85)
    ap.add_argument("--smoke", action="store_true",
                    help="只跑 q_001")
    ap.add_argument("--smoke-qid", default=None)
    args = ap.parse_args()
    gold_dir = args.gold_dir or DEFAULT_GOLD
    cases_root = args.cases_root or DEFAULT_CASES
    smoke_qid = args.smoke_qid or ("q_001" if args.smoke else None)

    result = run_all(
        gold_dir=gold_dir,
        cases_root=cases_root,
        c85_dir=args.c85_dir,
        smoke_qid=smoke_qid,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(result["summary"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out_dir / "rows.json").write_text(
        json.dumps(result["rows"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    s = result["summary"]
    print("=== C-96 刘翔主尺 ===")
    print(
        f"A0     {s['A0_hits']}/{s['denom']} "
        f"(zero_score_in_pack={s.get('A0_zero_score_segs_total')})"
    )
    for name in ("NoFill", "NoFillPri", "SlotCover", "SlotOnly"):
        a = s[name]
        print(
            f"{name:10s} {a['hits']}/{a['denom']} "
            f"lost={a['lost']} gained={a['gained']} "
            f"Δ={a['delta_vs_a0']:+d}  [{a['status']}]"
        )
    print("fill_ratio_mean", s["fill_ratio_mean"])
    print("verdict", s["verdict"], f"elapsed={s['elapsed_s']}s")
    print("wrote", args.out_dir)


if __name__ == "__main__":
    main()
