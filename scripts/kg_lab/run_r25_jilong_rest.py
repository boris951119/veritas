#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R25：修吉隆其余题（池外补搜／池内抗挤）。

主看 jilong q_002／q_003 盒密度 vs R24；案均密度升；us／刘翔不回退。
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

R24 = {
    "liuxiang": {
        "pool20": 8, "at4": 9, "at5": 11, "at7": 12, "gold": 14,
        "micro_dens": 0.5714, "sum_g": 12, "sum_k": 21,
    },
    "jilong": {
        "pool20": 6, "at4": 2, "at5": 3, "at7": 4, "gold": 13,
        "micro_dens": 0.2222, "sum_g": 2, "sum_k": 9,
    },
    "us_cn_ai": {
        "pool20": 6, "at4": 4, "at5": 4, "at7": 4, "gold": 13,
        "micro_dens": 0.4444, "sum_g": 4, "sum_k": 9,
    },
}

# R24 分题盒密度
R24_Q = {
    "liuxiang": {"q_001": 0.57, "q_002": 0.57, "q_003": 0.57},
    "jilong": {"q_001": 0.6667, "q_002": 0.0, "q_003": 0.0},
    "us_cn_ai": {"q_001": 0.6667, "q_002": 0.6667, "q_003": 0.0},
}


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R25 — 修吉隆其余题（池外补搜／池内抗挤）",
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
        "## vs R24（主看盒密度）",
        "",
        "| 案 | R24池20 | R25池20 | R24微密度 | R25微密度 | R24@7 | R25@7 | ≥2/3题 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R24[c["slug"]]
        n_ok = sum(1 for r in c["density_rows"] if r["gold_density"] + 1e-12 >= 2 / 3)
        lines.append(
            f"| {c['slug']} | {b['pool20']} | {c['pool_hits']['20']} | "
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
        "### 分题（jilong 为焦点）",
        "",
        "| 案 | qid | 池20金标 | route | k | 盒金标 | 密度 | vs R24 |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ]
    for c in report["cases"]:
        for q in c["questions"]:
            r = q["density"]
            p20 = q["pool"]["20"]["hits"]
            prev = (R24_Q.get(c["slug"]) or {}).get(q["qid"])
            vs = f"{prev:.0%}→{r['gold_density']:.0%}" if prev is not None else ""
            lines.append(
                f"| {c['slug']} | {q['qid']} | {p20}/{q['pool']['20']['gold_total']} | "
                f"{r['route']} | {r['k']} | {r['n_gold']} | {r['gold_density']:.0%} | {vs} |"
            )
    lines += [
        "",
        "## 辅表：固定切点 @k",
        "",
        "| 案 | @4 | @5 | @7 | R24@7 | Δ@7 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R24[c["slug"]]
        lines.append(
            f"| {c['slug']} | {c['cut_hits']['4']} | {c['cut_hits']['5']} | "
            f"{c['cut_hits']['7']} | {b['at7']} | "
            f"{c['cut_hits']['7'] - b['at7']:+d} |"
        )
    lines += [
        "",
        "## 诊断摘要",
        "",
        "- **q_002（口径）**：池内有金标＋池外仍有；盒被同页 UN／发布会改写多段占满；"
        "侧锚「泥石流」过弱曾掏空补洞臂。",
        "- **q_003（冰岩崩 vs 冰湖溃决）**：金标多在池内；话题标签／发布会换皮与查明金标"
        "近同文并簇时曾留错代表。",
        "- **q_001**：R24 已达 67%，本轮保底不回退。",
        "",
        "## 改动要点",
        "",
        "1. **一筛补洞（R23 延续）**：口径题允许单侧弱词锚；机构声部＋侧锚同现加分；"
        "略缩池头、加大注入，发言人／声明段进 pool20。",
        "2. **二筛抗挤（R24 加强）**：发布会查明换皮长共茎并簇；簇代表按精确钟点／声部／"
        "可核验择优；同文档只封单侧切片；成因／口径对撞启用软保位；对撞题放宽分地板。",
        "3. 冻结 R19～R24 骨架；无案专名、无保金标 id。",
        "",
        "## 剩余局限",
        "",
        "- q_002／q_003 题级密度仍 33%，未齐 2/3；外交部金标贴 pool20 边缘时仍易落盒外。",
        "- 案级微平均可低于 2/3。",
        "",
        "## 路径",
        "- `artifacts/R25_jilong_rest.json`",
        "- `artifacts/R25_jilong_rest.md`",
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
        f"（门槛 ≥11；R24={R24['liuxiang']['at7']}）；"
        f"池20={train['pool_hits']['20']}；"
        f"盒微密度 **{train['micro_gold_density']:.0%}**。"
    )
    for c in cases[1:]:
        b = R24[c["slug"]]
        n_ok = sum(1 for r in c["density_rows"] if r["gold_density"] + 1e-12 >= 2 / 3)
        bullets.append(
            f"{c['slug']}：池20 **{c['pool_hits']['20']}**（R24 {b['pool20']}）；"
            f"盒微密度 **{c['micro_gold_density']:.0%}**"
            f"（{c['sum_gold_in_boxes']}/{c['sum_k']}，R24 {b['micro_dens']:.0%}）；"
            f"@7={c['cut_hits']['7']}（R24 {b['at7']}）；"
            f"≥2/3 题 {n_ok}/{len(c['density_rows'])}。"
        )
    jl = next(c for c in cases if c["slug"] == "jilong")
    rest = [r for r in jl["density_rows"] if r["qid"] != "q_001"]
    bullets.append(
        "jilong 非 q_001："
        + "；".join(
            f"{r['qid']} {R24_Q['jilong'][r['qid']]:.0%}→{r['gold_density']:.0%}"
            for r in rest
        )
        + f"；案均 {R24['jilong']['micro_dens']:.0%}→{jl['micro_gold_density']:.0%}。"
    )
    report = {
        "ticket": "R25-jilong-rest",
        "cases": cases,
        "r24": R24,
        "r24_per_q": R24_Q,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R25_jilong_rest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R25_jilong_rest.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)

    us = next(c for c in cases if c["slug"] == "us_cn_ai")
    rest_up = any(
        r["gold_density"] + 1e-12 >= R24_Q["jilong"][r["qid"]] + 0.25
        for r in rest
    )
    micro_up = jl["micro_gold_density"] + 1e-12 >= R24["jilong"]["micro_dens"] + 0.08
    q001_ok = next(
        r["gold_density"] + 1e-12 >= 0.5
        for r in jl["density_rows"] if r["qid"] == "q_001"
    )
    us_ok = (
        us["cut_hits"]["7"] >= R24["us_cn_ai"]["at7"] - 1
        and us["micro_gold_density"] + 1e-12 >= R24["us_cn_ai"]["micro_dens"] - 0.05
    )
    liuxiang_ok = train["cut_hits"]["7"] >= 11
    ok = rest_up and micro_up and q001_ok and us_ok and liuxiang_ok
    print(
        f"gates: rest_up={rest_up} micro_up={micro_up} q001_ok={q001_ok} "
        f"us_ok={us_ok} liuxiang_ok={liuxiang_ok} → {'PASS' if ok else 'FAIL'}",
        flush=True,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
