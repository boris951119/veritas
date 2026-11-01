#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-90：C-85 K180「+15/−6」损失定位（零模型；Qoder 第一阶段）。

冻结 /tmp/c85_k180 缓存：
  1) 复现 A0=48、C=57、lost=6、gained=15
  2) 逐金标分层：未进候选／审查分低／密度装箱挤出／预算两侧都挤出
  3) 单变量对照：现行「分／log2(len)」装箱 vs 「分主序、长度只卡预算」

判据（探索门槛）：臂≥54 且相对 A0 lost=0；另报相对现行 C 臂损失。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c90_loss_locate.py \\
      --c85-dir /tmp/c85_k180 --out-dir /tmp/c90_loss
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

TARGET_A0 = 48
TARGET_DENOM = 105
TARGET_L2 = 54


def _billing_len(text: str) -> int:
    return min(len(text or ""), int(SEGMENT_MAX))


def _pack_score_primary(
    dossier: Dossier,
    budget: int,
    scores: dict[str, float],
) -> set[str]:
    """与 pack_material 同形，但第②段按原始分排序（不除 log2 长度）。"""
    budget = max(1, int(budget))
    dups = duplicate_map(dossier)
    relevance = {s["source_id"]: s for s in classify_sources(dossier)}
    lengths: dict[str, int] = {}
    eligible: list[tuple[str, str]] = []
    for src in dossier.sources:
        if src.id in dups or (relevance.get(src.id) or {}).get("level") == "zero":
            continue
        for seg in src.segments:
            eligible.append((src.id, seg.id))
            lengths[seg.id] = _billing_len(seg.text)
    if not eligible:
        for src in dossier.sources:
            if src.id in dups:
                continue
            for seg in src.segments:
                eligible.append((src.id, seg.id))
                lengths[seg.id] = _billing_len(seg.text)

    by_source: dict[str, list[str]] = {}
    for src_id, seg_id in eligible:
        by_source.setdefault(src_id, []).append(seg_id)
    for src_id in by_source:
        by_source[src_id].sort(key=lambda g: (-scores.get(g, 0.0), g))
    source_order = sorted(
        by_source,
        key=lambda s: -max((scores.get(g, 0.0) for g in by_source[s]), default=0.0),
    )

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
        for queue in by_source.values():
            if seg_id in queue:
                queue.remove(seg_id)
                break
        return True

    for seg_id in priority_segment_ids(dossier):
        _take(seg_id)

    scored = [g for g in lengths if scores.get(g, 0.0) > 0 and g not in selected]
    for seg_id in sorted(scored, key=lambda g: (-scores.get(g, 0.0), g)):
        if used >= budget:
            break
        _take(seg_id)

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


def _loc_to_sids(dossier: Dossier, gold: set[tuple[str, str]]) -> set[str]:
    out = set()
    for src in dossier.sources:
        for seg in src.segments:
            if selected_locs(dossier, {seg.id}) & gold:
                out.add(seg.id)
    return out


def _review_score(id_scores: dict[str, float], sid: str) -> float | None:
    if sid not in id_scores:
        return None
    # fused = review*1000 + bm25_norm；反推审查分粗值
    return float(id_scores[sid])


