#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-88：细召回后按需回溯粗上下文（邻段）＋查询分类路由（只量）。

协议（网上方案里「还值得试」的两刀；扩写主轴不重开）：
  1) 细粒度＝原文 BM25 分表
  2) 对前 M 名细切片，按同信源邻接表回溯 ±R 段（粗上下文）
  3) 邻段继承主段分 × 衰减；再装箱
  4) 路由：按议题类型决定 R（时点/成因 R=2；口径/伤亡 R=1；可关＝R=0）

判据：a＝A0 48/105；b＝臂≥54 且 lost=0。对照 C-85-C＝52。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c88_coarse_backtrack.py \\
      --run-dir /tmp/six2 --out-dir /tmp/c88_backtrack
  # 叠在 C-85 审查分上再回溯
  ... --seed-scores /tmp/c85_auto/llm_scores_c.json --score-input /tmp/c85_auto/score_input.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from scripts.probe_c62_rerank_arms import (  # noqa: E402
    _bm25_table,
    _pack_with_scores,
    _query_of,
)
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c84_llm_rerank import _budget  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD, discover_reports  # noqa: E402

TARGET_A0 = 48
TARGET_DENOM = 105
TARGET_L2 = 54


def _neighbor_index(dossier: Dossier) -> dict[str, list[str]]:
    """source_id → 有序 seg id 列表（案卷内顺序）。"""
    out: dict[str, list[str]] = {}
    for src in dossier.sources:
        out[str(src.id)] = [seg.id for seg in src.segments]
    return out


def _sid_source(sid: str) -> str:
    return sid.split("#", 1)[0] if "#" in sid else sid


def route_radius(question: str) -> tuple[str, int]:
    """查询分类 → 回溯半径。返回 (类型, R)。"""
    q = question or ""
    # 时点争点
    if any(x in q for x in ("时刻", "时分", "起始", "几点", "何时", "10时", "时间准")):
        return "time", 2
    # 成因／机制
    if any(x in q for x in ("成因", "冰川", "溃决", "断裂", "冰岩", "冰湖", "引发", "认定")):
        return "cause", 2
    # 口径／统计／伤亡
    if any(x in q for x in ("口径", "统计", "伤亡", "遇难", "失联", "洪灾", "山崩", "泥石流")):
        # 「泥石流」太泛：仅当与口径/称呼并列
        if any(x in q for x in ("口径", "统计", "称", "联合国", "尼泊尔")):
            return "caliber", 1
        if any(x in q for x in ("伤亡", "遇难", "失联")):
            return "casualty", 1
    # 默认轻回溯
    return "default", 1


def backtrack_boost(
    scores: dict[str, float],
    neighbor_of: dict[str, list[str]],
    *,
    top_m: int,
    radius: int,
    decay: float = 0.85,
) -> dict[str, float]:
    """对前 M 名细切片，给 ±R 邻段补分（不超过主段分）。"""
    if radius <= 0 or top_m <= 0:
        return dict(scores)
    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    seeds = [sid for sid, sc in ranked[:top_m] if sc > 0]
    # sid → 在源内下标
    pos: dict[str, tuple[str, int]] = {}
    for src_id, ids in neighbor_of.items():
        for i, sid in enumerate(ids):
            pos[sid] = (src_id, i)

    out = dict(scores)
    for sid in seeds:
        parent = float(scores.get(sid, 0.0))
        if parent <= 0 or sid not in pos:
            continue
        src_id, i = pos[sid]
        ids = neighbor_of[src_id]
        for d in range(1, radius + 1):
            factor = decay ** d
            for j in (i - d, i + d):
                if j < 0 or j >= len(ids):
                    continue
                nid = ids[j]
                boosted = parent * factor
                if boosted > float(out.get(nid, 0.0)):
                    out[nid] = boosted
    return out


