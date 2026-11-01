#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-91：单窗 lost 修复只量（①②；零模型；接 C-90）。

冻结 /tmp/c85_k180 审查分缓存，对照装箱臂（不调模型）：

  A0      生产 BM25＋密度键
  C_den   C-85 融合分＋密度键（复现 57／lost6）
  C_pri   融合分＋分主序（复现约 59／lost4）
  lock_*  先锁全 A0 再填（预算已满时＝退化成 A0，作反例）
  R_pri   **回补单调**：从 C_pri 出发，把缺失的 A0 段强制装回；
          腾位时优先丢掉「非 A0」里融合分最低的段
  R_den   同上，从 C_den 出发
  boost   A0 段融合分 +B 后再分主序装箱（B∈{1k,3k,5k}）

判据 b（探索）：臂 L2≥54 且相对 A0 lost=0。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c91_mono_pack.py \\
      --c85-dir /tmp/c85_k180 --out-dir /tmp/c91_mono
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.answer_slots import priority_segment_ids  # noqa: E402
from app.core.dup_check import duplicate_map  # noqa: E402
from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from app.core.relevance import classify_sources  # noqa: E402
from app.ingest.segment import SEGMENT_MAX  # noqa: E402
from scripts.probe_c62_rerank_arms import _pack_with_scores  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _fuse, _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

TARGET_L2 = 54
TARGET_A0 = 48
TARGET_DENOM = 105


def _billing_len(text: str) -> int:
    return min(len(text or ""), int(SEGMENT_MAX))


def _eligible_lengths(dossier: Dossier) -> dict[str, int]:
    dups = duplicate_map(dossier)
    relevance = {s["source_id"]: s for s in classify_sources(dossier)}
    lengths: dict[str, int] = {}
    for src in dossier.sources:
        if src.id in dups or (relevance.get(src.id) or {}).get("level") == "zero":
            continue
        for seg in src.segments:
            lengths[seg.id] = _billing_len(seg.text)
    if not lengths:
        for src in dossier.sources:
            if src.id in dups:
                continue
            for seg in src.segments:
                lengths[seg.id] = _billing_len(seg.text)
    return lengths


def _pack_fill(
    dossier: Dossier,
    budget: int,
    scores: dict[str, float],
    *,
    lock: set[str],
    order: str,
) -> set[str]:
    """先尽力装 lock（A0 保底），再按 order=primary|density 填剩余。"""
    budget = max(1, int(budget))
    lengths = _eligible_lengths(dossier)
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

    # 议题槽仍优先（与生产同形），但不打断 lock 保底意图：
    # 先 lock，再 priority 里未锁的，再填分。
    for seg_id in sorted(lock):
        _take(seg_id)
    for seg_id in priority_segment_ids(dossier):
        _take(seg_id)

    scored = [g for g in lengths if scores.get(g, 0.0) > 0 and g not in selected]

    def _key(g: str) -> tuple:
        sc = float(scores.get(g, 0.0))
        if order == "density":
            dens = sc / math.log2(max(lengths[g], 2))
            return (-dens, g)
        return (-sc, g)

    for seg_id in sorted(scored, key=_key):
        if used >= budget:
            break
        _take(seg_id)

    # 零分轮转保底（与 pack_material 同意图，简化跨源）
    by_source: dict[str, list[str]] = {}
    for src in dossier.sources:
        for seg in src.segments:
            if seg.id in lengths and seg.id not in selected:
                by_source.setdefault(src.id, []).append(seg.id)
    for sid in by_source:
        by_source[sid].sort(key=lambda g: (-scores.get(g, 0.0), g))
    source_order = sorted(
        by_source,
        key=lambda s: -max((scores.get(g, 0.0) for g in by_source[s]), default=0.0),
    )
    while used < budget:
        progressed = False
        for src_id in source_order:
            queue = by_source[src_id]
            for i, seg_id in enumerate(queue):
                if used + lengths[seg_id] <= budget:
                    queue.pop(i)
                    selected.add(seg_id)
                    used += lengths[seg_id]
                    progressed = True
                    break
        if not progressed:
            break
    return selected


