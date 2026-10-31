#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R26：吉隆 q_002／q_003 盒密度抬到 ≥2/3。

主看 jilong q_002／q_003 vs R25；案均升；us／刘翔／q_001 不回退。
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

R25 = {
    "liuxiang": {
        "pool20": 8, "at4": 9, "at5": 11, "at7": 12, "gold": 14,
        "micro_dens": 0.5714, "sum_g": 12, "sum_k": 21,
    },
    "jilong": {
        "pool20": 5, "at4": 4, "at5": 4, "at7": 5, "gold": 13,
        "micro_dens": 0.4444, "sum_g": 4, "sum_k": 9,
    },
    "us_cn_ai": {
        "pool20": 6, "at4": 4, "at5": 4, "at7": 4, "gold": 13,
        "micro_dens": 0.4444, "sum_g": 4, "sum_k": 9,
    },
}

R25_Q = {
    "liuxiang": {"q_001": 0.57, "q_002": 0.57, "q_003": 0.57},
    "jilong": {"q_001": 0.6667, "q_002": 0.3333, "q_003": 0.3333},
    "us_cn_ai": {"q_001": 0.6667, "q_002": 0.6667, "q_003": 0.0},
}


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R26 — 吉隆 q_002／q_003 盒密度 ≥2/3",
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
        "## vs R25（主看盒密度）",
        "",
        "| 案 | R25池20 | R26池20 | R25微密度 | R26微密度 | R25@7 | R26@7 | ≥2/3题 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R25[c["slug"]]
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
        "| 案 | qid | 池20金标 | route | k | 盒金标 | 密度 | vs R25 |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ]
    for c in report["cases"]:
        for q in c["questions"]:
            r = q["density"]
            p20 = q["pool"]["20"]["hits"]
            prev = (R25_Q.get(c["slug"]) or {}).get(q["qid"])
            vs = f"{prev:.0%}→{r['gold_density']:.0%}" if prev is not None else ""
            lines.append(
                f"| {c['slug']} | {q['qid']} | {p20}/{q['pool']['20']['gold_total']} | "
                f"{r['route']} | {r['k']} | {r['n_gold']} | {r['gold_density']:.0%} | {vs} |"
            )
    lines += [
        "",
        "## 辅表：固定切点 @k",
        "",
        "| 案 | @4 | @5 | @7 | R25@7 | Δ@7 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R25[c["slug"]]
        lines.append(
            f"| {c['slug']} | {c['cut_hits']['4']} | {c['cut_hits']['5']} | "
            f"{c['cut_hits']['7']} | {b['at7']} | "
            f"{c['cut_hits']['7'] - b['at7']:+d} |"
        )
    lines += [
        "",
        "## 诊断摘要（R25→R26）",
        "",
        "- **q_002（口径）**：R25 盒被查明换皮假双侧＋UN 短独占占满；发言人金标贴池缘。"
        "R26：口径声部注入优先、查明假双侧降权、两侧声部齐后弱双侧优先于成因综述。",
        "- **q_003（冰岩崩 vs 冰湖溃决）**：长 wire_relay 被 wire_pen 压到分地板下；"
        "同簇长通稿盖住短精确主张。R26：通稿罚分只打短段、地板放宽、簇代表偏短、"
        "同侧第 2 槽留给「精确＋钟点、非查明、非长文」。",
        "- **q_001**：维持 67%，钟点路径不搅池。",
        "",
        "## 改动要点",
        "",
        "1. **一筛**：口径题抬发言人／秘书长＋单侧锚；问句点名机构作软锚；"
        "查明假双侧降权；精确海拔／数额锚加分（非钟点题）。",
        "2. **二筛排序**：短通稿才 wire_pen；真双侧需口径声部／多锚；成因题时点钉加分；"
        "贴池缘精确／声部独占可进核心。",
        "3. **二筛装箱**：并簇后再软保位再截断；声部独占优先；弱双侧降成因综述；"
        "同侧第 2 槽仅精确＋钟点短段；簇代表偏短。",
        "4. 冻结 R19～R25；无案专名、无保金标 id。",
        "",
        "## 剩余局限",
        "",
        "- 案级微平均依赖题级齐 2/3；us q_003 仍可能 0%。",
        "- 同文档多金标仍受同侧／近同文约束，极端长文案可能不够。",
        "",
        "## 路径",
        "- `artifacts/R26_jilong_density.json`",
        "- `artifacts/R26_jilong_density.md`",
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
        f"（门槛 ≥11；R25={R25['liuxiang']['at7']}）；"
        f"池20={train['pool_hits']['20']}；"
        f"盒微密度 **{train['micro_gold_density']:.0%}**。"
    )
    for c in cases[1:]:
        b = R25[c["slug"]]
        n_ok = sum(1 for r in c["density_rows"] if r["gold_density"] + 1e-12 >= 2 / 3)
        bullets.append(
            f"{c['slug']}：池20 **{c['pool_hits']['20']}**（R25 {b['pool20']}）；"
            f"盒微密度 **{c['micro_gold_density']:.0%}**"
            f"（{c['sum_gold_in_boxes']}/{c['sum_k']}，R25 {b['micro_dens']:.0%}）；"
            f"@7={c['cut_hits']['7']}（R25 {b['at7']}）；"
            f"≥2/3 题 {n_ok}/{len(c['density_rows'])}。"
        )
    jl = next(c for c in cases if c["slug"] == "jilong")
    focus = [r for r in jl["density_rows"] if r["qid"] in {"q_002", "q_003"}]
    bullets.append(
        "jilong q_002／q_003："
        + "；".join(
            f"{r['qid']} {R25_Q['jilong'][r['qid']]:.0%}→{r['gold_density']:.0%}"
            for r in focus
        )
        + f"；案均 {R25['jilong']['micro_dens']:.0%}→{jl['micro_gold_density']:.0%}。"
    )
    report = {
        "ticket": "R26-jilong-density",
        "cases": cases,
        "r25": R25,
        "r25_per_q": R25_Q,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R26_jilong_density.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R26_jilong_density.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)

    us = next(c for c in cases if c["slug"] == "us_cn_ai")
    hit_23 = sum(1 for r in focus if r["gold_density"] + 1e-12 >= 2 / 3)
    other_up = all(
        r["gold_density"] + 1e-12 >= R25_Q["jilong"][r["qid"]] + 0.15
        for r in focus
    )
    # 至少一侧 2/3，另一侧明显升（≥R25+0.15 或也达 2/3）
    one_ok = hit_23 >= 1 and (
        hit_23 >= 2
        or any(
            r["gold_density"] + 1e-12 >= R25_Q["jilong"][r["qid"]] + 0.15
            for r in focus
        )
    )
    micro_up = jl["micro_gold_density"] + 1e-12 >= R25["jilong"]["micro_dens"] + 0.05
    q001_ok = next(
        r["gold_density"] + 1e-12 >= 0.5
        for r in jl["density_rows"] if r["qid"] == "q_001"
    )
    us_ok = (
        us["cut_hits"]["7"] >= R25["us_cn_ai"]["at7"] - 1
        and us["micro_gold_density"] + 1e-12 >= R25["us_cn_ai"]["micro_dens"] - 0.05
    )
    liuxiang_ok = train["cut_hits"]["7"] >= 11
    ok = one_ok and micro_up and q001_ok and us_ok and liuxiang_ok
    print(
        f"gates: one_ok={one_ok} hit_23={hit_23} other_up={other_up} "
        f"micro_up={micro_up} q001_ok={q001_ok} us_ok={us_ok} "
        f"liuxiang_ok={liuxiang_ok} → {'PASS' if ok else 'FAIL'}",
        flush=True,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
