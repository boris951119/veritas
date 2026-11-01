#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R23：一筛补洞（专治池外金标）。

主看池20 金标率＋盒密度；对比 R22。刘翔回归 @7≥11。
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

# R22 基线（池20／切点／盒微密度）
R22 = {
    "liuxiang": {
        "pool20": 8, "at4": 9, "at5": 11, "at7": 12, "gold": 14,
        "micro_dens": 0.5714, "sum_g": 12, "sum_k": 21,
    },
    "jilong": {
        "pool20": 4, "at4": 1, "at5": 1, "at7": 2, "gold": 13,
        "micro_dens": 0.1111, "sum_g": 1, "sum_k": 9,
    },
    "us_cn_ai": {
        "pool20": 6, "at4": 4, "at5": 4, "at7": 4, "gold": 13,
        "micro_dens": 0.4444, "sum_g": 4, "sum_k": 9,
    },
}


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R23 — 一筛补洞（专治池外金标）",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。规则优先；未调线上大模型；无案专名／无保金标 id。",
        "",
        "## vs R22（主看池20＋盒密度）",
        "",
        "| 案 | R22池20 | R23池20 | Δ池 | R22微密度 | R23微密度 | R22@7 | R23@7 | ≥2/3题 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R22[c["slug"]]
        n_ok = sum(1 for r in c["density_rows"] if r["gold_density"] + 1e-12 >= 2 / 3)
        lines.append(
            f"| {c['slug']} | {b['pool20']} | {c['pool_hits']['20']} | "
            f"{c['pool_hits']['20'] - b['pool20']:+d} | "
            f"{b['micro_dens']:.0%} | {c['micro_gold_density']:.0%} | "
            f"{b['at7']} | {c['cut_hits']['7']} | "
            f"{n_ok}/{len(c['density_rows'])} |"
        )
    lines += [
        "",
        "## 主指标：池20 与盒内密度",
        "",
        "| 案 | 池20 | 池50 | Σ金标/Σk | 微平均密度 | 达≥2/3 题 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        n_ok = sum(1 for r in c["density_rows"] if r["gold_density"] + 1e-12 >= 2 / 3)
        lines.append(
            f"| {c['slug']} | {c['pool_hits']['20']} | {c['pool_hits']['50']} | "
            f"{c['sum_gold_in_boxes']}/{c['sum_k']} | "
            f"{c['micro_gold_density']:.0%} | "
            f"{n_ok}/{len(c['density_rows'])} |"
        )
    lines += [
        "",
        "### 分题",
        "",
        "| 案 | qid | 池20金标 | route | k | 盒金标 | 密度 |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for c in report["cases"]:
        for q in c["questions"]:
            r = q["density"]
            p20 = q["pool"]["20"]["hits"]
            lines.append(
                f"| {c['slug']} | {q['qid']} | {p20}/{q['pool']['20']['gold_total']} | "
                f"{r['route']} | {r['k']} | {r['n_gold']} | {r['gold_density']:.0%} |"
            )
    lines += [
        "",
        "## 辅表：固定切点 @k",
        "",
        "| 案 | @4 | @5 | @7 | R22@7 | Δ@7 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R22[c["slug"]]
        lines.append(
            f"| {c['slug']} | {c['cut_hits']['4']} | {c['cut_hits']['5']} | "
            f"{c['cut_hits']['7']} | {b['at7']} | "
            f"{c['cut_hits']['7'] - b['at7']:+d} |"
        )
    lines += [
        "",
        "## 诊断摘要（开工前）",
        "",
        "- jilong q_001：R22 池20金标=0；金标落在经典/视图百名开外，但正文含对立时点"
        "（10时52分／8月26日）——二筛可变 k 无米下锅。",
        "- 补洞杠杆：问句时点展开＋主张短锚打分，保池头注入高分池外段；近同文一并补入。",
        "",
        "## 改动要点",
        "",
        "1. **`stage1_claim_holes`**：时点展开（至区间拆子串）、对立短锚／软锚打分、证据词加成。",
        "2. **安全注入**：保留 pool 头 10；高主张分池外段注入中段；近同文兄弟补入。",
        "3. **只动 `pool_ranked`**：`submit_ranked` 仍纯经典，二筛／R22 密度路径不动。",
        "4. 冻结沿用 R19～R22；无案专名、无保金标 id。",
        "",
        "## 剩余局限",
        "",
        "- 无钟点／弱锚题（如部分口径对立）补洞臂信号不足，池升有限。",
        "- 注入位有限；同文噪声段也可能进池，靠二筛密度约束消化。",
        "",
        "## 路径",
        "- `artifacts/R23_stage1_pool_hole.json`",
        "- `artifacts/R23_stage1_pool_hole.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    coeff, names = _coeff_names()
    cases = [
        _eval_case("liuxiang", "刘翔", coeff, names, prefer_gold=True),
        _eval_case("jilong", "吉隆", coeff, names, prefer_gold=False),
        _eval_case("us_cn_ai", "中美AI", coeff, names, prefer_gold=False),
    ]
    bullets: list[str] = []
    train = cases[0]
    bullets.append(
        f"刘翔回归：@7 **{train['cut_hits']['7']}/{train['gold_total']}**"
        f"（门槛 ≥11；R22={R22['liuxiang']['at7']}）；"
        f"池20={train['pool_hits']['20']}（R22 {R22['liuxiang']['pool20']}）；"
        f"盒微密度 **{train['micro_gold_density']:.0%}**。"
    )
    for c in cases[1:]:
        b = R22[c["slug"]]
        bullets.append(
            f"{c['slug']}：池20 **{c['pool_hits']['20']}**（R22 {b['pool20']}，"
            f"{c['pool_hits']['20'] - b['pool20']:+d}）；"
            f"盒微密度 **{c['micro_gold_density']:.0%}**"
            f"（{c['sum_gold_in_boxes']}/{c['sum_k']}，R22 {b['micro_dens']:.0%}）；"
            f"@7={c['cut_hits']['7']}（R22 {b['at7']}）。"
        )
    report = {
        "ticket": "R23-stage1-pool-hole",
        "cases": cases,
        "r22": R22,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R23_stage1_pool_hole.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R23_stage1_pool_hole.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)

    jl = next(c for c in cases if c["slug"] == "jilong")
    us = next(c for c in cases if c["slug"] == "us_cn_ai")
    pool_up = jl["pool_hits"]["20"] > R22["jilong"]["pool20"]
    dens_side = any(
        c["micro_gold_density"] + 1e-12 >= 0.5
        or any(r["gold_density"] + 1e-12 >= 2 / 3 for r in c["density_rows"])
        for c in (jl, us)
    )
    us_ok = (
        us["pool_hits"]["20"] >= R22["us_cn_ai"]["pool20"] - 1
        and us["cut_hits"]["7"] >= R22["us_cn_ai"]["at7"] - 1
        and us["micro_gold_density"] + 1e-12 >= R22["us_cn_ai"]["micro_dens"] - 0.05
    )
    liuxiang_ok = train["cut_hits"]["7"] >= 11 or train["micro_gold_density"] >= 0.5
    ok = pool_up and dens_side and us_ok and liuxiang_ok
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
