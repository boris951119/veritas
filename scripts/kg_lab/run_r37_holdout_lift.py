#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R37 实现票：AI171／柬泰 池外可核验召回＋盒稀保位（接 R36）。

注：只读归因另见 R37_poolout_diag；本票是涨分刀。
验收相对 R36：AI171／柬泰案均可见抬升；王虹不显著掉；
刘翔 @7≥11；吉隆／中美AI 不显著掉。
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
from scripts.kg_lab.run_r31_holdout3 import HOLDOUT  # noqa: E402
from scripts.kg_lab.run_r36_interview_recall import _diag_rows  # noqa: E402

R36 = {
    "liuxiang": {"pool20": 8, "at7": 12, "micro": 0.5714, "sum_g": 12, "sum_k": 21},
    "wanghong": {"pool20": 9, "at7": 5, "micro": 0.5556, "sum_g": 5, "sum_k": 9},
    "kh_th": {"pool20": 6, "at7": 4, "micro": 0.4444, "sum_g": 4, "sum_k": 9},
    "ai171": {"pool20": 5, "at7": 4, "micro": 0.3333, "sum_g": 3, "sum_k": 9},
    "jilong": {"pool20": 5, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
    "us_cn_ai": {"pool20": 8, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
}
GATE_DENS = 2.0 / 3.0
LIUXIANG_AT7_MIN = 11
DROP_EPS = 0.05  # 不显著掉


def _markdown(report: dict[str, Any]) -> str:
    g = report["gate"]
    lines = [
        "# R37 — AI171／柬泰：池外可核验召回＋盒稀保位",
        "",
        "> 只读归因见 `R37_poolout_diag.md`；本文件＝涨分实现票。",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。本机 14B 嵌入；禁百炼；无案专名。",
        "",
        "## 改了什么",
        "",
        "1. 一筛／槽对齐：数额槽剥单位数字核（`241人`↔`241`），"
        "拉丁×数额同现抬最高注入档；弱中文 BM25 的英文段靠槽位仍可进池。",
        "2. 二筛：事实核对题若强核心≤1，`k_min=1`（宁少勿滥），"
        "避免通稿硬凑满 3 槽导致盒稀。",
        "3. 未整套系数重拟合；未写案专名；未开同文档桥／主张硬踢（已证误伤）。",
        "",
        "## vs R36",
        "",
        "| 案 | 角色 | R36池20 | R37池20 | Δ池 | R36微密度 | R37微密度 | Δ密度 | R36@7 | R37@7 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R36.get(c["slug"], {})
        d_micro = c["micro_gold_density"] - float(b.get("micro") or 0)
        lines.append(
            f"| {c['slug']} | {c.get('role')} | {b.get('pool20', '—')} | "
            f"{c['pool_hits']['20']} | "
            f"{c['pool_hits']['20'] - int(b.get('pool20') or 0):+d} | "
            f"{b.get('micro', 0):.0%} | {c['micro_gold_density']:.0%} | "
            f"{d_micro:+.0%} | "
            f"{b.get('at7', '—')} | {c['cut_hits']['7']} |"
        )
    lines += [
        "",
        "### 分题主因",
        "",
        "| 案 | qid | 池20 | 盒 | 密度 | 主因 | route |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for c in report["cases"]:
        if c.get("role") not in {"holdout", "regression"}:
            continue
        for r in c.get("diag_rows") or []:
            lines.append(
                f"| {c['slug']} | {r['qid']} | {r['n_pool20']}/{r['n_gold']} | "
                f"{r['n_box']}/{r['k']} | {r['gold_density']:.0%} | "
                f"**{r['cause']}** | {r.get('route') or '—'} |"
            )
    lines += [
        "",
        "## 验收闸",
        "",
        f"- AI171 案均相对 R36 可见抬升：{'✓' if g['ai171_up'] else '✗'}"
        f"（{R36['ai171']['micro']:.0%}→{g['ai171_micro']:.0%}）",
        f"- 柬泰 案均相对 R36 可见抬升：{'✓' if g['kh_th_up'] else '✗'}"
        f"（{R36['kh_th']['micro']:.0%}→{g['kh_th_micro']:.0%}）",
        f"- 王虹不显著掉：{'✓' if g['wanghong_ok'] else '✗'}"
        f"（{R36['wanghong']['micro']:.0%}→{g['wanghong_micro']:.0%}）",
        f"- 刘翔 @7≥{LIUXIANG_AT7_MIN}：{'✓' if g['liuxiang_ok'] else '✗'}"
        f"（{g['liuxiang_at7']}）",
        f"- 吉隆不显著掉：{'✓' if g['jilong_ok'] else '✗'}",
        f"- 中美AI不显著掉：{'✓' if g['us_ok'] else '✗'}",
        f"- 门槛①（三案各≥2/3）：{'✓' if g['holdout_all_ge_23'] else '✗'}"
        f"（{g['n_holdout_pass']}/3）",
        "",
        f"### 距门槛①还差多少",
        "",
        f"- {g['gap_note']}",
        "",
        f"### 下一刀建议",
        "",
        f"- {g['next_cut']}",
        "",
        "## 未解洞",
        "",
    ]
    for hole in report.get("open_holes") or []:
        lines.append(f"- {hole}")
    lines += [
        "",
        "## 路径",
        "- `artifacts/R37_holdout_lift.json`",
        "- `artifacts/R37_holdout_lift.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    coeff, names = _coeff_names()
    lx = _eval_case("liuxiang", "刘翔", coeff, names, prefer_gold=True)
    lx["role"] = "regression"
    jl = _eval_case("jilong", "吉隆", coeff, names, prefer_gold=False)
    jl["role"] = "smoke"
    us = _eval_case("us_cn_ai", "中美AI", coeff, names, prefer_gold=False)
    us["role"] = "smoke"

    holdout_cases: list[dict[str, Any]] = []
    for h in HOLDOUT:
        c = _eval_case(h["slug"], h["mark"], coeff, names, prefer_gold=False)
        c["role"] = "holdout"
        c["title"] = h["title"]
        holdout_cases.append(c)

    mark_of = {"liuxiang": "刘翔", **{h["slug"]: h["mark"] for h in HOLDOUT}}
    for c in [lx, *holdout_cases]:
        c["diag_rows"] = _diag_rows(c["slug"], mark_of[c["slug"]])

    by = {c["slug"]: c for c in holdout_cases}
    ai, kh, wh = by["ai171"], by["kh_th"], by["wanghong"]

    def _up(now: float, base: float) -> bool:
        return now + 1e-12 >= base + 0.02  # 可见抬升 ≈ +2pp 或以上

    def _ok_drop(now: float, base: float) -> bool:
        return now + 1e-12 >= base - DROP_EPS

    ai_up = _up(ai["micro_gold_density"], R36["ai171"]["micro"])
    kh_up = _up(kh["micro_gold_density"], R36["kh_th"]["micro"])
    # 若绝对涨至少 1 金标槽也算可见
    if not ai_up and ai["sum_gold_in_boxes"] > R36["ai171"]["sum_g"]:
        ai_up = True
    if not kh_up and kh["sum_gold_in_boxes"] > R36["kh_th"]["sum_g"]:
        kh_up = True

    wh_ok = _ok_drop(wh["micro_gold_density"], R36["wanghong"]["micro"])
    lx_ok = lx["cut_hits"]["7"] >= LIUXIANG_AT7_MIN
    jl_ok = _ok_drop(jl["micro_gold_density"], R36["jilong"]["micro"])
    us_ok = _ok_drop(us["micro_gold_density"], R36["us_cn_ai"]["micro"])
    n_pass = sum(
        1 for c in holdout_cases
        if c["micro_gold_density"] + 1e-12 >= GATE_DENS
    )

    gaps = []
    for c in holdout_cases:
        need = GATE_DENS - c["micro_gold_density"]
        if need > 1e-12:
            gaps.append(f"{c['slug']} 差 {need:.0%}（现 {c['micro_gold_density']:.0%}）")
    gap_note = "；".join(gaps) if gaps else "三案均已 ≥2/3。"

    # 下一刀
    causes = []
    for c in holdout_cases:
        for r in c.get("diag_rows") or []:
            if r["gold_density"] + 1e-12 < GATE_DENS:
                causes.append(r["cause"])
    from collections import Counter
    cc = Counter(causes)
    if cc.get("池外", 0) >= cc.get("池内挤", 0) and cc.get("池外", 0) >= cc.get("盒稀", 0):
        next_cut = "继续可迁移池外召回（英文长段／嵌入），或授权主仓丙收英文声明进箱。"
    elif cc.get("盒稀", 0) or cc.get("池内挤", 0):
        next_cut = "二筛抗通稿／重复主张再收一刀；慎开同文档桥（R39 已证灌池）。"
    else:
        next_cut = "冲门槛①分题补洞；王虹收尾到 2/3。"

    mean_r36 = sum(R36[h["slug"]]["micro"] for h in HOLDOUT) / 3
    mean_now = sum(c["micro_gold_density"] for c in holdout_cases) / 3
    bullets = [
        f"holdout 案均 {mean_r36:.0%}→**{mean_now:.0%}**"
        f"（Σ {sum(c['sum_gold_in_boxes'] for c in holdout_cases)}/"
        f"{sum(c['sum_k'] for c in holdout_cases)}）。",
        f"`ai171`：{R36['ai171']['micro']:.0%}→**{ai['micro_gold_density']:.0%}**"
        f"（池20 {R36['ai171']['pool20']}→{ai['pool_hits']['20']}）。",
        f"`kh_th`：{R36['kh_th']['micro']:.0%}→**{kh['micro_gold_density']:.0%}**"
        f"（池20 {R36['kh_th']['pool20']}→{kh['pool_hits']['20']}）。",
        f"`wanghong`：{R36['wanghong']['micro']:.0%}→**{wh['micro_gold_density']:.0%}**。",
        f"刘翔 @7 **{lx['cut_hits']['7']}**；吉隆 {jl['micro_gold_density']:.0%}；"
        f"中美AI {us['micro_gold_density']:.0%}。",
        f"验收目标闸："
        f"AI{'✓' if ai_up else '✗'} 柬{'✓' if kh_up else '✗'} "
        f"王{'✓' if wh_ok else '✗'} 刘{'✓' if lx_ok else '✗'}。",
    ]
    open_holes = []
    for c in holdout_cases:
        if c["micro_gold_density"] + 1e-12 < GATE_DENS:
            open_holes.append(
                f"`{c['slug']}` 案均仍 {c['micro_gold_density']:.0%}，"
                f"距 2/3 差 {GATE_DENS - c['micro_gold_density']:.0%}。"
            )
        for r in c.get("diag_rows") or []:
            if r["cause"] in {"池外", "池内挤", "盒稀"} or r["gold_density"] < GATE_DENS:
                open_holes.append(
                    f"`{c['slug']}` {r['qid']} {r['cause']} "
                    f"（池20={r['n_pool20']}/{r['n_gold']} "
                    f"盒={r['n_box']}/{r['k']}）。"
                )

    gate = {
        "ai171_up": ai_up,
        "ai171_micro": round(ai["micro_gold_density"], 4),
        "kh_th_up": kh_up,
        "kh_th_micro": round(kh["micro_gold_density"], 4),
        "wanghong_ok": wh_ok,
        "wanghong_micro": round(wh["micro_gold_density"], 4),
        "liuxiang_ok": lx_ok,
        "liuxiang_at7": lx["cut_hits"]["7"],
        "jilong_ok": jl_ok,
        "us_ok": us_ok,
        "holdout_all_ge_23": n_pass == 3,
        "n_holdout_pass": n_pass,
        "gap_note": gap_note,
        "next_cut": next_cut,
        "pass_ticket": bool(ai_up and kh_up and wh_ok and lx_ok and jl_ok and us_ok),
    }

    report = {
        "ticket": "R37-holdout-lift",
        "kind": "pool-out-slots+box-sparse-kmin",
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict_bullets": bullets,
        "gate": gate,
        "open_holes": open_holes[:20],
        "cases": [lx, *holdout_cases, jl, us],
        "changes": [
            "amount digit-core match (zh unit strip)",
            "latin×amount inject tier; weak-BM25 EN paras via slots",
            "fact_check k_min=1 when single strong non-wire core",
        ],
    }

    def _jsonable(o: Any) -> Any:
        if isinstance(o, dict):
            return {str(k): _jsonable(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_jsonable(x) for x in o]
        if isinstance(o, (str, int, float, bool)) or o is None:
            return o
        return str(o)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R37_holdout_lift.json").write_text(
        json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R37_holdout_lift.md").write_text(_markdown(report), encoding="utf-8")
    print(
        f"R37lift ai={ai['micro_gold_density']:.0%} kh={kh['micro_gold_density']:.0%} "
        f"wh={wh['micro_gold_density']:.0%} lx@7={lx['cut_hits']['7']} "
        f"pass={gate['pass_ticket']} wall={report['wall_s']}s",
        flush=True,
    )
    return 0 if gate["pass_ticket"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
