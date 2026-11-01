#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R31：拓尔思另 3 未见过案盒密度 holdout（并入门槛①）。

锁 R19–R30 规则，禁止为本 holdout 调参／加案专名。
门槛①：另 3 案各自案均盒密度 ≥2/3，且刘翔 @7 ≥11。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.kg_lab.run_r22_intent_density import (  # noqa: E402
    OUT,
    _coeff_names,
    _eval_case,
)

# 已拟合／冒烟：liuxiang、jilong、us_cn_ai
# 本票 holdout＝样例集剩余三案（写死名单，禁止换案调参）
HOLDOUT = [
    {
        "slug": "wanghong",
        "mark": "王虹",
        "title": "王虹“北大discouraged”事件",
    },
    {
        "slug": "kh_th",
        "mark": "柬泰",
        "title": "柬泰边境争端（2025.12–2026.9）",
    },
    {
        "slug": "ai171",
        "mark": "印度",
        "title": "印度航空 AI171 空难（2025.6–2026.5）",
    },
]

FITTED = ("liuxiang", "jilong", "us_cn_ai")
GATE_DENS = 2.0 / 3.0
LIUXIANG_AT7_MIN = 11
R30_LX_AT7 = 12  # 回归对照


def _markdown(report: dict[str, Any]) -> str:
    gate = report["gate"]
    lines = [
        "# R31 — 拓尔思另 3 案盒密度 holdout（门槛①）",
        "",
        "## 结论先行",
        "",
        f"- **门槛①：{'通过' if gate['pass'] else '未通过'}**"
        f"（另 3 案案均 ≥2/3＝{gate['holdout_all_ge_23']}；"
        f"刘翔 @7≥11＝{gate['liuxiang_ok']}）。",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。锁 R19–R30；零调参；无案专名；本机规则＋既有嵌入，禁百炼。",
        "",
        "## Holdout 案名单（排除已拟合三案）",
        "",
        "| slug | 样例目录名 | 说明 |",
        "|---|---|---|",
    ]
    for h in HOLDOUT:
        lines.append(f"| `{h['slug']}` | {h['title']} | 未见过／未拟合 |")
    lines += [
        "",
        f"已排除（已拟合）：{', '.join(FITTED)}。",
        "",
        "## 盒密度主表",
        "",
        "| 案 | 角色 | 池20 | @7 | Σ金标/Σk | 案均密度 | ≥2/3题 | 门槛 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for c in report["cases"]:
        role = c.get("role") or ""
        n_ok = sum(1 for r in c["density_rows"] if r["gold_density"] + 1e-12 >= GATE_DENS)
        ge = c["micro_gold_density"] + 1e-12 >= GATE_DENS
        if role == "holdout":
            gate_s = "✓ ≥2/3" if ge else f"✗ 差 {GATE_DENS - c['micro_gold_density']:.0%}"
        elif role == "regression":
            gate_s = (
                f"✓ @7≥{LIUXIANG_AT7_MIN}"
                if c["cut_hits"]["7"] >= LIUXIANG_AT7_MIN
                else f"✗ @7={c['cut_hits']['7']}"
            )
        else:
            gate_s = "—"
        lines.append(
            f"| {c['slug']} | {role} | {c['pool_hits']['20']} | "
            f"{c['cut_hits']['7']}/{c['gold_total']} | "
            f"{c['sum_gold_in_boxes']}/{c['sum_k']} | "
            f"{c['micro_gold_density']:.0%} | "
            f"{n_ok}/{len(c['density_rows'])} | {gate_s} |"
        )
    lines += [
        "",
        "### 分题",
        "",
        "| 案 | qid | 池20 | k | 盒金标 | 密度 | route |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for c in report["cases"]:
        for q in c["questions"]:
            r = q["density"]
            p20 = q["pool"]["20"]
            lines.append(
                f"| {c['slug']} | {q['qid']} | "
                f"{p20['hits']}/{p20['gold_total']} | "
                f"{r['k']} | {r['n_gold']} | {r['gold_density']:.0%} | "
                f"{r['route']} |"
            )
    lines += [
        "",
        "## 门槛①判定",
        "",
        f"- 另 3 案各自案均 ≥2/3：**{'是' if gate['holdout_all_ge_23'] else '否'}**"
        f"（通过 {gate['n_holdout_pass']}/3）。",
        f"- 刘翔回归 @7≥{LIUXIANG_AT7_MIN}：**{'是' if gate['liuxiang_ok'] else '否'}**"
        f"（本跑 @7={gate['liuxiang_at7']}，R30={R30_LX_AT7}）。",
        f"- **总判：{'通过门槛①' if gate['pass'] else '未过门槛①'}**。",
        "",
        "## 纪律",
        "",
        "- 本票只量不调：未改 `app/kg_lab` 排序／装箱系数，未加案专名。",
        "- 更高密度冲刺仍冻结。",
        "",
        "## 路径",
        "- `artifacts/R31_holdout3.json`",
        "- `artifacts/R31_holdout3.md`",
        "",
    ]
    if not gate["pass"]:
        lines += [
            "## 差距（如实，不拟合）",
            "",
        ]
        for c in report["cases"]:
            if c.get("role") != "holdout":
                continue
            gap = GATE_DENS - c["micro_gold_density"]
            if gap > 1e-12:
                lines.append(
                    f"- `{c['slug']}` 案均 {c['micro_gold_density']:.0%}，"
                    f"距 2/3 差 {gap:.0%} "
                    f"（{c['sum_gold_in_boxes']}/{c['sum_k']}）。"
                )
                for r in c["density_rows"]:
                    if r["gold_density"] + 1e-12 < GATE_DENS:
                        lines.append(
                            f"  - {r['qid']}：{r['gold_density']:.0%} "
                            f"（{r['n_gold']}/{r['k']}）"
                        )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    coeff, names = _coeff_names()
    # 回归臂：刘翔 prefer_gold 关密度重排（与 R22–R30 同口径）
    lx = _eval_case("liuxiang", "刘翔", coeff, names, prefer_gold=True)
    lx["role"] = "regression"
    holdout_cases: list[dict[str, Any]] = []
    for h in HOLDOUT:
        c = _eval_case(h["slug"], h["mark"], coeff, names, prefer_gold=False)
        c["role"] = "holdout"
        c["title"] = h["title"]
        holdout_cases.append(c)

    bullets: list[str] = []
    bullets.append(
        f"刘翔回归：@7 **{lx['cut_hits']['7']}/{lx['gold_total']}**"
        f"（门槛 ≥{LIUXIANG_AT7_MIN}；R30={R30_LX_AT7}）；"
        f"盒微密度 {lx['micro_gold_density']:.0%}。"
    )
    n_pass = 0
    for c in holdout_cases:
        ge = c["micro_gold_density"] + 1e-12 >= GATE_DENS
        n_pass += int(ge)
        n_ok = sum(1 for r in c["density_rows"] if r["gold_density"] + 1e-12 >= GATE_DENS)
        bullets.append(
            f"holdout `{c['slug']}`（{c.get('title') or c['slug']}）："
            f"案均 **{c['micro_gold_density']:.0%}**"
            f"（{c['sum_gold_in_boxes']}/{c['sum_k']}）"
            f"{'≥' if ge else '<'}2/3；"
            f"池20={c['pool_hits']['20']}；@7={c['cut_hits']['7']}；"
            f"≥2/3题 {n_ok}/{len(c['density_rows'])}。"
        )

    holdout_all = n_pass == len(holdout_cases)
    lx_ok = lx["cut_hits"]["7"] >= LIUXIANG_AT7_MIN
    gate = {
        "pass": holdout_all and lx_ok,
        "holdout_all_ge_23": holdout_all,
        "n_holdout_pass": n_pass,
        "liuxiang_ok": lx_ok,
        "liuxiang_at7": lx["cut_hits"]["7"],
        "threshold": GATE_DENS,
    }
    bullets.insert(
        0,
        f"门槛① **{'通过' if gate['pass'] else '未通过'}**"
        f"（holdout {n_pass}/3 案均≥2/3；刘翔 @7={'过' if lx_ok else '不过'}）。",
    )

    report = {
        "ticket": "R31-holdout3",
        "holdout": HOLDOUT,
        "fitted_excluded": list(FITTED),
        "cases": [lx] + holdout_cases,
        "gate": gate,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
        "rules_locked": "R19-R30",
        "no_tuning": True,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R31_holdout3.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R31_holdout3.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)
    print(
        f"gates: holdout_all={holdout_all} n_pass={n_pass}/3 "
        f"liuxiang_ok={lx_ok} → {'PASS' if gate['pass'] else 'FAIL'}",
        flush=True,
    )
    # 本票允许 FAIL（如实报差距）；exit 0 方便留产物；用 gate.pass 作语义
    # 仍用 0/2 区分：通过 0，未过 2（与 R22–R30 一致）
    return 0 if gate["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
