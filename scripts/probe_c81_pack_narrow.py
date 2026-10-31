#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-81 件①：改装箱哲学（宽召回／窄进窗）——只量、零模型。

对照臂（同六案 18 题、同金标分母 105、同 pack_window.budget）：
  A0     ＝现行 pack_material（必须复现 L2＝48/105）
  N20／N40／N60＝max_segments＝20／40／60 ＋ fill_zero_score=False
  NZ     ＝仅 fill_zero_score=False（预算仍可装满有分的段）

量尺（同时看两根，不许只报准）：
  L2 召回 ＝金标命中／105
  纯度     ＝金标命中／装入段数（合计）

判据（入库／默认开之前）：
  a  A0 复现 48/105（复现不出＝停手）
  b  至少一臂纯度 ≥ A0 纯度 ×2，且该臂 L2 ≥ 40/105
  逃逸：纯度涨但召回崩、或无人过 b ⇒ 记表、生产默认不动

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c81_pack_narrow.py \\
      --run-dir /tmp/six2 --dry-run
  PYTHONPATH=. .venv/bin/python scripts/probe_c81_pack_narrow.py \\
      --run-dir /tmp/six2 --run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from app.export.official import _segment_locator  # noqa: E402
from scripts.probe_c66_multi_box import (  # noqa: E402
    construct_jobs,
    gold_keys_for,
    l2_hits,
    selected_locs,
)
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

TARGET_A0 = 48
TARGET_DENOM = 105


def _pack_arm(dossier: Dossier, budget: int, arm: str) -> dict:
    if arm == "A0":
        return pack_material(dossier, budget_chars=budget)
    if arm == "NZ":
        return pack_material(
            dossier, budget_chars=budget, fill_zero_score=False)
    if arm.startswith("N") and arm[1:].isdigit():
        n = int(arm[1:])
        return pack_material(
            dossier, budget_chars=budget,
            max_segments=n, fill_zero_score=False)
    raise ValueError(f"unknown arm {arm!r}")


def run_measure(jobs: list[dict], gold_dir: Path) -> dict[str, Any]:
    arms = ["A0", "NZ", "N20", "N40", "N60"]
    tot = {a: {"hits": 0, "n_sel": 0, "denom": 0} for a in arms}
    rows: list[dict] = []

    for job in jobs:
        budget = int(job["budget"])
        raw = json.loads(Path(job["report"]).read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(raw)
        gold, denom = gold_keys_for(gold_dir, job["case"], job["qid"])
        if denom == 0:
            continue
        row: dict[str, Any] = {
            "case": job["case"], "qid": job["qid"], "budget": budget,
            "denom": denom,
        }
        for arm in arms:
            pack = _pack_arm(dossier, budget, arm)
            sel = {str(x) for x in (pack.get("selected") or [])}
            locs = selected_locs(dossier, sel)
            hits = l2_hits(gold, locs)
            n_sel = len(sel)
            row[arm] = {"hits": hits, "n_sel": n_sel,
                        "used": int(pack.get("used_chars") or 0)}
            tot[arm]["hits"] += hits
            tot[arm]["n_sel"] += n_sel
            tot[arm]["denom"] += denom
        rows.append(row)

    summary: dict[str, Any] = {"n_questions": len(rows), "arms": {}, "rows": rows}
    for arm in arms:
        h = tot[arm]["hits"]
        n = tot[arm]["n_sel"]
        d = tot[arm]["denom"]
        summary["arms"][arm] = {
            "l2_hits": h,
            "denom": d,
            "n_selected": n,
            "recall": round(h / d, 4) if d else 0.0,
            "precision": round(h / n, 4) if n else 0.0,
        }
    return summary


def judge(summary: dict) -> dict[str, Any]:
    a0 = summary["arms"]["A0"]
    out: dict[str, Any] = {
        "a": {
            "ok": a0["l2_hits"] == TARGET_A0 and a0["denom"] == TARGET_DENOM,
            "got": f"{a0['l2_hits']}/{a0['denom']}",
            "want": f"{TARGET_A0}/{TARGET_DENOM}",
        },
        "b_candidates": [],
    }
    p0 = a0["precision"]
    for arm, rec in summary["arms"].items():
        if arm == "A0":
            continue
        ok = (
            p0 > 0
            and rec["precision"] >= p0 * 2
            and rec["l2_hits"] >= 40
            and rec["denom"] == TARGET_DENOM
        )
        out["b_candidates"].append({
            "arm": arm,
            "ok": ok,
            "precision": rec["precision"],
            "a0_precision": p0,
            "l2": f"{rec['l2_hits']}/{rec['denom']}",
        })
    out["b"] = {"ok": any(c["ok"] for c in out["b_candidates"])}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if not args.run and not args.dry_run:
        args.dry_run = True

    run_dir = Path(args.run_dir)
    pack = construct_jobs(run_dir, gold_root=None)
    print("======== C-81 改装箱哲学（只量）========")
    print(f"run_dir＝{pack['run_dir']}｜题数＝{pack['n_questions']}")
    if args.dry_run and not args.run:
        print("干跑：将量 A0／NZ／N20／N40／N60；金标只在 --run 计数步打开。")
        print("判据 a＝A0→48/105；b＝某臂纯度≥A0×2 且 L2≥40/105。")
        return 0

    gold_dir = Path(args.gold_dir)
    if not gold_dir.is_dir():
        print(f"金标目录不存在：{gold_dir}", file=sys.stderr)
        return 2
    summary = run_measure(pack["jobs"], gold_dir)
    print("\n臂｜L2 召回｜装入段｜纯度(命中/装入)")
    for arm, rec in summary["arms"].items():
        print(
            f"  {arm:4}｜{rec['l2_hits']:3}/{rec['denom']} "
            f"（{rec['recall']:.3f}）｜{rec['n_selected']:5}｜"
            f"{rec['precision']:.4f}"
        )
    j = judge(summary)
    print("\n判据 a", "✅" if j["a"]["ok"] else "❌", j["a"])
    print("判据 b", "✅" if j["b"]["ok"] else "❌（逃逸＝记表、默认不动）")
    for c in j["b_candidates"]:
        mark = "✅" if c["ok"] else "·"
        print(
            f"  {mark} {c['arm']}: prec {c['precision']:.4f} "
            f"(A0×2 门槛 {c['a0_precision']*2:.4f}) L2={c['l2']}"
        )
    if args.out:
        outp = Path(args.out)
        outp.write_text(
            json.dumps({"summary": summary, "judge": j},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"\n落盘 {outp}")
    return 0 if j["a"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
