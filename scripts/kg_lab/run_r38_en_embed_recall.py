#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R38：AI171 池外——英文长段／嵌入召回（禁堆一筛体积）。

接 R37。验收：AI171 案均相对 33% 可见抬升；王虹／柬泰／刘翔／吉隆／中美AI 不显著掉。
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

# R37 结论文本基线（本票对照）
R37 = {
    "liuxiang": {"pool20": 8, "at7": 12, "micro": 0.5714, "sum_g": 12, "sum_k": 21},
    "wanghong": {"pool20": 9, "at7": 5, "micro": 0.5556, "sum_g": 5, "sum_k": 9},
    "kh_th": {"pool20": 6, "at7": 4, "micro": 0.5714, "sum_g": 5, "sum_k": 9},
    "ai171": {"pool20": 5, "at7": 4, "micro": 0.3333, "sum_g": 3, "sum_k": 9},
    "jilong": {"pool20": 5, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
    "us_cn_ai": {"pool20": 8, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
}
GATE_DENS = 2.0 / 3.0
LIUXIANG_AT7_MIN = 11
DROP_EPS = 0.05


def _markdown(report: dict[str, Any]) -> str:
    g = report["gate"]
    lines = [
        "# R38 — AI171 池外：英文长段／嵌入召回",
        "",
        "> 接 R37；禁堆一筛体积；同数字通稿勿挤可核验代表。",
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
        "1. 跨语臂：可核验槽 → 英文检索串，嵌入⊕BM25 并入 RRF（不扩池体积）。",
        "2. 长段嵌入窗：头＋数字核＋高拉丁窗拼装（`EMBED_PACK_VER=2`，只重嵌超长／高拉丁）。",
        "3. 主张臂／槽档：高拉丁×主张英核／数额可进注入；数额排序抬英文声明与官方短句，指纹去重抗通稿灌注。",
        "4. 二筛簇代表：高拉丁声明优先于同数字中文通稿壳。",
        "",
        "## vs R37",
        "",
        "| 案 | 角色 | R37池20 | R38池20 | Δ池 | R37微密度 | R38微密度 | Δ密度 | R37@7 | R38@7 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R37.get(c["slug"], {})
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
        f"- AI171 案均相对 R37(33%) 可见抬升：{'✓' if g['ai171_up'] else '✗'}"
        f"（{R37['ai171']['micro']:.0%}→{g['ai171_micro']:.0%}）",
        f"- 柬泰不显著掉：{'✓' if g['kh_th_ok'] else '✗'}"
        f"（{R37['kh_th']['micro']:.0%}→{g['kh_th_micro']:.0%}）",
        f"- 王虹不显著掉：{'✓' if g['wanghong_ok'] else '✗'}"
        f"（{R37['wanghong']['micro']:.0%}→{g['wanghong_micro']:.0%}）",
        f"- 刘翔 @7≥{LIUXIANG_AT7_MIN}：{'✓' if g['liuxiang_ok'] else '✗'}"
        f"（{g['liuxiang_at7']}）",
        f"- 吉隆不显著掉：{'✓' if g['jilong_ok'] else '✗'}",
        f"- 中美AI不显著掉：{'✓' if g['us_ok'] else '✗'}",
        f"- 门槛①（三案各≥2/3）：{'✓' if g['holdout_all_ge_23'] else '✗'}"
        f"（{g['n_holdout_pass']}/3）",
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
        "- `artifacts/R38_en_embed_recall.json`",
        "- `artifacts/R38_en_embed_recall.md`",
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
        return now + 1e-12 >= base + 0.02

    def _ok_drop(now: float, base: float) -> bool:
        return now + 1e-12 >= base - DROP_EPS

    ai_up = _up(ai["micro_gold_density"], R37["ai171"]["micro"])
    if not ai_up and ai["sum_gold_in_boxes"] > R37["ai171"]["sum_g"]:
        ai_up = True
    # 池20 可见抬也算本票「抬金标进 pool」的弱通过信号，但案均闸仍看密度
    ai_pool_up = ai["pool_hits"]["20"] > R37["ai171"]["pool20"]

    kh_ok = _ok_drop(kh["micro_gold_density"], R37["kh_th"]["micro"])
    wh_ok = _ok_drop(wh["micro_gold_density"], R37["wanghong"]["micro"])
    lx_ok = lx["cut_hits"]["7"] >= LIUXIANG_AT7_MIN
    jl_ok = _ok_drop(jl["micro_gold_density"], R37["jilong"]["micro"])
    us_ok = _ok_drop(us["micro_gold_density"], R37["us_cn_ai"]["micro"])
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

    from collections import Counter
    causes = []
    for c in holdout_cases:
        for r in c.get("diag_rows") or []:
            if r["gold_density"] + 1e-12 < GATE_DENS:
                causes.append(r["cause"])
    cc = Counter(causes)
    if cc.get("池外", 0) >= max(cc.get("池内挤", 0), cc.get("盒稀", 0)):
        next_cut = "英文金标仍有池外：可授权主仓丙收声明进箱，或二筛按主张核换掉同数字通稿。"
    elif cc.get("盒稀", 0) or cc.get("池内挤", 0):
        next_cut = "池内已到、盒未满：二筛主张去重／同数字通稿让位再收一刀。"
    else:
        next_cut = "冲门槛①；王虹／柬泰收尾到 2/3。"

    mean_r37 = sum(R37[h["slug"]]["micro"] for h in HOLDOUT) / 3
    mean_now = sum(c["micro_gold_density"] for c in holdout_cases) / 3
    bullets = [
        f"holdout 案均 {mean_r37:.0%}→**{mean_now:.0%}**"
        f"（Σ {sum(c['sum_gold_in_boxes'] for c in holdout_cases)}/"
        f"{sum(c['sum_k'] for c in holdout_cases)}）。",
        f"`ai171`：{R37['ai171']['micro']:.0%}→**{ai['micro_gold_density']:.0%}**"
        f"（池20 {R37['ai171']['pool20']}→{ai['pool_hits']['20']}）。",
        f"`kh_th`：{R37['kh_th']['micro']:.0%}→**{kh['micro_gold_density']:.0%}**。",
        f"`wanghong`：{R37['wanghong']['micro']:.0%}→**{wh['micro_gold_density']:.0%}**。",
        f"刘翔 @7 **{lx['cut_hits']['7']}**；吉隆 {jl['micro_gold_density']:.0%}；"
        f"中美AI {us['micro_gold_density']:.0%}。",
        f"验收目标闸：AI{'✓' if ai_up else '✗'}"
        f"{'（池↑）' if (not ai_up and ai_pool_up) else ''} "
        f"柬{'✓' if kh_ok else '✗'} 王{'✓' if wh_ok else '✗'} "
        f"刘{'✓' if lx_ok else '✗'}。",
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
        "ai171_pool_up": ai_pool_up,
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
        "pass_ticket": bool(ai_up and kh_ok and wh_ok and lx_ok and jl_ok and us_ok),
    }

    report = {
        "ticket": "R38-en-embed-recall",
        "kind": "en-long-embed+anti-wire-same-digit",
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict_bullets": bullets,
        "gate": gate,
        "open_holes": open_holes[:20],
        "cases": [lx, *holdout_cases, jl, us],
        "changes": [
            "crosslingual EN query embed+bm25 RRF arm",
            "long-para embed pack head+digit+latin windows",
            "EN claim tier/score; amount inject prefers EN/official over wire clones",
            "cluster rep prefers high-latin declaration",
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
    (OUT / "R38_en_embed_recall.json").write_text(
        json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R38_en_embed_recall.md").write_text(_markdown(report), encoding="utf-8")
    print(
        f"R38 ai={ai['micro_gold_density']:.0%} kh={kh['micro_gold_density']:.0%} "
        f"wh={wh['micro_gold_density']:.0%} lx@7={lx['cut_hits']['7']} "
        f"pool_ai={ai['pool_hits']['20']} pass={gate['pass_ticket']} "
        f"wall={report['wall_s']}s",
        flush=True,
    )
    return 0 if gate["pass_ticket"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
