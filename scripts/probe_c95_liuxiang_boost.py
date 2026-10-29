#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-95：刘翔主尺复放 C-91 软保底 ± C-85 K180（只量）。

Boyu：切法轴已关；不以六案扫参当过线。主尺＝刘翔样例集（分母≈14）。
六案历史「C-91 @7500 → 56 lost=0」只并排、**不可外推**。

臂：
  A0          现产 pack_material
  C85         C-85 K180 融合分 + 密度键装箱（沿用 /tmp/c85_k180 缓存）
  C91         生产 BM25 分表上：A0 已装段 +B → 分主序（B 在刘翔重扫）
  C91xC85     C-85 融合分上：A0 已装段 +B → 分主序（同一 B 规则）

B 网格：0‥10000 step 250；禁止直接用六案 7k–8k 当生产默认。
敏感性：leave-one-question——用另两问扫最优 B，验留一问是否塌。

门槛（刘翔尺）：相对刘翔 A0 lost=0 且 L2≥A0；仅扫参过线、换问即塌 → 逃逸。
只量、默认关；不改生产；不 commit。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c95_liuxiang_boost.py \\
      --c85-dir /tmp/c85_k180 --smoke --out-dir /tmp/c95_lx
  PYTHONPATH=. .venv/bin/python scripts/probe_c95_liuxiang_boost.py \\
      --c85-dir /tmp/c85_k180 --out-dir /tmp/c95_lx
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
from scripts.probe_c62_rerank_arms import _pack_with_scores  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _fuse, _gold_keys  # noqa: E402
from scripts.probe_c91_mono_pack import _pack_score_primary  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

CASE_SUB = "刘翔"
B_GRID = list(range(0, 10001, 250))
# 历史六案并排（不可外推）
HIST_SIX = {
    "note": "六案 C-91 软保底曾 B≈7500 → L2=56 lost=0；不可外推到刘翔／生产",
    "B": 7500,
    "l2": 56,
    "lost": 0,
    "denom": 105,
}


def _load_lx_jobs(c85_dir: Path) -> list[dict]:
    jobs = json.loads((c85_dir / "score_input.json").read_text(encoding="utf-8"))
    out = [j for j in jobs if CASE_SUB in j["case"]]
    if len(out) != 3:
        raise SystemExit(f"期望刘翔 3 问，实得 {len(out)}")
    return sorted(out, key=lambda j: j["qid"])


def _id_scores(sc: Any, job: dict) -> dict[str, float]:
    if isinstance(sc, dict):
        return {str(k): float(v) for k, v in sc.items()}
    return {cid: float(s) for cid, s in zip(job["ids"], sc)}


def _prep(job: dict, scores_c: dict, gold_dir: Path) -> dict[str, Any]:
    key = f"{job['case']}::{job['qid']}"
    sc = scores_c.get(key)
    if sc is None:
        raise SystemExit(f"缺分 {key}")
    dossier = Dossier.from_dict(
        json.loads(Path(job["report"]).read_text(encoding="utf-8")))
    budget = int(job["budget"])
    gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
    bm25 = {str(k): float(v) for k, v in job["bm25_scores"].items()}
    id_scores = _id_scores(sc, job)
    for sid in id_scores:
        bm25.setdefault(sid, 0.0)
    fused = _fuse(bm25, id_scores, use_bm25=True)
    p0 = pack_material(dossier, budget_chars=budget)
    sel_a0 = {str(x) for x in (p0.get("selected") or [])}
    loc_a0 = selected_locs(dossier, sel_a0)
    return {
        "job": job, "key": key, "dossier": dossier, "budget": budget,
        "gold": gold, "denom": denom, "bm25": bm25, "fused": fused,
        "sel_a0": sel_a0, "loc_a0": loc_a0,
        "a0_hits": l2_hits(gold, loc_a0),
    }


def _eval_pack(
    prep: dict, selected: set[str],
) -> tuple[int, int, int]:
    loc = selected_locs(prep["dossier"], selected)
    hits = l2_hits(prep["gold"], loc)
    lost = len((prep["gold"] & prep["loc_a0"]) - loc)
    gained = len((prep["gold"] & loc) - prep["loc_a0"])
    return hits, lost, gained


