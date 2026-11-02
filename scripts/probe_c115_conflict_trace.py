#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-115：冲突三类覆盖＋处置留痕开／关对照（零 LLM 主尺）。

主尺：样例对撞条目三类覆盖率、unclassified、留痕齐全率；泄漏＝0。
旁证：刘翔@7／holdout L2（装箱面）。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c115_conflict_trace.py \\
      --out artifacts/C115_conflict_trace.md
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

from app.core.conflict_trace import (  # noqa: E402
    apply_conflict_trace,
    summarize_trace,
    trace_fields_complete,
)
from app.core.fact_ledger import find_collisions  # noqa: E402
from app.core.kg_density_bridge import density_submit_surface  # noqa: E402
from app.core.kg_submit_surface import (  # noqa: E402
    FORBIDDEN_PACK_KEYS,
    apply_kg_submit_surface,
    audit_forbidden_keys,
    pack_kwargs_for_kg,
)
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

CASES = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
C85 = Path("/tmp/c85_k180")
CASE_LX = "刘翔编制“二选一”事件"
QIDS = ("q_001", "q_002", "q_003")
HOLDOUT = (
    ("王虹“北大discouraged”事件", "wanghong"),
    ("柬泰边境争端（2025.12–2026.9）", "kh_th"),
    ("印度航空 AI171 空难（2025.6–2026.5）", "ai171"),
)
SAMPLE = (
    CASE_LX,
    "王虹“北大discouraged”事件",
    "柬泰边境争端（2025.12–2026.9）",
    "印度航空 AI171 空难（2025.6–2026.5）",
)


