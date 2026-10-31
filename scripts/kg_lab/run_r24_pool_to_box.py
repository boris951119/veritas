#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R24：池内金标进盒（二筛抗通稿挤占）。

主看盒密度 vs R23；冻结一筛／角色／意图路由／可变 k 框架。
刘翔回归 @7≥11；us_cn_ai 不掉；jilong 至少一侧逼近／达到 2/3。
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

# R23 基线（池20／切点／盒微密度）
R23 = {
    "liuxiang": {
        "pool20": 8, "at4": 9, "at5": 11, "at7": 12, "gold": 14,
        "micro_dens": 0.5714, "sum_g": 12, "sum_k": 21,
    },
    "jilong": {
        "pool20": 6, "at4": 1, "at5": 1, "at7": 3, "gold": 13,
        "micro_dens": 0.1111, "sum_g": 1, "sum_k": 9,
    },
    "us_cn_ai": {
        "pool20": 6, "at4": 4, "at5": 4, "at7": 4, "gold": 13,
        "micro_dens": 0.4444, "sum_g": 4, "sum_k": 9,
    },
}


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R24 — 池内金标进盒（二筛抗通稿挤占）",
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
        "## vs R23（主看盒密度）",
        "",
        "| 案 | R23池20 | R24池20 | R23微密度 | R24微密度 | R23@7 | R24@7 | ≥2/3题 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R23[c["slug"]]
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
        "### 分题",
        "",
        "| 案 | qid | 池20金标 | route | k | 盒金标 | 密度 | vs R23 |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ]
    r23_q = report.get("r23_per_q") or {}
    for c in report["cases"]:
        for q in c["questions"]:
            r = q["density"]
            p20 = q["pool"]["20"]["hits"]
            prev = (r23_q.get(c["slug"]) or {}).get(q["qid"])
            vs = ""
            if prev is not None:
                vs = f"{prev:.0%}→{r['gold_density']:.0%}"
            lines.append(
                f"| {c['slug']} | {q['qid']} | {p20}/{q['pool']['20']['gold_total']} | "
                f"{r['route']} | {r['k']} | {r['n_gold']} | {r['gold_density']:.0%} | {vs} |"
            )
    lines += [
        "",
        "## 辅表：固定切点 @k",
        "",
        "| 案 | @4 | @5 | @7 | R23@7 | Δ@7 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R23[c["slug"]]
        lines.append(
            f"| {c['slug']} | {c['cut_hits']['4']} | {c['cut_hits']['5']} | "
            f"{c['cut_hits']['7']} | {b['at7']} | "
            f"{c['cut_hits']['7'] - b['at7']:+d} |"
        )
    lines += [
        "",
        "## 诊断摘要（开工前）",
        "",
        "- jilong q_001：R23 池内已有金标（p21／p237），但盒被"
        "「8月26日10时30分许…」单侧通稿近同文占满（三槽全 option_a 镜像），密度 0%。",
        "- 根因：精确指纹去重咬不住通稿改写；`59分` 弱锚把「10时59分」误判成双侧；"
        "长段共引查明句若宽阈值并簇会互挤金标。",
        "",
        "## 改动要点",
        "",
        "1. **通稿／近同文簇**：短通报宽并簇留代表；长段仅高 Jaccard 并（防金标互挤）。",
        "2. **钟点对撞题软保位**：双侧主张段优先于单侧通稿；同侧独占至多 1；"
        "无侧权威段不抢核心槽（仅含钟点锚的裁决题启用，避免伤 us_cn_ai）。",
        "3. **核心分**：钟点路由下抬句首钟点／真双侧、降短通稿与长文综述埋钟点；"
        "过滤 `N分` 残片误命中。",
        "4. 冻结 R19～R23 一筛／角色／意图路由／可变 k；无案专名、无保金标 id。",
        "",
        "## 剩余局限",
        "",
        "- 无钟点对立题（口径／制度）仍主要靠 R22 密度路径，通稿簇收益有限。",
        "- jilong 非时点题盒密度仍低；案级微平均可低于 2/3。",
        "",
        "## 路径",
        "- `artifacts/R24_pool_to_box.json`",
        "- `artifacts/R24_pool_to_box.md`",
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
    # R23 分题密度（对照）
    r23_per_q = {
        "liuxiang": {"q_001": 0.57, "q_002": 0.57, "q_003": 0.57},
        "jilong": {"q_001": 0.0, "q_002": 0.0, "q_003": 0.3333},
        "us_cn_ai": {"q_001": 0.6667, "q_002": 0.6667, "q_003": 0.0},
    }
    bullets: list[str] = []
    train = cases[0]
    bullets.append(
        f"刘翔回归：@7 **{train['cut_hits']['7']}/{train['gold_total']}**"
        f"（门槛 ≥11；R23={R23['liuxiang']['at7']}）；"
        f"池20={train['pool_hits']['20']}；"
        f"盒微密度 **{train['micro_gold_density']:.0%}**。"
    )
    for c in cases[1:]:
        b = R23[c["slug"]]
        n_ok = sum(1 for r in c["density_rows"] if r["gold_density"] + 1e-12 >= 2 / 3)
        bullets.append(
            f"{c['slug']}：池20 **{c['pool_hits']['20']}**（R23 {b['pool20']}）；"
            f"盒微密度 **{c['micro_gold_density']:.0%}**"
            f"（{c['sum_gold_in_boxes']}/{c['sum_k']}，R23 {b['micro_dens']:.0%}）；"
            f"@7={c['cut_hits']['7']}（R23 {b['at7']}）；"
            f"≥2/3 题 {n_ok}/{len(c['density_rows'])}。"
        )
    report = {
        "ticket": "R24-pool-to-box",
        "cases": cases,
        "r23": R23,
        "r23_per_q": r23_per_q,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R24_pool_to_box.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R24_pool_to_box.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)

    jl = next(c for c in cases if c["slug"] == "jilong")
    us = next(c for c in cases if c["slug"] == "us_cn_ai")
    jl_side = any(r["gold_density"] + 1e-12 >= 2 / 3 for r in jl["density_rows"]) or (
        jl["micro_gold_density"] + 1e-12 >= R23["jilong"]["micro_dens"] + 0.08
    )
    us_ok = (
        us["pool_hits"]["20"] >= R23["us_cn_ai"]["pool20"] - 1
        and us["cut_hits"]["7"] >= R23["us_cn_ai"]["at7"] - 1
        and us["micro_gold_density"] + 1e-12 >= R23["us_cn_ai"]["micro_dens"] - 0.05
    )
    liuxiang_ok = train["cut_hits"]["7"] >= 11
    ok = jl_side and us_ok and liuxiang_ok
    print(
        f"gates: jilong_side={jl_side} us_ok={us_ok} liuxiang_ok={liuxiang_ok} → "
        f"{'PASS' if ok else 'FAIL'}",
        flush=True,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
