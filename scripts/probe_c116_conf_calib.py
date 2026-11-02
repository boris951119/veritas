#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-116：置信档校准闸开／关对照（零 LLM；自标 labels_self／face_v2 快照）。

主尺：高档精确度（strict「对」）＋旁报 ECE；泄漏＝0。
旁证：刘翔@7／holdout L2。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c116_conf_calib.py \\
      --out artifacts/C116_conf_calib.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.conf_calib import (  # noqa: E402
    build_calib_row,
    demote_reasons_from_parts,
    gated_band,
    high_band_precision,
)
from app.core.confidence import band_of  # noqa: E402
from app.core.kg_density_bridge import density_submit_surface  # noqa: E402
from app.core.kg_submit_surface import (  # noqa: E402
    FORBIDDEN_PACK_KEYS,
    apply_kg_submit_surface,
    audit_forbidden_keys,
    pack_kwargs_for_kg,
)
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from scripts.calibrate_confidence import compute_curve  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

SNAP = ROOT / "calibration/face_v2_row_snapshot.jsonl"
LABELS = ROOT / "calibration/labels_self.jsonl"
CASES = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
C85 = Path("/tmp/c85_k180")
CASE_LX = "刘翔编制“二选一”事件"
QIDS = ("q_001", "q_002", "q_003")
HOLDOUT = (
    ("王虹“北大discouraged”事件", "wanghong"),
    ("柬泰边境争端（2025.12–2026.9）", "kh_th"),
    ("印度航空 AI171 空难（2025.6–2026.5）", "ai171"),
)


def _load_snapshot() -> list[dict[str, Any]]:
    if not SNAP.is_file():
        raise SystemExit(f"missing snapshot: {SNAP}")
    # join labels by (case, statement_sha8) — snapshot 已带 label
    rows = []
    for line in SNAP.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows.append(r)
    return rows


def _measure_calib() -> dict[str, Any]:
    snap = _load_snapshot()
    off_rows: list[dict] = []
    on_rows: list[dict] = []
    curve_off: list[dict] = []
    curve_on: list[dict] = []
    leaks: list = []

    for r in snap:
        score = float(r.get("score_v2") or 0.0)
        parts = dict(r.get("parts") or {})
        lab = str(r.get("label") or "")
        case = str(r.get("case") or "")
        cid = str(r.get("conclusion_id") or "")

        # 旗关
        os.environ["VERITAS_CONF_CALIB"] = "0"
        g_off = gated_band(score, parts=parts, enabled=False)
        off_rows.append(build_calib_row(
            conclusion_id=cid, score=score, gated=g_off, label=lab, case=case,
        ))
        curve_off.append({
            "score": score, "label": lab, "labeled_by": "Boyu", "case": case,
        })

        # 旗开：band 可降；ECE 用呈现分（降档→钳到 0.799，不改库存分）
        os.environ["VERITAS_CONF_CALIB"] = "1"
        g_on = gated_band(score, parts=parts, enabled=True)
        on_rows.append(build_calib_row(
            conclusion_id=cid, score=score, gated=g_on, label=lab, case=case,
        ))
        score_present = score
        if g_on["demoted"] and g_on["predicted_band"] == "高":
            score_present = min(score, 0.799)
        curve_on.append({
            "score": score_present, "label": lab,
            "labeled_by": "Boyu", "case": case,
        })
        leaks.extend(audit_forbidden_keys(g_on))

    prec_off = high_band_precision(off_rows, band_key="band")
    prec_on = high_band_precision(on_rows, band_key="band")
    ece_off = compute_curve(curve_off)
    ece_on = compute_curve(curve_on)
    n_demoted = sum(1 for r in on_rows if r.get("demoted"))
    return {
        "n": len(snap),
        "prec_off": prec_off,
        "prec_on": prec_on,
        "ece_off": ece_off["ece"],
        "ece_on": ece_on["ece"],
        "high_cov_off": ece_off["high_coverage_count"],
        "high_cov_on": ece_on["high_coverage_count"],
        "n_demoted": n_demoted,
        "leaks": leaks,
        "sample_demote_reasons": demote_reasons_from_parts(
            (snap[0].get("parts") if snap else {}) or {}
        ),
    }