def _measure_case(case_name: str) -> dict[str, Any]:
    d = load_official_case(CASES / case_name)
    cols = find_collisions(d)

    # 旗关：不写结构面 → 覆盖／留痕记 0（对照基线）
    os.environ["VERITAS_CONFLICT_TRACE"] = "0"
    off_payload = apply_conflict_trace(d, collisions=cols, enabled=False)
    off = {
        "n": len(cols),
        "classified": 0,
        "unclassified": len(cols) if cols else 0,
        "coverage_rate": 0.0,
        "trace_complete": 0,
        "trace_complete_rate": 0.0,
        "by_class": {},
        "written": off_payload is not None,
    }

    # 旗开
    os.environ["VERITAS_CONFLICT_TRACE"] = "1"
    d2 = load_official_case(CASES / case_name)
    cols2 = find_collisions(d2)
    on_payload = apply_conflict_trace(d2, collisions=cols2, enabled=True)
    assert on_payload is not None
    leaks = audit_forbidden_keys(on_payload)
    sm = on_payload["summary"]
    # 自检：每条齐全
    n_complete = sum(
        1 for r in on_payload["records"] if trace_fields_complete(r)
    )
    return {
        "case": case_name,
        "n_collisions": len(cols2),
        "off": off,
        "on": sm,
        "on_trace_complete_check": n_complete,
        "leaks": leaks,
        "by_class": sm.get("by_class") or {},
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
    os.environ["VERITAS_CONFLICT_TRACE"] = flag
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
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/C115_conflict_trace.md")
    args = ap.parse_args()
    t0 = time.time()
    if not CASES.is_dir():
        print(f"missing cases: {CASES}", file=sys.stderr)
        return 2

    rows = [_measure_case(c) for c in SAMPLE]
    n_off = sum(r["off"]["n"] for r in rows)
    # 旗关结构覆盖＝0；旗开按 summary 汇总
    on_n = sum(r["on"]["n"] for r in rows)
    on_classified = sum(r["on"]["classified"] for r in rows)
    on_unclass = sum(r["on"]["unclassified"] for r in rows)
    on_complete = sum(r["on"]["trace_complete"] for r in rows)
    off_coverage = 0.0
    on_coverage = (on_classified / on_n) if on_n else 0.0
    off_trace = 0.0
    on_trace = (on_complete / on_n) if on_n else 0.0
    leaks_n = sum(len(r["leaks"]) for r in rows)

    side = _side_pack()
    side_ok = True
    if not side.get("skipped"):
        side_ok = (
            side["lx_at7_on"] >= 11
            and side["lx_at7_on"] >= side["lx_at7_off"]
            and side["holdout_l2_on"] >= side["holdout_l2_off"] - 1
            and side.get("pack_leaks", 0) == 0
        )

    # 过线：覆盖／留痕相对旗关稳定增益；泄漏0；旁证不掉
    pass_line = (
        on_coverage > off_coverage + 1e-12
        and on_trace > off_trace + 1e-12
        and leaks_n == 0
        and side_ok
        and on_n > 0
    )
    # unclassified 相对「全未归类」下降
    unclass_drop = (n_off - on_unclass) if n_off else 0
    advice = "YES" if pass_line else "NO"
    wall = time.time() - t0

    lines = [
        "# C-115 冲突三类覆盖＋处置留痕（开／关对照）",
        "",
        f"> 零 LLM 主尺；旗默认关；`VERITAS_CONFLICT_TRACE=1` 开。墙钟 {wall:.1f}s。",
        "> 挂点：`app/core/conflict_trace.py`；`pipeline` hygiene／仲裁后；"
        "`export/official` 回放面；`config` 旗。",
        f"> 过线建议：**{advice}** — 覆盖 关 {off_coverage:.4f} → 开 {on_coverage:.4f}；"
        f"留痕 关 {off_trace:.4f} → 开 {on_trace:.4f}；"
        f"unclassified {n_off}→{on_unclass}；泄漏={leaks_n}。",
        "",
        "## 结论",
        "",
        f"- 三类覆盖率：关 **{off_coverage:.4f}** → 开 **{on_classified}/{on_n}"
        f"={on_coverage:.4f}**",
        f"- unclassified：关（无结构＝全未归类）**{n_off}** → 开 **{on_unclass}**"
        f"（下降 {unclass_drop}）",
        f"- 留痕齐全率：关 **{off_trace:.4f}** → 开 **{on_complete}/{on_n}"
        f"={on_trace:.4f}**",
        f"- 泄漏：**{leaks_n}**",
        (
            f"- 旁证刘翔@7：关 {side.get('lx_at7_off')}／开 {side.get('lx_at7_on')}；"
            f"holdout L2：关 {side.get('holdout_l2_off')}／开 {side.get('holdout_l2_on')}"
            if not side.get("skipped")
            else f"- 旁证装箱：跳过（{side.get('reason')}）"
        ),
        f"- **合入建议：{'可建议末批统一合（仍默认关）' if advice == 'YES' else '不合'}**；"
        "本票／C-113／C-114 均不直接合 main。",
        "",
        "## 分案",
        "",
        "| case | n | on_coverage | unclassified | trace_complete | by_class |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        bc = r["by_class"]
        bc_s = (
            f"sw={bc.get('same_window', 0)}/"
            f"cd={bc.get('cross_day', 0)}/"
            f"ut={bc.get('unknown_time', 0)}/"
            f"uc={bc.get('unclassified', 0)}"
        )
        lines.append(
            f"| {r['case']} | {r['n_collisions']} | "
            f"{r['on']['coverage_rate']:.3f} | {r['on']['unclassified']} | "
            f"{r['on']['trace_complete']}/{r['on']['n']} | {bc_s} |"
        )
    lines += [
        "",
        "## 一行验收",
        "",
        f"过线建议 **{advice}**＋覆盖{on_coverage:.4f}／留痕{on_trace:.4f}"
        f"／泄漏{leaks_n}／旁证@7="
        f"{side.get('lx_at7_on', 'NA')}/holdout="
        f"{side.get('holdout_l2_on', 'NA')}",
        "",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "advice": advice,
        "off_coverage": off_coverage,
        "on_coverage": on_coverage,
        "off_trace": off_trace,
        "on_trace": on_trace,
        "on_n": on_n,
        "on_classified": on_classified,
        "on_unclassified": on_unclass,
        "leaks": leaks_n,
        "unclass_drop": unclass_drop,
        "side": side,
        "cases": rows,
        "wall_s": wall,
        "hooks": [
            "app/core/conflict_trace.py",
            "app/pipeline.py",
            "app/export/official.py",
            "app/config.py",
        ],
        "flag": "VERITAS_CONFLICT_TRACE",
        "flag_default": False,
        "classes": ["same_window", "cross_day", "unknown_time"],
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