def _boost_pack(
    prep: dict, base_scores: dict[str, float], B: float,
) -> set[str]:
    boosted = dict(base_scores)
    for sid in prep["sel_a0"]:
        boosted[sid] = float(boosted.get(sid, 0.0)) + float(B)
    return _pack_score_primary(prep["dossier"], prep["budget"], boosted)


def _sum_metrics(preps: list[dict], pack_fn) -> dict[str, int]:
    tot = Counter()
    for p in preps:
        sel = pack_fn(p)
        h, lo, g = _eval_pack(p, sel)
        tot["hits"] += h
        tot["lost"] += lo
        tot["gained"] += g
        tot["denom"] += p["denom"]
        tot["a0"] += p["a0_hits"]
    return dict(tot)


def _pick_B(train: list[dict], *, on_fused: bool) -> tuple[float, dict]:
    """扫 B：优先 lost=0，再 hits 最大，再 gained，再 B 小。"""
    best = None
    for B in B_GRID:
        def pack_fn(p, _B=B):
            base = p["fused"] if on_fused else p["bm25"]
            return _boost_pack(p, base, _B)

        tot = _sum_metrics(train, pack_fn)
        key = (
            0 if tot["lost"] == 0 else 1,
            tot["lost"],
            -tot["hits"],
            -tot["gained"],
            B,
        )
        cand = (key, float(B), tot)
        if best is None or cand[0] < best[0]:
            best = cand
    assert best is not None
    return best[1], best[2]


