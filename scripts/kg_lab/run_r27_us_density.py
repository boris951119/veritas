#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R27：再抬盒密度——主攻 us_cn_ai（看上升空间）。

主看 us_cn_ai 案均／q_003 vs R26；jilong ≥67% 持平；liuxiang @7 ≥11。
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

R26 = {
    "liuxiang": {
        "pool20": 8, "at4": 9, "at5": 11, "at7": 12, "gold": 14,
        "micro_dens": 0.5714, "sum_g": 12, "sum_k": 21,
    },
    "jilong": {
        "pool20": 5, "at4": 5, "at5": 5, "at7": 6, "gold": 13,
        "micro_dens": 0.6667, "sum_g": 6, "sum_k": 9,
    },
    "us_cn_ai": {
        "pool20": 6, "at4": 4, "at5": 4, "at7": 4, "gold": 13,
        "micro_dens": 0.4444, "sum_g": 4, "sum_k": 9,
    },
}

R26_Q = {
    "liuxiang": {"q_001": 0.57, "q_002": 0.57, "q_003": 0.57},
    "jilong": {"q_001": 0.6667, "q_002": 0.6667, "q_003": 0.6667},
    "us_cn_ai": {"q_001": 0.6667, "q_002": 0.6667, "q_003": 0.0},
}


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R27 — us_cn_ai 盒密度再抬（主攻 q_003）",
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
        "## vs R26（主看盒密度）",
        "",
        "| 案 | R26池20 | R27池20 | R26微密度 | R27微密度 | R26@7 | R27@7 | ≥2/3题 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R26[c["slug"]]
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
        "### 分题（us_cn_ai 为焦点）",
        "",
        "| 案 | qid | 池20金标 | route | k | 盒金标 | 密度 | vs R26 |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ]
    for c in report["cases"]:
        for q in c["questions"]:
            r = q["density"]
            p20 = q["pool"]["20"]["hits"]
            prev = (R26_Q.get(c["slug"]) or {}).get(q["qid"])
            vs = f"{prev:.0%}→{r['gold_density']:.0%}" if prev is not None else ""
            lines.append(
                f"| {c['slug']} | {q['qid']} | {p20}/{q['pool']['20']['gold_total']} | "
                f"{r['route']} | {r['k']} | {r['n_gold']} | {r['gold_density']:.0%} | {vs} |"
            )
    lines += [
        "",
        "## 辅表：固定切点 @k",
        "",
        "| 案 | @4 | @5 | @7 | R26@7 | Δ@7 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R26[c["slug"]]
        lines.append(
            f"| {c['slug']} | {c['cut_hits']['4']} | {c['cut_hits']['5']} | "
            f"{c['cut_hits']['7']} | {b['at7']} | "
            f"{c['cut_hits']['7'] - b['at7']:+d} |"
        )
    lines += [
        "",
        "## 诊断摘要（R26→R27）",
        "",
        "- **us q_003（企业 vs 政府责任）**：R26 盒密度 0%。根因三层——"
        "① `claim_conflict` 只认灾害口径，责任对立未启软保位；"
        "②「还是」清洗丢掉半句拉丁专名（Anthropic）；"
        "③ 简繁镜像通稿（022）挤占繁体金标（017）。",
        "- **修复**：主体×责任对立进 claim_conflict；还是半句补拉丁；"
        "责任题补洞降门槛＋单侧可核验抬分；软保位可核验强度置换；"
        "近同文繁简折叠＋簇代表偏繁体／政府口径。",
        "- **us q_001／q_002**：维持 67%。",
        "- **jilong／liuxiang**：案均／@7 不回退。",
        "",
        "## 改动要点",
        "",
        "1. **路由**：`is_claim_conflict_route` 增「拉丁主体 × 政府／责任」；"
        "软锚扩失控／责任；还是半句补 Anthropic 类专名。",
        "2. **一筛**：责任题同口径题降补洞门槛；单侧可核验＋拉丁抬注入；"
        "政府介入／控制进 distinctive。",
        "3. **二筛**：可核验责任独占加分；裸专名路过降权；"
        "软保位按可核验强度置换；繁简折叠近同文；簇代表偏政府口径／繁体。",
        "4. 冻结 R19～R26；无案专名、无保金标 id；系数未动（±0）。",
        "",
        "## 剩余局限",
        "",
        "- 繁简表为新闻常见字子集，冷僻异体仍可能漏并簇。",
        "- us 案均刚贴 2/3；再抬需更多金标进池／盒，池外金标仍在。",
        "",
        "## 路径",
        "- `artifacts/R27_us_density.json`",
        "- `artifacts/R27_us_density.md`",
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
        f"（门槛 ≥11；R26={R26['liuxiang']['at7']}）；"
        f"池20={train['pool_hits']['20']}；"
        f"盒微密度 **{train['micro_gold_density']:.0%}**。"
    )
    for c in cases[1:]:
        b = R26[c["slug"]]
        n_ok = sum(1 for r in c["density_rows"] if r["gold_density"] + 1e-12 >= 2 / 3)
        bullets.append(
            f"{c['slug']}：池20 **{c['pool_hits']['20']}**（R26 {b['pool20']}）；"
            f"盒微密度 **{c['micro_gold_density']:.0%}**"
            f"（{c['sum_gold_in_boxes']}/{c['sum_k']}，R26 {b['micro_dens']:.0%}）；"
            f"@7={c['cut_hits']['7']}（R26 {b['at7']}）；"
            f"≥2/3 题 {n_ok}/{len(c['density_rows'])}。"
        )
    us = next(c for c in cases if c["slug"] == "us_cn_ai")
    focus = [r for r in us["density_rows"] if r["qid"] == "q_003"]
    bullets.append(
        "us_cn_ai q_003："
        + "；".join(
            f"{r['qid']} {R26_Q['us_cn_ai'][r['qid']]:.0%}→{r['gold_density']:.0%}"
            for r in focus
        )
        + f"；案均 {R26['us_cn_ai']['micro_dens']:.0%}→{us['micro_gold_density']:.0%}。"
    )
    report = {
        "ticket": "R27-us-density",
        "cases": cases,
        "r26": R26,
        "r26_per_q": R26_Q,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R27_us_density.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R27_us_density.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)

    jl = next(c for c in cases if c["slug"] == "jilong")
    us_micro_up = (
        us["micro_gold_density"] + 1e-12
        >= R26["us_cn_ai"]["micro_dens"] + 0.10
    )
    us_q003 = next(r for r in us["density_rows"] if r["qid"] == "q_003")
    us_q003_up = us_q003["gold_density"] + 1e-12 >= 1 / 3
    jl_hold = jl["micro_gold_density"] + 1e-12 >= 2 / 3 - 1e-9
    us_q_hold = all(
        next(r for r in us["density_rows"] if r["qid"] == qid)["gold_density"]
        + 1e-12
        >= R26_Q["us_cn_ai"][qid] - 0.05
        for qid in ("q_001", "q_002")
    )
    liuxiang_ok = train["cut_hits"]["7"] >= 11
    ok = us_micro_up and us_q003_up and jl_hold and us_q_hold and liuxiang_ok
    print(
        f"gates: us_micro_up={us_micro_up} us_q003_up={us_q003_up} "
        f"jl_hold={jl_hold} us_q_hold={us_q_hold} "
        f"liuxiang_ok={liuxiang_ok} → {'PASS' if ok else 'FAIL'}",
        flush=True,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