def _meta() -> dict[tuple[str, str], dict]:
    if not (C85 / "score_input.json").exists():
        return {}
    return {
        (j["case"], j["qid"]): j
        for j in json.loads((C85 / "score_input.json").read_text(encoding="utf-8"))
    }


def _gold_seg(gold: set) -> set[str]:
    return {
        str(loc) if "#" in str(loc) else f"{doc}#{loc}"
        for doc, loc in gold
    }


def _at7(dossier, selected: set[str], gold: set) -> int:
    pri = [
        str(x) for x in (dossier.accounting or {}).get("kg_priority_segment_ids") or []
    ]
    head = [x for x in pri if x in selected][:7]
    if len(head) < 7:
        head = head + sorted(selected - set(head))[: 7 - len(head)]
    return l2_hits(gold, selected_locs(dossier, set(head)))


def _pack_l2(case_name: str, qid: str, flag: str) -> dict[str, int]:
    os.environ["VERITAS_CONF_CALIB"] = flag
    os.environ["VERITAS_KG_SUBMIT_SURFACE"] = "1"
    os.environ["VERITAS_KG_STAGE1"] = "1"
    os.environ["VERITAS_KG_REHYDRATE_BOX"] = "1"
    meta = _meta().get((case_name, qid)) or {}
    query = str(meta.get("query") or qid)
    budget = int(meta.get("budget") or 12_000)
    gold, _ = _gold_keys(DEFAULT_GOLD, case_name, qid)
    gold_seg = _gold_seg(gold)
    d = load_official_case(CASES / case_name)
    d.question = query
    bridge = density_submit_surface(
        d, top_n=180, order=None, gold_ids=gold_seg or None, use_stage1=True,
    )
    leaks = audit_forbidden_keys(bridge["surface"])
    d.accounting["kg_submit"] = bridge["surface"]
    d.accounting["kg_cap_segments"] = False
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    for bad in FORBIDDEN_PACK_KEYS:
        assert bad not in (kw or {})
    pack = pack_material(d, budget_chars=budget, **(kw or {}))
    selected = {str(x) for x in (pack.get("selected") or [])}
    return {
        "l2": l2_hits(gold, selected_locs(d, selected)),
        "at7": _at7(d, selected, gold),
        "leaks": len(leaks),
    }