def run_all(c85_dir: Path, gold_dir: Path, *, smoke_qid: str | None) -> dict[str, Any]:
    t0 = time.perf_counter()
    jobs = _load_lx_jobs(c85_dir)
    scores_c = json.loads((c85_dir / "llm_scores_c.json").read_text(encoding="utf-8"))
    preps = [_prep(j, scores_c, gold_dir) for j in jobs]
    if smoke_qid:
        preps = [p for p in preps if p["job"]["qid"] == smoke_qid]
        if not preps:
            raise SystemExit(f"smoke 无此问 {smoke_qid}")

    # ---- 全量臂（B 在全部可用问上扫，乐观）----
    a0_hits = sum(p["a0_hits"] for p in preps)
    denom = sum(p["denom"] for p in preps)

    def pack_a0(p):
        return set(p["sel_a0"])

    def pack_c85(p):
        return _pack_with_scores(p["dossier"], p["budget"], p["fused"])

    tot_a0 = _sum_metrics(preps, pack_a0)
    tot_c85 = _sum_metrics(preps, pack_c85)

    B_c91, tr_c91 = _pick_B(preps, on_fused=False)
    B_combo, tr_combo = _pick_B(preps, on_fused=True)

    def pack_c91(p, _B=B_c91):
        return _boost_pack(p, p["bm25"], _B)

    def pack_combo(p, _B=B_combo):
        return _boost_pack(p, p["fused"], _B)

    tot_c91 = _sum_metrics(preps, pack_c91)
    tot_combo = _sum_metrics(preps, pack_combo)

    # B 敏感曲线（全问）
    curve_c91 = []
    curve_combo = []
    for B in B_GRID:
        t1 = _sum_metrics(
            preps, lambda p, _B=B: _boost_pack(p, p["bm25"], _B))
        t2 = _sum_metrics(
            preps, lambda p, _B=B: _boost_pack(p, p["fused"], _B))
        curve_c91.append({
            "B": B, "hits": t1["hits"], "lost": t1["lost"], "gained": t1["gained"],
            "pass": t1["lost"] == 0 and t1["hits"] >= tot_a0["hits"],
        })
        curve_combo.append({
            "B": B, "hits": t2["hits"], "lost": t2["lost"], "gained": t2["gained"],
            "pass": t2["lost"] == 0 and t2["hits"] >= tot_a0["hits"],
        })

    pass_c91 = [c for c in curve_c91 if c["pass"]]
    pass_combo = [c for c in curve_combo if c["pass"]]

    # ---- leave-one-question ----
    loo_rows = []
    if len(preps) >= 2 and not smoke_qid:
        for hold in preps:
            train = [p for p in preps if p["job"]["qid"] != hold["job"]["qid"]]
            B1, _ = _pick_B(train, on_fused=False)
            B2, _ = _pick_B(train, on_fused=True)
            # eval hold
            for name, B, base_key in (
                ("C91", B1, "bm25"),
                ("C91xC85", B2, "fused"),
            ):
                base = hold[base_key]
                sel = _boost_pack(hold, base, B)
                h, lo, g = _eval_pack(hold, sel)
                loo_rows.append({
                    "hold_qid": hold["job"]["qid"],
                    "arm": name,
                    "B_from_train": B,
                    "hold_denom": hold["denom"],
                    "hold_a0": hold["a0_hits"],
                    "hits": h, "lost": lo, "gained": g,
                    "pass": lo == 0 and h >= hold["a0_hits"],
                    "collapsed": not (lo == 0 and h >= hold["a0_hits"]),
                })

    n_loo = len(loo_rows)
    n_loo_pass = sum(1 for r in loo_rows if r["pass"])
    n_loo_collapse = sum(1 for r in loo_rows if r["collapsed"])

    # 门槛：全量臂 + hold-out
    def arm_pass(tot: dict) -> bool:
        return tot["lost"] == 0 and tot["hits"] >= tot_a0["hits"]

    full_pass = {
        "C91": arm_pass(tot_c91),
        "C85": arm_pass(tot_c85),
        "C91xC85": arm_pass(tot_combo),
    }
    # 逃逸：无臂全量过线，或过线但 leave-one 有塌
    any_full = any(full_pass.values())
    loo_ok = (n_loo == 0) or (n_loo_collapse == 0 and n_loo_pass == n_loo)
    if smoke_qid:
        escape = True
        escape_reason = "烟雾／非整案＝不判主门槛"
    elif not any_full:
        escape = True
        escape_reason = "刘翔全量无臂同时 lost=0 且 L2≥A0"
    elif any_full and not loo_ok:
        escape = True
        escape_reason = "全量或可过线，但 leave-one-question 塌（扫参不稳）"
    else:
        escape = False
        escape_reason = "刘翔尺过线且留一问未塌（仍默认关，合入另票）"

    per_q = []
    for p in preps:
        row = {
            "qid": p["job"]["qid"], "denom": p["denom"], "a0": p["a0_hits"],
        }
        for name, fn in (
            ("C85", pack_c85),
            ("C91", pack_c91),
            ("C91xC85", pack_combo),
        ):
            h, lo, g = _eval_pack(p, fn(p))
            row[f"{name}_hits"] = h
            row[f"{name}_lost"] = lo
            row[f"{name}_gained"] = g
        per_q.append(row)

    return {
        "ticket": "C-95",
        "case": preps[0]["job"]["case"],
        "smoke_qid": smoke_qid,
        "denom": denom,
        "n_questions": len(preps),
        "arms": {
            "A0": {
                "l2_hits": tot_a0["hits"], "lost_n": 0, "gained_n": 0,
                "note": "baseline",
            },
            "C85_K180": {
                "l2_hits": tot_c85["hits"],
                "lost_n": tot_c85["lost"],
                "gained_n": tot_c85["gained"],
                "vs_a0": tot_c85["hits"] - tot_a0["hits"],
                "pass_lx": full_pass["C85"],
            },
            "C91_boost_bm25": {
                "B_full_sweep": B_c91,
                "l2_hits": tot_c91["hits"],
                "lost_n": tot_c91["lost"],
                "gained_n": tot_c91["gained"],
                "vs_a0": tot_c91["hits"] - tot_a0["hits"],
                "pass_lx": full_pass["C91"],
                "train_at_pick": tr_c91,
            },
            "C91xC85": {
                "B_full_sweep": B_combo,
                "l2_hits": tot_combo["hits"],
                "lost_n": tot_combo["lost"],
                "gained_n": tot_combo["gained"],
                "vs_a0": tot_combo["hits"] - tot_a0["hits"],
                "pass_lx": full_pass["C91xC85"],
                "train_at_pick": tr_combo,
            },
        },
        "B_pass_window_c91": (
            [pass_c91[0]["B"], pass_c91[-1]["B"]] if pass_c91 else None
        ),
        "B_pass_window_combo": (
            [pass_combo[0]["B"], pass_combo[-1]["B"]] if pass_combo else None
        ),
        "B_curve_c91_pass_count": len(pass_c91),
        "B_curve_combo_pass_count": len(pass_combo),
        "leave_one_question": loo_rows,
        "loo_n": n_loo,
        "loo_pass_n": n_loo_pass,
        "loo_collapse_n": n_loo_collapse,
        "per_question": per_q,
        "hist_six_c91_side_by_side": HIST_SIX,
        "escape": escape,
        "escape_reason": escape_reason,
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "curves": {"c91": curve_c91, "combo": curve_combo},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--c85-dir", default="/tmp/c85_k180")
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--out-dir", default="/tmp/c95_lx")
    ap.add_argument("--smoke", action="store_true", help="只跑 q_001 烟雾")
    ap.add_argument("--smoke-qid", default="q_001")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    smoke_qid = args.smoke_qid if args.smoke else None
    print(
        f"======== C-95 刘翔主尺 C-91±C-85"
        f"{'（烟雾 '+smoke_qid+'）' if smoke_qid else ''} ========",
        flush=True,
    )
    summary = run_all(
        Path(args.c85_dir), Path(args.gold_dir), smoke_qid=smoke_qid)

    print(f"案＝{summary['case']}  denom={summary['denom']}  "
          f"n_q={summary['n_questions']}", flush=True)
    for name, lab in (
        ("A0", "A0 现产"),
        ("C85_K180", "C-85 K180"),
        ("C91_boost_bm25", "C-91 软保底(BM25+B)"),
        ("C91xC85", "C-91⊕C-85"),
    ):
        a = summary["arms"][name]
        extra = ""
        if "B_full_sweep" in a:
            extra = f" B*={a['B_full_sweep']}"
        pas = a.get("pass_lx")
        tag = "" if pas is None else ("过" if pas else "未过")
        print(
            f"  {lab}: L2={a['l2_hits']}/{summary['denom']} "
            f"lost={a.get('lost_n', 0)} gained={a.get('gained_n', 0)}"
            f"{extra} {tag}",
            flush=True,
        )
    print(
        f"B 过线窗口 C91={summary['B_pass_window_c91']} "
        f"combo={summary['B_pass_window_combo']}",
        flush=True,
    )
    if summary["loo_n"]:
        print(
            f"leave-one-question: pass {summary['loo_pass_n']}/{summary['loo_n']} "
            f"collapse={summary['loo_collapse_n']}",
            flush=True,
        )
        for r in summary["leave_one_question"]:
            mark = "✓" if r["pass"] else "✗塌"
            print(
                f"  hold {r['hold_qid']} {r['arm']} B={r['B_from_train']}: "
                f"{r['hold_a0']}→{r['hits']} L{r['lost']}G{r['gained']} {mark}",
                flush=True,
            )
    print(
        f"并排历史六案 C-91: B={HIST_SIX['B']} L2={HIST_SIX['l2']}/105 "
        f"lost={HIST_SIX['lost']} ⚠不可外推",
        flush=True,
    )
    print(
        f"{'逃逸' if summary['escape'] else '刘翔尺过线'}："
        f"{summary['escape_reason']}",
        flush=True,
    )
    print(f"耗时 {summary['elapsed_s']}s", flush=True)

    # curves 太大可截断存
    slim = dict(summary)
    slim["curves"] = {
        "c91_pass_only": [c for c in summary["curves"]["c91"] if c["pass"]],
        "combo_pass_only": [c for c in summary["curves"]["combo"] if c["pass"]],
        "c91_full": summary["curves"]["c91"],
        "combo_full": summary["curves"]["combo"],
    }
    (out / "summary.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"落盘 {out / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
