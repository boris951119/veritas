#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-98：C-85「模型审阅打分」合入评估（刘翔主尺；零新模型调用）。

Boyu：字面抠字支撑已否；改认真评估锚审融合分能否合入。
本票**不调 LLM**——复用 `/tmp/c85_k180` 冻结分；案卷＝`load_official_case`
（与 C-96/97 同尺；⚠ 勿与 C-95 的 six2-report A0=8 混比）。

臂（同一融合分表）：
  A0            现产 pack_material
  C85_den       融合分 → 密度键装箱（C-85 原形）
  C85_pri       融合分 → 分主序
  C85_pri_nf    融合分 → 分主序 + 关灌满
  C85_mono      从 C85_pri 强制装回**全部** A0 段（合法保底；常把 gained 挤掉）
  C85_boost     A0 段融合分 +B 后再分主序（B 网格扫；合法，同 C-95）
  C85_gold_mono （诊断／禁合入）只锁 A0∩金标段——**偷看金标**，只证明上限

门槛（刘翔）：
  IMPROVE＝lost=0 ∧ L2≥A0 ∧ gained>0
  C85_gold_mono 不计合入；C85_boost 过线须 leave-one 未塌
旁证：六案 summary_c 只并排。成本：score_meta_* 冻结账。

go_nogo：GO_CANDIDATE｜NO_GO｜NEED_PAIR_RUN（GO≠已合入）

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c98_c85_merge_eval.py \\
      --out-dir /tmp/c98_c85
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

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from scripts.probe_c62_rerank_arms import _pack_with_scores  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _fuse, _gold_keys  # noqa: E402
from scripts.probe_c91_mono_pack import (  # noqa: E402
    _mono_repair,
    _pack_score_primary,
)
from scripts.probe_c97_support_rank import _pack_pri_nofill  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

CASE_SUB = "刘翔"
DEFAULT_C85 = Path("/tmp/c85_k180")
B_GRID = list(range(0, 10001, 250))


def _id_scores(sc: Any, job: dict) -> dict[str, float]:
    if isinstance(sc, dict):
        return {str(k): float(v) for k, v in sc.items()}
    return {cid: float(s) for cid, s in zip(job["ids"], sc)}


def _load_lx_jobs(c85_dir: Path) -> list[dict]:
    jobs = json.loads((c85_dir / "score_input.json").read_text(encoding="utf-8"))
    out = [j for j in jobs if CASE_SUB in j["case"]]
    if len(out) != 3:
        raise SystemExit(f"期望刘翔 3 问，实得 {len(out)}")
    return sorted(out, key=lambda j: j["qid"])


def _status(hits: int, lost: int, gained: int, a0: int) -> str:
    if lost == 0 and hits >= a0 and gained > 0:
        return "IMPROVE"
    if lost == 0 and hits >= a0:
        return "FLAT"
    return "ESCAPE"


def _cost_block(c85_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"source": str(c85_dir), "phases": {}}
    total_s = 0.0
    total_calls = 0
    for name in ("anchors_meta.json", "score_meta_b.json", "score_meta_c.json"):
        p = c85_dir / name
        if not p.is_file():
            continue
        meta = json.loads(p.read_text(encoding="utf-8"))
        out["phases"][name] = meta
        total_s += float(meta.get("elapsed_s") or 0)
        total_calls += int(meta.get("n_calls") or 0)
    prep = c85_dir / "prepare_meta.json"
    if prep.is_file():
        out["prepare"] = json.loads(prep.read_text(encoding="utf-8"))
    out["total_elapsed_s_scored"] = round(total_s, 1)
    out["total_llm_calls"] = total_calls
    out["note"] = (
        "墙钟／调用＝当时六案 18 题打分冻结账；"
        "刘翔 3 题约占 1/6，粗估 wall≈total/6（非精确）"
    )
    out["liuxiang_wall_s_rough"] = round(total_s / 6.0, 1) if total_s else None
    return out


def _six_side(c85_dir: Path) -> dict[str, Any] | None:
    p = c85_dir / "summary_c.json"
    if not p.is_file():
        return None
    s = json.loads(p.read_text(encoding="utf-8")).get("summary") or {}
    return {
        "note": "六案旁证，非主尺；lost≠0⇒六案尺未过 C-85 原门槛 b",
        "denom": s.get("denom"),
        "a0_l2": (s.get("a0") or {}).get("l2_hits"),
        "C_l2": (s.get("C") or {}).get("l2_hits"),
        "lost_n": s.get("lost_n"),
        "gained_n": s.get("gained_n"),
    }


