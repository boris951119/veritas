#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R40：holdout 三案齐抬 ~10pp 冲 ≥2/3（禁盲扩一筛）。

接 R39。验收：王虹／柬泰／AI171 尽量各 ≥2/3；刘翔＋吉隆／中美AI 不显著掉。
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

# R39 结论文本基线
R39 = {
    "liuxiang": {"pool20": 8, "at7": 12, "micro": 0.5714, "sum_g": 12, "sum_k": 21},
    "wanghong": {"pool20": 9, "at7": 5, "micro": 0.5556, "sum_g": 5, "sum_k": 9},
    "kh_th": {"pool20": 6, "at7": 4, "micro": 0.5714, "sum_g": 4, "sum_k": 7},
    "ai171": {"pool20": 6, "at7": 6, "micro": 0.5714, "sum_g": 4, "sum_k": 7},
    "jilong": {"pool20": 5, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
    "us_cn_ai": {"pool20": 8, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
}
GATE_DENS = 2.0 / 3.0
LIUXIANG_AT7_MIN = 11
DROP_EPS = 0.05


def _markdown(report: dict[str, Any]) -> str:
    g = report["gate"]
    lines = [
        "# R40 — holdout 三案齐抬冲 ≥2/3（禁盲扩一筛）",
        "",
        "> 接 R39；按题诊断池外 vs 池内挤；可变 k／同簇代表／澄清·一手·数额钉保位。",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。本机嵌入；禁百炼；无案专名。",
        "",
        "## 改了什么",
        "",
        "1. 钟点×战机同簇：句首钟点代表优先；仅剩 1 枚 `clock_strike` 时缩 k（柬泰盒稀）。",
        "2. 澄清题：澄清／原院长抬，有消息称复述降；一手出处／官方视频相对汇总多方抬。",
        "3. 拉丁×数额裁决：槽抬＋英文数额声明保位进盒（AI171 死亡人数题）。",
        "4. 可变 k：澄清／一手／数额包仅 1 枚钉时宁缺毋滥；不盲扩一筛。",
        "",
        "## vs R39",
        "",
        "| 案 | 角色 | R39池20 | R40池20 | Δ池 | R39微密度 | R40微密度 | Δ密度 | R39@7 | R40@7 | ≥2/3 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for c in report["cases"]:
        b = R39.get(c["slug"], {})
        d_micro = c["micro_gold_density"] - float(b.get("micro") or 0)
        ge = "✓" if c["micro_gold_density"] + 1e-12 >= GATE_DENS else "·"
        lines.append(
            f"| {c['slug']} | {c.get('role')} | {b.get('pool20', '—')} | "
            f"{c['pool_hits']['20']} | "
            f"{c['pool_hits']['20'] - int(b.get('pool20') or 0):+d} | "
            f"{b.get('micro', 0):.0%} | {c['micro_gold_density']:.0%} | "
            f"{d_micro:+.0%} | "
            f"{b.get('at7', '—')} | {c['cut_hits']['7']} | {ge} |"
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
        f"- 门槛①（三案各≥2/3）：{'✓' if g['holdout_all_ge_23'] else '✗'}"
        f"（{g['n_holdout_pass']}/3）",
        f"- AI171 相对 R39 可见抬／过闸：{'✓' if g['ai171_ok'] else '✗'}"
        f"（{R39['ai171']['micro']:.0%}→{g['ai171_micro']:.0%}）",
        f"- 柬泰：{'✓' if g['kh_th_ok'] else '✗'}"
        f"（{R39['kh_th']['micro']:.0%}→{g['kh_th_micro']:.0%}）",
        f"- 王虹：{'✓' if g['wanghong_ok'] else '✗'}"
        f"（{R39['wanghong']['micro']:.0%}→{g['wanghong_micro']:.0%}）",
        f"- 刘翔 @7≥{LIUXIANG_AT7_MIN}：{'✓' if g['liuxiang_ok'] else '✗'}"
        f"（{g['liuxiang_at7']}）",
        f"- 吉隆不显著掉：{'✓' if g['jilong_ok'] else '✗'}",
        f"- 中美AI不显著掉：{'✓' if g['us_ok'] else '✗'}",
        "",
        "### 距门槛①还差多少",
        "",
        f"- {g['gap_note']}",
        "",
        "### 下一刀建议",
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
        "- `artifacts/R40_holdout_gate.json`",
        "- `artifacts/R40_holdout_gate.md`",
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

    def _ok_drop(now: float, base: float) -> bool:
        return now + 1e-12 >= base - DROP_EPS

    def _ge23(now: float) -> bool:
        return now + 1e-12 >= GATE_DENS

    ai_ok = _ge23(ai["micro_gold_density"]) or (
        ai["micro_gold_density"] + 1e-12 >= R39["ai171"]["micro"] + 0.02
    )
    kh_ok = _ge23(kh["micro_gold_density"]) or _ok_drop(
        kh["micro_gold_density"], R39["kh_th"]["micro"],
    )
    wh_ok = _ge23(wh["micro_gold_density"]) or _ok_drop(
        wh["micro_gold_density"], R39["wanghong"]["micro"],
    )
    lx_ok = lx["cut_hits"]["7"] >= LIUXIANG_AT7_MIN
    jl_ok = _ok_drop(jl["micro_gold_density"], R39["jilong"]["micro"])
    us_ok = _ok_drop(us["micro_gold_density"], R39["us_cn_ai"]["micro"])
    n_pass = sum(1 for c in holdout_cases if _ge23(c["micro_gold_density"]))

    gaps = []
    for c in holdout_cases:
        need = GATE_DENS - c["micro_gold_density"]
        if need > 1e-12:
            gaps.append(f"{c['slug']} 差 {need:.0%}（现 {c['micro_gold_density']:.0%}）")
    gap_note = "；".join(gaps) if gaps else "三案均已 ≥2/3。"

    from collections import Counter
    causes = []
    for c in holdout_cases:
        for r in c.get("diag_rows") or []:
            if r["gold_density"] + 1e-12 < GATE_DENS:
                causes.append(r["cause"])
    cc = Counter(causes)
    if n_pass == 3:
        next_cut = "门槛①已过；可收王虹 q_002 第二澄清金标进盒，或稳回归后收主仓。"
    elif cc.get("池外", 0) >= max(cc.get("池内挤", 0), cc.get("盒稀", 0)):
        next_cut = "仍有池外：授权主仓丙收声明，或 need_en 深化（禁盲扩体积）。"
    else:
        next_cut = "池内挤／盒稀：澄清第二金标保位或同簇再收一刀。"

    mean_r39 = sum(R39[h["slug"]]["micro"] for h in HOLDOUT) / 3
    mean_now = sum(c["micro_gold_density"] for c in holdout_cases) / 3
    bullets = [
        f"holdout 案均 {mean_r39:.0%}→**{mean_now:.0%}**"
        f"（Σ {sum(c['sum_gold_in_boxes'] for c in holdout_cases)}/"
        f"{sum(c['sum_k'] for c in holdout_cases)}）。",
        f"门槛① **{n_pass}/3**"
        f"（wanghong {wh['micro_gold_density']:.0%}／"
        f"kh_th {kh['micro_gold_density']:.0%}／"
        f"ai171 {ai['micro_gold_density']:.0%}）。",
        f"`ai171`：{R39['ai171']['micro']:.0%}→**{ai['micro_gold_density']:.0%}**。",
        f"`kh_th`：{R39['kh_th']['micro']:.0%}→**{kh['micro_gold_density']:.0%}**。",
        f"`wanghong`：{R39['wanghong']['micro']:.0%}→**{wh['micro_gold_density']:.0%}**。",
        f"刘翔 @7 **{lx['cut_hits']['7']}**；吉隆 {jl['micro_gold_density']:.0%}；"
        f"中美AI {us['micro_gold_density']:.0%}。",
    ]
    open_holes = []
    for c in holdout_cases:
        if not _ge23(c["micro_gold_density"]):
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
        "ai171_ok": ai_ok,
        "ai171_micro": round(ai["micro_gold_density"], 4),
        "kh_th_ok": kh_ok,
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
        "pass_ticket": bool(
            n_pass >= 1 and ai_ok and kh_ok and wh_ok and lx_ok and jl_ok and us_ok
        ),
    }

    report = {
        "ticket": "R40-holdout-gate",
        "kind": "clock-strike-k+clarify-primary-amount-nails",
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict_bullets": bullets,
        "gate": gate,
        "open_holes": open_holes[:20],
        "cases": [lx, *holdout_cases, jl, us],
        "changes": [
            "clock_strike cluster + shrink k when one left",
            "clarify vs rumor; primary vs roundup",
            "amount×latin adjudicate slot boost + nail pack",
            "variable k for single nail packs; no stage1 expand",
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
    (OUT / "R40_holdout_gate.json").write_text(
        json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R40_holdout_gate.md").write_text(_markdown(report), encoding="utf-8")
    print(
        f"R40 ai={ai['micro_gold_density']:.0%} kh={kh['micro_gold_density']:.0%} "
        f"wh={wh['micro_gold_density']:.0%} lx@7={lx['cut_hits']['7']} "
        f"gate={n_pass}/3 pass={gate['pass_ticket']} wall={report['wall_s']}s",
        flush=True,
    )
    return 0 if gate["pass_ticket"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