def _pack_score_primary(
    dossier: Dossier, budget: int, scores: dict[str, float],
) -> set[str]:
    return _pack_fill(dossier, budget, scores, lock=set(), order="primary")


def _mono_repair(
    dossier: Dossier,
    budget: int,
    scores: dict[str, float],
    *,
    base: set[str],
    must: set[str],
) -> set[str]:
    """从 base 装箱出发，强制装回 must（通常＝A0）；腾位踢非 must 里分最低者。"""
    lengths = _eligible_lengths(dossier)
    budget = max(1, int(budget))
    sel = set(base) & set(lengths)
    # 先丢掉不在 eligible 的
    used = sum(lengths[s] for s in sel)

    def _drop_victim() -> bool:
        nonlocal used
        victims = sorted(
            (s for s in sel if s not in must),
            key=lambda s: (float(scores.get(s, 0.0)), s),
        )
        if not victims:
            return False
        v = victims[0]
        sel.remove(v)
        used -= lengths[v]
        return True

    for sid in sorted(must):
        if sid in sel or sid not in lengths:
            continue
        need = lengths[sid]
        while used + need > budget:
            if not _drop_victim():
                break
        if used + need <= budget:
            sel.add(sid)
            used += need
    return sel


def analyze(c85_dir: Path, gold_dir: Path) -> dict[str, Any]:
    jobs = json.loads((c85_dir / "score_input.json").read_text(encoding="utf-8"))
    scores_c = json.loads((c85_dir / "llm_scores_c.json").read_text(encoding="utf-8"))

    boosts = (1000.0, 3000.0, 5000.0)
    arms = [
        "a0", "c_den", "c_pri",
        "lock_pri", "lock_den",
        "r_pri", "r_den",
        *[f"boost_{int(b)}" for b in boosts],
    ]
    tot = {a: Counter() for a in arms}
    rows = []
    repair_miss = []

    for job in jobs:
        key = f"{job['case']}::{job['qid']}"
        sc = scores_c.get(key)
        if sc is None:
            raise SystemExit(f"缺分 {key}")
        if isinstance(sc, dict):
            id_scores = {str(k): float(v) for k, v in sc.items()}
        else:
            id_scores = {cid: float(s) for cid, s in zip(job["ids"], sc)}

        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        budget = int(job["budget"])
        gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
        if denom == 0:
            continue

        bm25 = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        for sid in id_scores:
            bm25.setdefault(sid, 0.0)
        fused = _fuse(bm25, id_scores, use_bm25=True)

        p0 = pack_material(dossier, budget_chars=budget)
        sel_a0 = {str(x) for x in (p0.get("selected") or [])}
        sel_den = _pack_with_scores(dossier, budget, fused)
        sel_pri = _pack_score_primary(dossier, budget, fused)
        sel_lock_p = _pack_fill(dossier, budget, fused, lock=sel_a0, order="primary")
        sel_lock_d = _pack_fill(dossier, budget, fused, lock=sel_a0, order="density")
        sel_rp = _mono_repair(
            dossier, budget, fused, base=sel_pri, must=sel_a0)
        sel_rd = _mono_repair(
            dossier, budget, fused, base=sel_den, must=sel_a0)

        for sid in sel_a0 - sel_rp:
            repair_miss.append({
                "arm": "r_pri", "case": job["case"], "qid": job["qid"], "sid": sid,
            })

        packs: dict[str, set[str]] = {
            "a0": sel_a0,
            "c_den": sel_den,
            "c_pri": sel_pri,
            "lock_pri": sel_lock_p,
            "lock_den": sel_lock_d,
            "r_pri": sel_rp,
            "r_den": sel_rd,
        }
        for b in boosts:
            boosted = dict(fused)
            for sid in sel_a0:
                boosted[sid] = float(boosted.get(sid, 0.0)) + float(b)
            packs[f"boost_{int(b)}"] = _pack_score_primary(
                dossier, budget, boosted)

        row: dict[str, Any] = {
            "case": job["case"], "qid": job["qid"], "denom": denom, "budget": budget,
        }
        loc_a0 = selected_locs(dossier, sel_a0)
        for name, sel in packs.items():
            loc = selected_locs(dossier, sel)
            hits = l2_hits(gold, loc)
            lost = len((gold & loc_a0) - loc)
            gained = len((gold & loc) - loc_a0)
            row[f"{name}_hits"] = hits
            row[f"{name}_n"] = len(sel)
            row[f"{name}_lost"] = lost
            row[f"{name}_gained"] = gained
            row[f"{name}_a0_cover"] = len(sel_a0 & sel)
            tot[name]["hits"] += hits
            tot[name]["lost"] += lost
            tot[name]["gained"] += gained
            tot[name]["n_seg"] += len(sel)
            tot[name]["a0_cover"] += len(sel_a0 & sel)
            tot[name]["a0_n"] += len(sel_a0)
        tot["a0"]["denom"] += denom
        rows.append(row)

    denom = int(tot["a0"]["denom"])
    a0_hits = int(tot["a0"]["hits"])
    summary_arms = {}
    for name in arms:
        h = int(tot[name]["hits"])
        lo = int(tot[name]["lost"])
        g = int(tot[name]["gained"])
        summary_arms[name] = {
            "l2_hits": h,
            "lost_n": lo,
            "gained_n": g,
            "vs_a0_delta": h - a0_hits,
            "gate_b": h >= TARGET_L2 and lo == 0,
            "mean_n_seg": round(tot[name]["n_seg"] / max(len(rows), 1), 1),
            "a0_cover_rate": round(
                tot[name]["a0_cover"] / max(tot[name]["a0_n"], 1), 4),
        }

    return {
        "n_questions": len(rows),
        "denom": denom,
        "expect_reproduce": {
            "a0": TARGET_A0,
            "c_den": 57,
            "c_den_lost": 6,
            "ok": (
                a0_hits == TARGET_A0
                and int(tot["c_den"]["hits"]) == 57
                and int(tot["c_den"]["lost"]) == 6
                and denom == TARGET_DENOM
            ),
        },
        "arms": summary_arms,
        "repair_miss_n": len(repair_miss),
        "repair_miss_sample": repair_miss[:12],
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--c85-dir", default="/tmp/c85_k180")
    ap.add_argument("--out-dir", default="/tmp/c91_mono")
    ap.add_argument("--gold-dir", default="")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gold_dir = Path(args.gold_dir) if args.gold_dir else DEFAULT_GOLD

    print("======== C-91 单调／回补／加分只量（零模型）========", flush=True)
    summary = analyze(Path(args.c85_dir), gold_dir)
    rep = summary["expect_reproduce"]
    print(
        f"复现: A0={summary['arms']['a0']['l2_hits']} "
        f"C_den={summary['arms']['c_den']['l2_hits']} "
        f"lost={summary['arms']['c_den']['lost_n']} "
        f"{'OK' if rep['ok'] else 'FAIL'}",
        flush=True,
    )
    labels = {
        "a0": "A0 生产",
        "c_den": "C 密度",
        "c_pri": "C 分主序",
        "lock_pri": "先锁A0再填·分主序",
        "lock_den": "先锁A0再填·密度",
        "r_pri": "回补单调←分主序",
        "r_den": "回补单调←密度",
        "boost_1000": "A0加分+1k·分主序",
        "boost_3000": "A0加分+3k·分主序",
        "boost_5000": "A0加分+5k·分主序",
    }
    for k, lab in labels.items():
        a = summary["arms"][k]
        gate = "过" if a["gate_b"] else "逃逸"
        print(
            f"  {lab}: L2={a['l2_hits']}/{summary['denom']} "
            f"lost={a['lost_n']} gained={a['gained_n']} "
            f"ΔA0={a['vs_a0_delta']:+d} "
            f"A0覆盖={a['a0_cover_rate']:.1%} 门槛b={gate}",
            flush=True,
        )
    if summary["repair_miss_n"]:
        print(f"⚠ 回补未装回 A0 段 {summary['repair_miss_n']} 次", flush=True)

    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"落盘 {out / 'summary.json'}", flush=True)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