def _side_pack() -> dict[str, Any]:
    if not C85.is_dir() or not (C85 / "score_input.json").exists():
        return {"skipped": True, "reason": "no /tmp/c85_k180"}
    lx_off = [_pack_l2(CASE_LX, qid, "0") for qid in QIDS]
    lx_on = [_pack_l2(CASE_LX, qid, "1") for qid in QIDS]
    hold_off: list[dict] = []
    hold_on: list[dict] = []
    for case_name, _ in HOLDOUT:
        for qid in QIDS:
            hold_off.append(_pack_l2(case_name, qid, "0"))
            hold_on.append(_pack_l2(case_name, qid, "1"))
    return {
        "skipped": False,
        "lx_at7_off": sum(x["at7"] for x in lx_off),
        "lx_at7_on": sum(x["at7"] for x in lx_on),
        "holdout_l2_off": sum(x["l2"] for x in hold_off),
        "holdout_l2_on": sum(x["l2"] for x in hold_on),
        "pack_leaks": sum(
            x["leaks"] for x in lx_off + lx_on + hold_off + hold_on
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/C116_conf_calib.md")
    args = ap.parse_args()
    t0 = time.time()

    m = _measure_calib()
    side = _side_pack()
    leaks_n = len(m["leaks"])

    po, pn = m["prec_off"], m["prec_on"]
    prec_off = po.get("precision")
    prec_on = pn.get("precision")
    acc_off = po.get("accuracy")
    acc_on = pn.get("accuracy")
    ece_off, ece_on = m["ece_off"], m["ece_on"]

    side_ok = True
    if not side.get("skipped"):
        side_ok = (
            side["lx_at7_on"] >= 11
            and side["lx_at7_on"] >= side["lx_at7_off"]
            and side["holdout_l2_on"] >= side["holdout_l2_off"] - 1
            and side.get("pack_leaks", 0) == 0
        )

    # 过线：高档精确度增益 或 ECE 下降；泄漏0；旁证不掉
    prec_gain = (
        prec_off is not None and prec_on is not None
        and prec_on > prec_off + 1e-12
    )
    ece_drop = ece_on < ece_off - 1e-12
    pass_line = (prec_gain or ece_drop) and leaks_n == 0 and side_ok
    # 高档样本开闸后仍须非空，否则精确度不可比
    if not pn.get("n_high"):
        pass_line = False
    advice = "YES" if pass_line else "NO"
    wall = time.time() - t0

    def _fmt(x: float | None) -> str:
        return "NA" if x is None else f"{x:.4f}"

    lines = [
        "# C-116 置信档校准闸（开／关对照）",
        "",
        f"> 零 LLM；旗默认关；`VERITAS_CONF_CALIB=1` 开。墙钟 {wall:.1f}s。",
        "> 挂点：`app/core/conf_calib.py`；`pipeline` finalize；`export/official` 交卷档；"
        "`config` 旗。尺源：`calibration/face_v2_row_snapshot.jsonl`（自标，非金标提示）。",
        f"> 过线建议：**{advice}** — 高档精确度 关 {_fmt(prec_off)} → 开 {_fmt(prec_on)}；"
        f"ECE 关 {ece_off:.6f} → 开 {ece_on:.6f}；泄漏={leaks_n}。",
        "",
        "## 结论",
        "",
        f"- 高档精确度（strict 对）：关 **{po.get('n_hit')}/{po.get('n_high')}="
        f"{_fmt(prec_off)}** → 开 **{pn.get('n_hit')}/{pn.get('n_high')}="
        f"{_fmt(prec_on)}**",
        f"- 高档加权准确率（对=1／部分=0.5／错=0）：关 **{_fmt(acc_off)}** → "
        f"开 **{_fmt(acc_on)}**",
        f"- ECE：关 **{ece_off:.6f}** → 开 **{ece_on:.6f}**"
        f"（降档行呈现分钳到 <0.8；库存 score 不变）",
        f"- 高档覆盖：关 {m['high_cov_off']} → 开 {m['high_cov_on']}；"
        f"降档条数={m['n_demoted']}",
        f"- 泄漏：**{leaks_n}**",
        (
            f"- 旁证刘翔@7：关 {side.get('lx_at7_off')}／开 {side.get('lx_at7_on')}；"
            f"holdout L2：关 {side.get('holdout_l2_off')}／开 {side.get('holdout_l2_on')}"
            if not side.get("skipped")
            else f"- 旁证装箱：跳过（{side.get('reason')}）"
        ),
        f"- **合入建议：{'可建议末批统一合（仍默认关）' if advice == 'YES' else '不合'}**；"
        "本票／C-113～115 均不直接合 main。",
        "",
        "## 门槛（开旗）",
        "",
        "- min_evidence：n_evidence ≥ 2",
        "- anchor_incomplete：引文命中率 ＜ 1 或段不可定位",
        "- chain_incomplete：chain ＜ 1",
        "- panel_disagreement：agreement ＜ 1",
        "- conflict_undecided：落入平局／无裁决冲突对",
        "",
        "## 一行验收",
        "",
        f"过线建议 **{advice}**＋高档精确度{_fmt(prec_on)}／ECE{ece_on:.6f}"
        f"／泄漏{leaks_n}／旁证@7="
        f"{side.get('lx_at7_on', 'NA')}/holdout="
        f"{side.get('holdout_l2_on', 'NA')}",
        "",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "advice": advice,
        "prec_off": prec_off,
        "prec_on": prec_on,
        "acc_off": acc_off,
        "acc_on": acc_on,
        "ece_off": ece_off,
        "ece_on": ece_on,
        "high_cov_off": m["high_cov_off"],
        "high_cov_on": m["high_cov_on"],
        "n_demoted": m["n_demoted"],
        "leaks": leaks_n,
        "side": side,
        "detail": m,
        "wall_s": wall,
        "hooks": [
            "app/core/conf_calib.py",
            "app/pipeline.py",
            "app/export/official.py",
            "app/config.py",
        ],
        "flag": "VERITAS_CONF_CALIB",
        "flag_default": False,
        "labels_source": str(SNAP.relative_to(ROOT)),
    }
    args.out.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(lines[-3])
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
