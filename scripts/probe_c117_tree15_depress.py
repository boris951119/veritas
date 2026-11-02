#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-117：树15 满箱减压开／关对照（零 LLM 主尺）。

主路径＝bounded_budget_bump（有 excluded 时 +1 档字预算）。
主尺：刘翔＋holdout L2 合计／满箱披露次数；泄漏＝0。
旁证：@7≥11、holdout 不显著掉。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c117_tree15_depress.py \\
      --out artifacts/C117_tree15_depress.md
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

from app.core.kg_density_bridge import density_submit_surface  # noqa: E402
from app.core.kg_submit_surface import (  # noqa: E402
    FORBIDDEN_PACK_KEYS,
    apply_kg_submit_surface,
    audit_forbidden_keys,
    pack_kwargs_for_kg,
)
from app.core.material import pack_material  # noqa: E402
from app.core.tree15_depress import (  # noqa: E402
    PATH_NAME,
    apply_tree15_depress,
)
from app.ingest.official_case import load_official_case  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

CASES = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
C85 = Path("/tmp/c85_k180")
CASE_LX = "刘翔编制“二选一”事件"
QIDS = ("q_001", "q_002", "q_003")
PLAN = (
    [("liuxiang", CASE_LX, f"q_00{i}", "regression") for i in (1, 2, 3)]
    + [("wanghong", "王虹“北大discouraged”事件", f"q_00{i}", "holdout")
       for i in (1, 2, 3)]
    + [("kh_th", "柬泰边境争端（2025.12–2026.9）", f"q_00{i}", "holdout")
       for i in (1, 2, 3)]
    + [("ai171", "印度航空 AI171 空难（2025.6–2026.5）", f"q_00{i}", "holdout")
       for i in (1, 2, 3)]
)


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