def run_all(
    *,
    gold_dir: Path,
    cases_root: Path,
    c85_dir: Path,
    smoke_qid: str | None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    jobs = _load_lx_jobs(c85_dir)
    scores_c = json.loads((c85_dir / "llm_scores_c.json").read_text(encoding="utf-8"))
    if smoke_qid:
        jobs = [j for j in jobs if j["qid"] == smoke_qid]
        if not jobs:
            raise SystemExit(f"smoke 无此问 {smoke_qid}")

    rows: list[dict[str, Any]] = []
    tot: Counter = Counter()
    # 可合入候选臂（不含 gold_mono）
    arm_names = [
        "C85_den", "C85_pri", "C85_pri_nf", "C85_mono", "C85_boost",
    ]

    preps: list[dict[str, Any]] = []
    for job in jobs:
        case, qid, query = job["case"], job["qid"], job["query"]
        budget = int(job["budget"])
        dossier = load_official_case(cases_root / case)
        dossier.question = query
        gold, denom = _gold_keys(gold_dir, case, qid)

        key = f"{case}::{qid}"
        id_sc = _id_scores(scores_c[key], job)
        bm25 = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        for sid in id_sc:
            bm25.setdefault(sid, 0.0)
        fused = _fuse(bm25, id_sc, use_bm25=True)

        p0 = pack_material(dossier, budget_chars=budget)
        sel_a0 = {str(x) for x in (p0.get("selected") or [])}
        loc_a0 = selected_locs(dossier, sel_a0)
        a0_hits = l2_hits(gold, loc_a0)

        must_gold = set()
        for sid in sel_a0:
            if selected_locs(dossier, {sid}) & gold:
                must_gold.add(sid)

        prep = {
            "job": job, "dossier": dossier, "budget": budget,
            "gold": gold, "denom": denom, "fused": fused,
            "sel_a0": sel_a0, "loc_a0": loc_a0, "a0_hits": a0_hits,
            "must_gold": must_gold,
        }
        preps.append(prep)

        sel_den = _pack_with_scores(dossier, budget, fused)
        sel_pri = _pack_score_primary(dossier, budget, fused)
        sel_nf = _pack_pri_nofill(dossier, budget, fused)
        sel_mono = _mono_repair(
            dossier, budget, fused, base=sel_pri, must=sel_a0,
        )
        sel_gmono = _mono_repair(
            dossier, budget, fused, base=sel_pri, must=must_gold,
        )

        row: dict[str, Any] = {
            "case": case, "qid": qid, "denom": denom, "budget": budget,
            "query": query,
            "A0": {"hits": a0_hits, "n": len(sel_a0)},
            "n_a0_gold_segs": len(must_gold),
        }
        for name, sel in (
            ("C85_den", sel_den),
            ("C85_pri", sel_pri),
            ("C85_pri_nf", sel_nf),
            ("C85_mono", sel_mono),
            ("C85_gold_mono", sel_gmono),
        ):
            loc = selected_locs(dossier, sel)
            hits = l2_hits(gold, loc)
            lost = len((gold & loc_a0) - loc)
            gained = len((gold & loc) - loc_a0)
            row[name] = {
                "hits": hits, "lost": lost, "gained": gained,
                "n": len(sel),
                "status": _status(hits, lost, gained, a0_hits),
            }
            if name != "C85_gold_mono":
                tot[f"{name}_hits"] += hits
                tot[f"{name}_lost"] += lost
                tot[f"{name}_gained"] += gained
            else:
                tot["oracle_hits"] += hits
                tot["oracle_lost"] += lost
                tot["oracle_gained"] += gained
        rows.append(row)
        tot["denom"] += denom
        tot["a0"] += a0_hits

    def _eval_boost(preps_sub: list[dict], B: float) -> dict[str, int]:
        t: Counter = Counter()
        for p in preps_sub:
            boosted = dict(p["fused"])
            for sid in p["sel_a0"]:
                boosted[sid] = float(boosted.get(sid, 0.0)) + float(B)
            sel = _pack_score_primary(p["dossier"], p["budget"], boosted)
            loc = selected_locs(p["dossier"], sel)
            hits = l2_hits(p["gold"], loc)
            lost = len((p["gold"] & p["loc_a0"]) - loc)
            gained = len((p["gold"] & loc) - p["loc_a0"])
            t["hits"] += hits
            t["lost"] += lost
            t["gained"] += gained
            t["a0"] += p["a0_hits"]
            t["denom"] += p["denom"]
        return dict(t)

    def _pick_B(train: list[dict]) -> tuple[float, dict]:
        best = None
        for B in B_GRID:
            tot_b = _eval_boost(train, float(B))
            key = (
                0 if tot_b["lost"] == 0 else 1,
                tot_b["lost"],
                -tot_b["hits"],
                -tot_b["gained"],
                B,
            )
            cand = (key, float(B), tot_b)
            if best is None or cand[0] < best[0]:
                best = cand
        assert best is not None
        return best[1], best[2]

    B_star, boost_full = _pick_B(preps)
    # 逐问明细用 B*
    for p, row in zip(preps, rows):
        boosted = dict(p["fused"])
        for sid in p["sel_a0"]:
            boosted[sid] = float(boosted.get(sid, 0.0)) + float(B_star)
        sel = _pack_score_primary(p["dossier"], p["budget"], boosted)
        loc = selected_locs(p["dossier"], sel)
        hits = l2_hits(p["gold"], loc)
        lost = len((p["gold"] & p["loc_a0"]) - loc)
        gained = len((p["gold"] & loc) - p["loc_a0"])
        row["C85_boost"] = {
            "hits": hits, "lost": lost, "gained": gained,
            "n": len(sel), "B": B_star,
            "status": _status(hits, lost, gained, p["a0_hits"]),
        }
        tot["C85_boost_hits"] += hits
        tot["C85_boost_lost"] += lost
        tot["C85_boost_gained"] += gained

    # leave-one on boost
    loo = []
    if len(preps) >= 2 and not smoke_qid:
        for hold in preps:
            train = [p for p in preps if p["job"]["qid"] != hold["job"]["qid"]]
            B_tr, _ = _pick_B(train)
            tot_h = _eval_boost([hold], B_tr)
            loo.append({
                "hold_qid": hold["job"]["qid"],
                "B_from_train": B_tr,
                "hold_a0": hold["a0_hits"],
                "hits": tot_h["hits"],
                "lost": tot_h["lost"],
                "gained": tot_h["gained"],
                "pass": tot_h["lost"] == 0 and tot_h["hits"] >= hold["a0_hits"],
                "collapsed": not (
                    tot_h["lost"] == 0 and tot_h["hits"] >= hold["a0_hits"]
                ),
            })

    def _sum(name: str) -> dict[str, Any]:
        hits = int(tot[f"{name}_hits"])
        lost = int(tot[f"{name}_lost"])
        gained = int(tot[f"{name}_gained"])
        a0 = int(tot["a0"])
        st = _status(hits, lost, gained, a0)
        out = {
            "hits": hits, "lost": lost, "gained": gained,
            "denom": int(tot["denom"]), "a0": a0,
            "delta_vs_a0": hits - a0,
            "status": st,
            "improve_pass": st == "IMPROVE",
        }
        if name == "C85_boost":
            out["B_star"] = B_star
            out["boost_full_at_pick"] = boost_full
        return out

    arms = {n: _sum(n) for n in arm_names}
    oracle = {
        "hits": int(tot["oracle_hits"]),
        "lost": int(tot["oracle_lost"]),
        "gained": int(tot["oracle_gained"]),
        "denom": int(tot["denom"]),
        "a0": int(tot["a0"]),
        "delta_vs_a0": int(tot["oracle_hits"]) - int(tot["a0"]),
        "status": _status(
            int(tot["oracle_hits"]), int(tot["oracle_lost"]),
            int(tot["oracle_gained"]), int(tot["a0"]),
        ),
        "forbidden_in_production": True,
        "note": "锁 A0∩金标＝偷看金标；只证明审查分信息上限",
    }

    per_q_escape = []
    for r in rows:
        for n in arm_names:
            if r[n]["status"] == "ESCAPE":
                per_q_escape.append({"qid": r["qid"], "arm": n, **{
                    k: r[n][k] for k in ("hits", "lost", "gained", "status")
                }})

    improve_arms = [n for n, a in arms.items() if a["improve_pass"]]
    loo_collapse = sum(1 for x in loo if x.get("collapsed"))
    if "C85_boost" in improve_arms and loo and loo_collapse == 0:
        go = "GO_CANDIDATE"
        reason = (
            f"C85_boost B*={B_star} 刘翔 IMPROVE 且 leave-one 未塌；"
            "仍默认关，须配对真跑 + 用户拍默认"
        )
        preferred = "C85_boost"
    elif "C85_boost" in improve_arms and loo_collapse:
        go = "NEED_PAIR_RUN"
        reason = f"C85_boost 全量 IMPROVE 但 leave-one 塌 {loo_collapse} 次"
        preferred = "C85_boost"
    elif improve_arms:
        go = "GO_CANDIDATE"
        preferred = improve_arms[0]
        reason = f"{preferred} 刘翔 IMPROVE；须配对真跑；默认关"
    elif oracle["status"] == "IMPROVE":
        go = "NO_GO"
        preferred = None
        reason = (
            "合法臂无 IMPROVE；oracle gold_mono 能 IMPROVE⇒"
            "审查分有信息，但缺「不看金标的保真闸」；"
            "不宜为审阅税合入现形"
        )
    elif any(a["status"] == "FLAT" for a in arms.values()):
        go = "NO_GO"
        preferred = None
        reason = "合法臂最多 FLAT；不值得为审阅税合入"
    else:
        go = "NO_GO"
        preferred = None
        reason = "刘翔尺合法臂全 ESCAPE"

    recommendation = {
        "preferred_arm_if_any": preferred,
        "go_nogo": go,
        "reason": reason,
        "oracle_ceiling": oracle,
        "production_default": "仍关；GO_CANDIDATE≠已合入",
        "next_if_go": (
            "配对真跑六案×开关开／关各一；记墙钟与 L2／2.3；用户拍默认值"
        ),
    }

    summary = {
        "ticket": "C-98",
        "ruler": "刘翔",
        "dossier_source": "load_official_case",
        "score_source": str(c85_dir / "llm_scores_c.json"),
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "A0_hits": int(tot["a0"]),
        "arms": arms,
        "oracle_C85_gold_mono": oracle,
        "leave_one_boost": loo,
        "per_question_escape": per_q_escape,
        "six_case_side": _six_side(c85_dir),
        "cost_frozen": _cost_block(c85_dir),
        "recommendation": recommendation,
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "note": (
            "零新模型调用；主尺刘翔；六案只旁证；"
            "字面支撑（C-97）已排除；本票只评审阅融合分装箱形态"
        ),
    }
    return {"summary": summary, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="C-98 C-85 merge eval (LiuXiang)")
    ap.add_argument("--out-dir", type=Path, default=Path("/tmp/c98_c85"))
    ap.add_argument("--gold-dir", type=Path, default=None)
    ap.add_argument("--cases-root", type=Path, default=None)
    ap.add_argument("--c85-dir", type=Path, default=DEFAULT_C85)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--smoke-qid", default=None)
    args = ap.parse_args()
    gold = args.gold_dir or DEFAULT_GOLD
    cases = args.cases_root or DEFAULT_GOLD
    smoke = args.smoke_qid or ("q_001" if args.smoke else None)

    result = run_all(
        gold_dir=gold, cases_root=cases,
        c85_dir=args.c85_dir, smoke_qid=smoke,
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
    print("=== C-98 C-85 合入评估 · 刘翔主尺 ===")
    print(f"A0     {s['A0_hits']}/{s['denom']}  (official_case)")
    for name, a in s["arms"].items():
        extra = f" B*={a['B_star']}" if "B_star" in a else ""
        print(
            f"{name:12s} {a['hits']}/{a['denom']} "
            f"lost={a['lost']} gained={a['gained']} "
            f"Δ={a['delta_vs_a0']:+d}  [{a['status']}]{extra}"
        )
    o = s["oracle_C85_gold_mono"]
    print(
        f"{'oracle_gold':12s} {o['hits']}/{o['denom']} "
        f"lost={o['lost']} gained={o['gained']} "
        f"Δ={o['delta_vs_a0']:+d}  [{o['status']}]  (禁合入)"
    )
    rec = s["recommendation"]
    print("go_nogo", rec["go_nogo"])
    print("reason ", rec["reason"])
    if s.get("leave_one_boost"):
        print(
            "leave_one_boost",
            [
                (x["hold_qid"], x["B_from_train"], x["pass"])
                for x in s["leave_one_boost"]
            ],
        )
    six = s.get("six_case_side") or {}
    if six:
        print(
            "six_side",
            f"A0={six.get('a0_l2')} C={six.get('C_l2')} "
            f"lost={six.get('lost_n')} gained={six.get('gained_n')}",
        )
    cost = s["cost_frozen"]
    print(
        "cost_frozen",
        f"calls={cost.get('total_llm_calls')} "
        f"wall_s={cost.get('total_elapsed_s_scored')} "
        f"lx_rough_s={cost.get('liuxiang_wall_s_rough')}",
    )
    print("wrote", args.out_dir)


if __name__ == "__main__":
    main()