def analyze(c85_dir: Path, gold_dir: Path) -> dict[str, Any]:
    jobs = json.loads((c85_dir / "score_input.json").read_text(encoding="utf-8"))
    scores_c = json.loads((c85_dir / "llm_scores_c.json").read_text(encoding="utf-8"))
    meta = {}
    if (c85_dir / "prepare_meta.json").is_file():
        meta = json.loads((c85_dir / "prepare_meta.json").read_text(encoding="utf-8"))

    layer_lost = Counter()
    layer_gained = Counter()
    lost_details: list[dict] = []
    gained_details: list[dict] = []
    rows = []
    tot = Counter()

    for job in jobs:
        key = f"{job['case']}::{job['qid']}"
        sc = scores_c.get(key)
        if sc is None:
            raise SystemExit(f"缺分 {key}")
        if isinstance(sc, dict):
            id_scores_raw = {str(k): float(v) for k, v in sc.items()}
        else:
            id_scores_raw = {cid: float(s) for cid, s in zip(job["ids"], sc)}

        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        text_of = {
            seg.id: (seg.text or "")
            for src in dossier.sources for seg in src.segments
        }
        budget = int(job["budget"])
        gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
        if denom == 0:
            continue
        gold_sids = _loc_to_sids(dossier, gold)
        cand = set(job["ids"])

        bm25 = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        for sid in id_scores_raw:
            bm25.setdefault(sid, 0.0)
        fused = _fuse(bm25, id_scores_raw, use_bm25=True)

        # A0
        p0 = pack_material(dossier, budget_chars=budget)
        sel_a = {str(x) for x in (p0.get("selected") or [])}
        loc_a = selected_locs(dossier, sel_a)
        hits_a = l2_hits(gold, loc_a)

        # C density（现行探针路径）
        sel_den = _pack_with_scores(dossier, budget, fused)
        loc_den = selected_locs(dossier, sel_den)
        hits_den = l2_hits(gold, loc_den)

        # score-primary 对照
        sel_pri = _pack_score_primary(dossier, budget, fused)
        loc_pri = selected_locs(dossier, sel_pri)
        hits_pri = l2_hits(gold, loc_pri)

        lost = (gold & loc_a) - loc_den
        gained = (gold & loc_den) - loc_a
        lost_n = len(lost)
        gained_n = len(gained)

        # 分层：对每个 lost／gained 金标键找 sid
        def sids_for(locs: set[tuple[str, str]]) -> set[str]:
            return {s for s in gold_sids if selected_locs(dossier, {s}) & locs}

        for sid in sids_for(lost):
            in_cand = sid in cand
            rev = id_scores_raw.get(sid)
            in_den = sid in sel_den
            in_pri = sid in sel_pri
            fused_sc = fused.get(sid, 0.0)
            # 审查分（未 fuse）：raw
            # 分层优先级：候选 → 密度挤出 → 审查分/融合分 → 双侧预算
            if not in_cand:
                layer = "L1_not_in_candidate"
            elif in_pri and not in_den:
                layer = "L3_squeezed_by_density"
            elif rev is not None and float(rev) < 6.0:
                layer = "L2_review_low"
            elif fused_sc <= 0:
                layer = "L2b_fused_zero"
            elif (not in_pri) and (not in_den):
                layer = "L4_budget_both"
            else:
                layer = "L5_other"
            layer_lost[layer] += 1
            lost_details.append({
                "case": job["case"], "qid": job["qid"], "sid": sid,
                "layer": layer,
                "review_raw": rev,
                "fused": round(fused_sc, 4),
                "len": _billing_len(text_of.get(sid, "")),
                "density_key": round(
                    fused_sc / math.log2(max(_billing_len(text_of.get(sid, "")), 2)), 6)
                if fused_sc else 0,
                "in_cand": in_cand,
                "in_density_pack": in_den,
                "in_score_primary_pack": in_pri,
                "text_head": (text_of.get(sid, "") or "")[:80].replace("\n", " "),
            })

        for sid in sids_for(gained):
            in_cand = sid in cand
            rev = id_scores_raw.get(sid)
            in_pri = sid in sel_pri
            if not in_cand:
                gl = "G_not_in_cand_weird"
            elif rev is not None and float(rev) >= 6:
                gl = "G_high_review"
            else:
                gl = "G_other"
            if in_pri:
                gl += "+also_pri"
            else:
                gl += "+not_pri"
            layer_gained[gl] += 1
            gained_details.append({
                "case": job["case"], "qid": job["qid"], "sid": sid,
                "layer": gl,
                "review_raw": rev,
                "fused": round(fused.get(sid, 0.0), 4),
                "len": _billing_len(text_of.get(sid, "")),
            })

        # 相对 A0：pri 臂 lost/gained
        lost_pri = (gold & loc_a) - loc_pri
        gained_pri = (gold & loc_pri) - loc_a

        rows.append({
            "case": job["case"], "qid": job["qid"], "denom": denom,
            "budget": budget,
            "a0_hits": hits_a, "a0_n": len(sel_a),
            "C_density_hits": hits_den, "C_density_n": len(sel_den),
            "C_primary_hits": hits_pri, "C_primary_n": len(sel_pri),
            "lost_density": lost_n, "gained_density": gained_n,
            "lost_primary": len(lost_pri), "gained_primary": len(gained_pri),
            "n_cand": len(cand),
            "n_overlap_packs": len(sel_den & sel_pri),
            "only_density": len(sel_den - sel_pri),
            "only_primary": len(sel_pri - sel_den),
        })
        tot["denom"] += denom
        tot["a0"] += hits_a
        tot["den"] += hits_den
        tot["pri"] += hits_pri
        tot["lost_den"] += lost_n
        tot["gained_den"] += gained_n
        tot["lost_pri"] += len(lost_pri)
        tot["gained_pri"] += len(gained_pri)

    summary = {
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "reproduce": {
            "a0": int(tot["a0"]),
            "C_density": int(tot["den"]),
            "lost_density": int(tot["lost_den"]),
            "gained_density": int(tot["gained_den"]),
            "expect_a0": TARGET_A0,
            "expect_C": 57,
            "expect_lost": 6,
            "expect_gained": 15,
            "ok": (
                int(tot["a0"]) == TARGET_A0
                and int(tot["den"]) == 57
                and int(tot["lost_den"]) == 6
                and int(tot["gained_den"]) == 15
                and int(tot["denom"]) == TARGET_DENOM
            ),
        },
        "score_primary": {
            "l2_hits": int(tot["pri"]),
            "lost_n": int(tot["lost_pri"]),
            "gained_n": int(tot["gained_pri"]),
            "vs_a0_delta": int(tot["pri"]) - int(tot["a0"]),
            "vs_density_delta": int(tot["pri"]) - int(tot["den"]),
            "gate_b": (
                int(tot["pri"]) >= TARGET_L2 and int(tot["lost_pri"]) == 0
            ),
        },
        "lost_layers": dict(layer_lost),
        "gained_layers": dict(layer_gained),
        "prepare_meta": meta,
        "rows": rows,
        "lost_details": lost_details,
        "gained_details": gained_details,
    }
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--c85-dir", default="/tmp/c85_k180")
    ap.add_argument("--out-dir", default="/tmp/c90_loss")
    ap.add_argument("--gold-dir", default="")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gold_dir = Path(args.gold_dir) if args.gold_dir else DEFAULT_GOLD

    print("======== C-90 损失定位（零模型）========", flush=True)
    summary = analyze(Path(args.c85_dir), gold_dir)
    rep = summary["reproduce"]
    print(
        f"复现: A0={rep['a0']}/{summary['denom']} "
        f"C密度={rep['C_density']} lost={rep['lost_density']} "
        f"gained={rep['gained_density']} "
        f"{'OK' if rep['ok'] else 'FAIL 与缓存摘要不一致'}",
        flush=True,
    )
    pri = summary["score_primary"]
    print(
        f"对照·分主序: L2={pri['l2_hits']}/{summary['denom']} "
        f"lost={pri['lost_n']} gained={pri['gained_n']} "
        f"ΔA0={pri['vs_a0_delta']:+d} Δ密度={pri['vs_density_delta']:+d} "
        f"门槛b={'过' if pri['gate_b'] else '逃逸'}",
        flush=True,
    )
    print("lost 分层:", json.dumps(summary["lost_layers"], ensure_ascii=False), flush=True)
    print("gained 分层:", json.dumps(summary["gained_layers"], ensure_ascii=False), flush=True)
    print("lost 明细:", flush=True)
    for d in summary["lost_details"]:
        print(
            f"  {d['qid']} {d['sid']}: {d['layer']} "
            f"rev={d['review_raw']} fused={d['fused']} len={d['len']} "
            f"denKey={d['density_key']} "
            f"pri={d['in_score_primary_pack']} den={d['in_density_pack']}",
            flush=True,
        )

    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"落盘 {out / 'summary.json'}", flush=True)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