def _run(case: str, qid: str, *, flag: str) -> dict[str, Any]:
    os.environ["VERITAS_TREE15_DEPRESS"] = flag
    os.environ["VERITAS_KG_SUBMIT_SURFACE"] = "1"
    os.environ["VERITAS_KG_STAGE1"] = "1"
    os.environ["VERITAS_KG_REHYDRATE_BOX"] = "1"
    meta = _meta().get((case, qid)) or {}
    query = str(meta.get("query") or qid)
    budget = int(meta.get("budget") or 12_000)
    gold, denom = _gold_keys(DEFAULT_GOLD, case, qid)
    gold_seg = _gold_seg(gold)
    d = load_official_case(CASES / case)
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
    n_full = 1 if pack.get("excluded") else 0
    if flag in ("1", "true", "on", "yes"):
        pack, dep = apply_tree15_depress(
            d, pack, enabled=True, pack_kwargs=dict(kw or {}),
        )
    else:
        pack, dep = apply_tree15_depress(
            d, pack, enabled=False, pack_kwargs=dict(kw or {}),
        )
    sel = {str(x) for x in (pack.get("selected") or [])}
    return {
        "l2": l2_hits(gold, selected_locs(d, sel)),
        "at7": _at7(d, sel, gold),
        "denom": denom,
        "n_sel": len(sel),
        "n_excluded": len(pack.get("excluded") or []),
        "full_box": n_full,
        "triggered": bool(dep.get("triggered")),
        "budget_before": dep.get("budget_before"),
        "budget_after": dep.get("budget_after"),
        "leaks": len(leaks) + len(audit_forbidden_keys(dep)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/C117_tree15_depress.md")
    args = ap.parse_args()
    t0 = time.time()
    if not CASES.is_dir():
        print(f"missing {CASES}", file=sys.stderr)
        return 2

    rows = []
    for slug, case, qid, role in PLAN:
        print(f"… {slug}/{qid}", flush=True)
        off = _run(case, qid, flag="0")
        on = _run(case, qid, flag="1")
        rows.append({
            "slug": slug, "case": case, "qid": qid, "role": role,
            "off": off, "on": on,
            "delta_l2": on["l2"] - off["l2"],
            "delta_at7": on["at7"] - off["at7"],
        })
        print(
            f"   L2 {off['l2']}→{on['l2']} @7 {off['at7']}→{on['at7']} "
            f"full {off['full_box']}→trig={on['triggered']}",
            flush=True,
        )

    lx = [r for r in rows if r["role"] == "regression"]
    ho = [r for r in rows if r["role"] == "holdout"]
    lx_l2_off = sum(r["off"]["l2"] for r in lx)
    lx_l2_on = sum(r["on"]["l2"] for r in lx)
    ho_l2_off = sum(r["off"]["l2"] for r in ho)
    ho_l2_on = sum(r["on"]["l2"] for r in ho)
    lx_at7_off = sum(r["off"]["at7"] for r in lx)
    lx_at7_on = sum(r["on"]["at7"] for r in lx)
    full_off = sum(r["off"]["full_box"] for r in rows)
    full_on_left = sum(1 for r in rows if r["on"]["n_excluded"] > 0)
    trig = sum(1 for r in rows if r["on"]["triggered"])
    leaks = sum(r["off"]["leaks"] + r["on"]["leaks"] for r in rows)
    total_l2_off = lx_l2_off + ho_l2_off
    total_l2_on = lx_l2_on + ho_l2_on

    side_ok = (
        lx_at7_on >= 11
        and lx_at7_on >= lx_at7_off
        and ho_l2_on >= ho_l2_off - 1
        and leaks == 0
    )
    l2_gain = total_l2_on > total_l2_off
    l2_flat = total_l2_on == total_l2_off
    if l2_gain and side_ok:
        advice = "YES"
    elif (l2_gain or (l2_flat and trig == 0)) and side_ok and leaks == 0:
        # 旁证绿但 L2 无稳定增益 → 弱 YES／不合
        advice = "弱 YES" if not l2_gain else "YES"
    else:
        advice = "NO"
    # 明确：无 L2 增益即使旁证绿也标弱 YES
    if advice == "YES" and not l2_gain:
        advice = "弱 YES"
    if advice == "弱 YES" and not side_ok:
        advice = "NO"

    wall = time.time() - t0
    lines = [
        "# C-117 树15 满箱减压（开／关对照）",
        "",
        f"> 零 LLM；旗默认关；`VERITAS_TREE15_DEPRESS=1` 开。墙钟 {wall:.1f}s。",
        f"> **主路径**：`{PATH_NAME}`（有 excluded → +1 档字预算重装；硬顶 "
        f"factor/ABS；续盒最多 +1）。",
        "> 挂点：`app/core/tree15_depress.py`；`pipeline` 装箱后；`config` 旗。",
        f"> 过线建议：**{advice}** — L2 合计 关 {total_l2_off} → 开 {total_l2_on}；"
        f"满箱披露题数 关 {full_off}／开后仍 excluded {full_on_left}；"
        f"触发加重装 {trig}；泄漏={leaks}。",
        "",
        "## 结论",
        "",
        f"- L2 合计（刘翔+holdout）：关 **{total_l2_off}** → 开 **{total_l2_on}**"
        f"（Δ{total_l2_on - total_l2_off:+d}）",
        f"- 刘翔 L2：{lx_l2_off}→{lx_l2_on}；holdout L2：{ho_l2_off}→{ho_l2_on}",
        f"- 满箱（首装 excluded>0）题数：关 **{full_off}**；开旗触发 **{trig}**；"
        f"开后仍装不下 **{full_on_left}**",
        f"- 旁证刘翔@7：关 {lx_at7_off}／开 {lx_at7_on}；holdout L2 同上",
        f"- 泄漏：**{leaks}**",
        f"- **合入建议：{'可建议末批另拍' if advice == 'YES' else '不合 main'}**；"
        "本票／C-113～116 均不直接合；未并 C-113。",
        "",
        "## 分题",
        "",
        "| slug/qid | L2 off→on | @7 off→on | full | triggered | ΔL2 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['slug']}/{r['qid']} | {r['off']['l2']}→{r['on']['l2']} | "
            f"{r['off']['at7']}→{r['on']['at7']} | {r['off']['full_box']} | "
            f"{int(r['on']['triggered'])} | {r['delta_l2']:+d} |"
        )
    lines += [
        "",
        "## 一行验收",
        "",
        f"过线建议 **{advice}**＋L2 {total_l2_off}→{total_l2_on}"
        f"／泄漏{leaks}／旁证@7={lx_at7_on}/holdout={ho_l2_on}",
        "",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "advice": advice,
        "path": PATH_NAME,
        "total_l2_off": total_l2_off,
        "total_l2_on": total_l2_on,
        "lx_l2_off": lx_l2_off,
        "lx_l2_on": lx_l2_on,
        "holdout_l2_off": ho_l2_off,
        "holdout_l2_on": ho_l2_on,
        "lx_at7_off": lx_at7_off,
        "lx_at7_on": lx_at7_on,
        "full_off": full_off,
        "full_on_left": full_on_left,
        "triggered": trig,
        "leaks": leaks,
        "rows": rows,
        "wall_s": wall,
        "hooks": [
            "app/core/tree15_depress.py",
            "app/pipeline.py",
            "app/config.py",
        ],
        "flag": "VERITAS_TREE15_DEPRESS",
        "flag_default": False,
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