def measure_arm(
    jobs: list[dict],
    gold_dir: Path,
    *,
    score_fn,
    arm_key: str,
) -> dict[str, Any]:
    rows = []
    lost_n = gained_n = 0
    tot = Counter()
    for job in jobs:
        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        budget = int(job["budget"])
        gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
        if denom == 0:
            continue
        scores = score_fn(job, dossier)
        p0 = pack_material(dossier, budget_chars=budget)
        sel_a = {str(x) for x in (p0.get("selected") or [])}
        loc_a = selected_locs(dossier, sel_a)
        hits_a = l2_hits(gold, loc_a)

        sel = _pack_with_scores(dossier, budget, scores)
        loc = selected_locs(dossier, sel)
        hits = l2_hits(gold, loc)
        lost = (gold & loc_a) - loc
        gained = (gold & loc) - loc_a
        lost_n += len(lost)
        gained_n += len(gained)
        rows.append({
            "case": job["case"], "qid": job["qid"], "denom": denom,
            "route": job.get("route"), "radius": job.get("radius"),
            "a0_hits": hits_a, "a0_n": len(sel_a),
            f"{arm_key}_hits": hits, f"{arm_key}_n": len(sel),
            "lost": len(lost), "gained": len(gained),
        })
        tot["denom"] += denom
        tot["a0_hits"] += hits_a
        tot["a0_n"] += len(sel_a)
        tot["arm_hits"] += hits
        tot["arm_n"] += len(sel)
    return {
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "a0": {
            "l2_hits": int(tot["a0_hits"]),
            "n_selected": int(tot["a0_n"]),
            "precision": round(tot["a0_hits"] / tot["a0_n"], 4) if tot["a0_n"] else 0,
            "recall": round(tot["a0_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        arm_key: {
            "l2_hits": int(tot["arm_hits"]),
            "n_selected": int(tot["arm_n"]),
            "precision": round(tot["arm_hits"] / tot["arm_n"], 4) if tot["arm_n"] else 0,
            "recall": round(tot["arm_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        "lost_n": lost_n,
        "gained_n": gained_n,
        "rows": rows,
    }


def judge(summary: dict, arm_key: str) -> dict:
    a_ok = summary["a0"]["l2_hits"] == TARGET_A0 and summary["denom"] == TARGET_DENOM
    arm = summary[arm_key]
    b_ok = (
        arm["l2_hits"] >= TARGET_L2
        and summary["lost_n"] == 0
        and summary["denom"] == TARGET_DENOM
    )
    return {
        "a": {"ok": a_ok, "got": f"{summary['a0']['l2_hits']}/{summary['denom']}"},
        "b": {
            "ok": b_ok,
            "got": f"{arm['l2_hits']}/{summary['denom']}",
            "lost_n": summary["lost_n"],
            "gained_n": summary["gained_n"],
        },
        "improved_vs_a0": arm["l2_hits"] > summary["a0"]["l2_hits"],
        "vs_c85c_52": arm["l2_hits"] - 52,
    }


def build_jobs(run_dir: Path) -> list[dict]:
    jobs = []
    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(rep)
        query = _query_of(dossier)
        route, radius = route_radius(query)
        bm25 = dict(_bm25_table(dossier))
        jobs.append({
            "case": case,
            "qid": qid,
            "query": query,
            "budget": _budget(rep),
            "report": str(rp.resolve()),
            "bm25_scores": bm25,
            "route": route,
            "radius": radius,
        })
    return jobs


def load_seed_scores(
    score_input: Path, scores_path: Path,
) -> dict[str, dict[str, float]]:
    """C-85 产物：key → sid→审查分（可与 BM25 fuse 底表合并）。"""
    jobs = json.loads(score_input.read_text(encoding="utf-8"))
    raw = json.loads(scores_path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, float]] = {}
    for job in jobs:
        key = f"{job['case']}::{job['qid']}"
        sc = raw.get(key)
        if sc is None:
            continue
        if isinstance(sc, dict):
            id_scores = {str(k): float(v) for k, v in sc.items()}
        else:
            id_scores = {cid: float(s) for cid, s in zip(job["ids"], sc)}
        # 与 C-85 相同：审查分主序、BM25 破并列
        bm25 = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        max_b = max(bm25.values()) if bm25 else 1.0
        max_b = max_b if max_b > 0 else 1.0
        fused = {sid: 0.0 for sid in bm25}
        for sid, s in id_scores.items():
            b = float(bm25.get(sid, 0.0)) / max_b
            fused[sid] = float(s) * 1000.0 + b
            bm25.setdefault(sid, 0.0)
        for sid in bm25:
            fused.setdefault(sid, 0.0)
        out[key] = fused
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", default="/tmp/six2")
    ap.add_argument("--out-dir", default="/tmp/c88_backtrack")
    ap.add_argument("--gold-dir", default="")
    ap.add_argument("--top-m", type=int, default=40, help="对前 M 细切片回溯邻段")
    ap.add_argument("--decay", type=float, default=0.85)
    ap.add_argument("--fixed-radius", type=int, default=None,
                    help="若给定则全题同一 R，关掉路由")
    ap.add_argument("--seed-scores", default="",
                    help="可选 C-85 llm_scores_*.json")
    ap.add_argument("--score-input", default="",
                    help="与 seed-scores 配套的 score_input.json")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gold_dir = Path(args.gold_dir) if args.gold_dir else DEFAULT_GOLD

    jobs = build_jobs(Path(args.run_dir))
    if args.fixed_radius is not None:
        for j in jobs:
            j["radius"] = int(args.fixed_radius)
            j["route"] = f"fixed_r{args.fixed_radius}"

    seed = None
    if args.seed_scores:
        if not args.score_input:
            raise SystemExit("--seed-scores 需要同时给 --score-input")
        seed = load_seed_scores(Path(args.score_input), Path(args.seed_scores))
        print(f"叠加种子分 {len(seed)} 题 ← {args.seed_scores}", flush=True)

    # 路由分布
    rc = Counter((j["route"], j["radius"]) for j in jobs)
    print("======== C-88 路由分布 ========", flush=True)
    for (route, r), n in sorted(rc.items(), key=lambda x: -x[1]):
        print(f"  {route} R={r}: {n} 题", flush=True)

    def base_scores(job, dossier):
        key = f"{job['case']}::{job['qid']}"
        if seed and key in seed:
            return dict(seed[key])
        return {str(k): float(v) for k, v in job["bm25_scores"].items()}

    def make_fn(radius_mode: str):
        def fn(job, dossier):
            nb = _neighbor_index(dossier)
            base = base_scores(job, dossier)
            if radius_mode == "r0":
                r = 0
            elif radius_mode == "fixed1":
                r = 1
            elif radius_mode == "fixed2":
                r = 2
            else:  # route
                r = int(job["radius"])
            return backtrack_boost(
                base, nb, top_m=args.top_m, radius=r, decay=args.decay)
        return fn

    arms = [
        ("R0", "r0"),       # 不回溯（种子或纯 BM25）
        ("R1", "fixed1"),
        ("R2", "fixed2"),
        ("ROUTE", "route"),
    ]
    payload = {"protocol": "C-88", "top_m": args.top_m, "decay": args.decay,
               "seed": bool(seed), "route_counts": {
                   f"{a}/{b}": c for (a, b), c in rc.items()
               }}
    print("======== C-88 量尺 ========", flush=True)
    for arm_key, mode in arms:
        summary = measure_arm(jobs, gold_dir, score_fn=make_fn(mode), arm_key=arm_key)
        j = judge(summary, arm_key)
        payload[arm_key] = {"summary": summary, "judge": j}
        print(
            f"{arm_key}: A0={summary['a0']['l2_hits']}/{summary['denom']} "
            f"臂={summary[arm_key]['l2_hits']}/{summary['denom']} "
            f"lost={summary['lost_n']} gained={summary['gained_n']} "
            f"b={'过' if j['b']['ok'] else '逃逸'} "
            f"vsC85C={j['vs_c85c_52']:+d}",
            flush=True,
        )

    # 吉隆子集披露
    jilong = []
    for arm_key, _ in arms:
        rows = payload[arm_key]["summary"]["rows"]
        sub = [r for r in rows if "吉隆" in r["case"]]
        if not sub:
            continue
        hits = sum(r[f"{arm_key}_hits"] for r in sub)
        den = sum(r["denom"] for r in sub)
        a0 = sum(r["a0_hits"] for r in sub)
        jilong.append({"arm": arm_key, "a0": a0, "hits": hits, "denom": den})
    payload["jilong_subset"] = jilong
    if jilong:
        print("吉隆子集:", jilong, flush=True)

    (out_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"落盘 {out_dir / 'summary.json'}", flush=True)

    # 任一路过 b 才 0
    if any(payload[k]["judge"]["b"]["ok"] for k, _ in arms):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
