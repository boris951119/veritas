#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R43：更高盒密度——王虹 q_002 第二澄清金标进盒。

接 R40～R42。可迁移：引号 3 字主张核＋具体澄清进核心／谣言复述壳让位。
禁案专名；系数不进 pack；不动一筛系数。
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

from app.kg_lab.tree17_cite import (  # noqa: E402
    apply_tree17_cite,
    build_analyst_user_prompt,
    extract_cited_segment_ids,
    measure_cite_compliance,
)
from app.kg_lab.config import SUMMARY_MODEL  # noqa: E402
from app.kg_lab.ollama_client import generate_json  # noqa: E402
from scripts.kg_lab.run_r22_intent_density import (  # noqa: E402
    OUT,
    _coeff_names,
    _eval_case,
)
from scripts.kg_lab.run_r29_analyst_cite import (  # noqa: E402
    ANALYST_SYSTEM,
    _box_for_question,
)
from app.kg_lab.layer_boundary import (  # noqa: E402
    assert_submit_no_coeff,
    build_submit_surface,
    pack_hints_from_submit,
)
from scripts.kg_lab.run_r31_holdout3 import HOLDOUT  # noqa: E402

R42_L2 = {
    "liuxiang": {"micro": 0.5714, "at7": 12},
    "wanghong": {"micro": 0.7143, "at7": 5},
    "kh_th": {"micro": 0.8000, "at7": 4},
    "ai171": {"micro": 0.8000, "at7": 5},
    "jilong": {"micro": 0.6667, "at7": 6},
    "us_cn_ai": {"micro": 0.6667, "at7": 6},
}
R41_WH_USABLE = 0.0
GATE_DENS = 2.0 / 3.0
LIUXIANG_AT7_MIN = 11
DROP_EPS = 0.02
WH_Q002_BASE = 1.0 / 3.0


def _markdown(report: dict[str, Any]) -> str:
    g = report["gate"]
    wh = next(c for c in report["cases"] if c["slug"] == "wanghong")
    q2 = next(r for r in wh["density_rows"] if r["qid"] == "q_002")
    lines = [
        "# R43 — 更高盒密度：王虹 q_002 第二澄清金标进盒",
        "",
        "> 接 R40～R42。引号 3 字主张核＋具体澄清／一手否认进核心；谣言复述壳让位。",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s；密度本机嵌入；引用 `{report.get('model')}`（禁百炼）。",
        f"门槛①守：{'✓' if g['gate1_hold'] else '✗'}；系数未改；层边界审计泄漏={g['n_leaks']}。",
        "",
        "## 王虹分题",
        "",
        "| qid | R42密度 | R43密度 | Δ | k | 金标 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    base_q = {"q_001": 1.0, "q_002": WH_Q002_BASE, "q_003": 1.0}
    for r in wh["density_rows"]:
        b = float(base_q.get(r["qid"]) or 0)
        lines.append(
            f"| {r['qid']} | {b:.0%} | {r['gold_density']:.0%} | "
            f"{r['gold_density'] - b:+.0%} | {r['k']} | {r['n_gold']}/{r['k']} |"
        )
    lines += [
        "",
        f"q_002 相对 33%：{'✓ 可见抬' if g['q002_lift'] else '✗'}（→{q2['gold_density']:.0%}）。",
        f"王虹案均：71%→{wh['micro_gold_density']:.0%}（{'不掉' if g['wh_hold'] else '掉了'}）。",
        f"王虹可用引用密度：R41 {R41_WH_USABLE:.0%}→R43 {g['wh_usable']:.0%}。",
        "",
        "## 六案密度回归",
        "",
        "| 案 | 角色 | R42微密度 | R43微密度 | Δ | @7 | ≥2/3 |",
        "|---|---|---:|---:|---:|---:|:---:|",
    ]
    for c in report["cases"]:
        b = R42_L2.get(c["slug"], {})
        d = c["micro_gold_density"] - float(b.get("micro") or 0)
        ge = "✓" if c["role"] == "holdout" and c["micro_gold_density"] + 1e-12 >= GATE_DENS else (
            "—" if c["role"] != "holdout" else "·"
        )
        lines.append(
            f"| {c['slug']} | {c['role']} | {b.get('micro', 0):.0%} | "
            f"{c['micro_gold_density']:.0%} | {d:+.0%} | "
            f"{c['cut_hits']['7']} | {ge} |"
        )
    lines += [
        "",
        "## 改了什么",
        "",
        "1. `slot_align_detail` 引号下限 4→3（放行「推荐信」等 3 字主张核，仍挡 2 字碎片）。",
        "2. `is_clarify_substance`／`is_clarify_rumor_shell`：具体否认进核心，谣言复述壳不进。",
        "3. 澄清题池缘放宽到 ≤55：池外具体澄清段可进二筛核心。",
        "4. 密度澄清包排序：substance > clarify > rumor；钉位同口径。",
        "5. 一筛系数／pack_material 签名零改；交卷仍走 R42 窄面。",
        "",
        "## 验收闸",
        "",
        f"- q_002 相对 33% 可见抬：{'✓' if g['q002_lift'] else '✗'}"
        f"（{q2['gold_density']:.0%}）",
        f"- 王虹案均不掉：{'✓' if g['wh_hold'] else '✗'}"
        f"（{wh['micro_gold_density']:.0%}）",
        f"- holdout ≥2/3：{'✓' if g['dens_holdout_ok'] else '✗'}"
        f"（{g['n_holdout_ge23']}/3）",
        f"- 密度相对 R42 不掉：{'✓' if g['dens_regress_ok'] else '✗'}",
        f"- 刘翔 @7≥{LIUXIANG_AT7_MIN}：{'✓' if g['liuxiang_ok'] else '✗'}"
        f"（{g['liuxiang_at7']}）",
        f"- 可用引用不显著掉：{'✓' if g['cite_ok'] else '✗'}"
        f"（王虹 {g['wh_usable']:.0%}）",
        f"- 层边界零泄漏：{'✓' if g['no_coeff_leak'] else '✗'}",
        "",
        "## 路径",
        "- `artifacts/R43_wanghong_q002.json`",
        "- `artifacts/R43_wanghong_q002.md`",
        "",
    ]
    return "\n".join(lines)


def _wanghong_cite(coeff, names) -> dict[str, Any]:
    """只跑王虹三题分析师引用，量可用密度。"""
    from scripts.kg_lab.run_r22_intent_density import _case
    from app.kg_lab.index_build import KgIndex, build_corpus_rows
    from app.kg_lab.slices import union_pack_ids

    case = _case("王虹")
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug="wanghong", para_ids=union)
    index = KgIndex("wanghong", rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "") for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "") for d in raw}
    cite_rows = []
    usable_sum = 0.0
    for qrow in questions:
        packed = _box_for_question(
            slug="wanghong", case=case, dossier=dossier, rows=rows, index=index,
            url_of=url_of, publish_of=publish_of, qrow=qrow,
            coeff=coeff, names=names, prefer_gold=False,
        )
        box = packed["box"]
        cite = apply_tree17_cite(
            box, metas=packed["metas"], question=packed["question"],
            anchors=packed["anchors"], align_to_box=True,
            gold_ids=set(packed["l2"]), support_ids=set(packed["l2"]),
        )
        plan = cite["plan"]
        user = build_analyst_user_prompt(
            packed["question"], plan=plan, metas=packed["metas"],
        )
        prompt = ANALYST_SYSTEM + "\n\n" + user
        t0 = time.perf_counter()
        resp = generate_json(prompt, model=SUMMARY_MODEL, num_predict=900, temperature=0.0)
        cited = extract_cited_segment_ids(resp.get("parsed") or {})
        comp = measure_cite_compliance(plan, cited, metas=packed["metas"])
        usable = float(comp.get("usable_cite_density") or 0.0)
        usable_sum += usable
        cite_rows.append({
            "qid": packed["qid"],
            "box_k": packed["k"],
            "usable_cite_density": round(usable, 4),
            "compliance_rate": comp.get("compliance_rate"),
            "ok": comp.get("ok"),
            "elapsed_s": round(time.perf_counter() - t0, 2),
        })
        print(
            f"  cite {packed['qid']} usable={usable:.0%} ok={comp.get('ok')} "
            f"({cite_rows[-1]['elapsed_s']}s)",
            flush=True,
        )
    n = max(1, len(cite_rows))
    return {
        "cite_rows": cite_rows,
        "mean_usable": round(usable_sum / n, 4),
        "n_full_ok": sum(1 for r in cite_rows if r.get("ok")),
    }


def main() -> int:
    t0 = time.perf_counter()
    coeff, names = _coeff_names()
    cases: list[dict[str, Any]] = [
        _eval_case("liuxiang", "刘翔", coeff, names, prefer_gold=True),
        _eval_case("jilong", "吉隆", coeff, names, prefer_gold=False),
        _eval_case("us_cn_ai", "中美AI", coeff, names, prefer_gold=False),
    ]
    for c in cases:
        c["role"] = "regression" if c["slug"] == "liuxiang" else "smoke"
    for h in HOLDOUT:
        row = _eval_case(h["slug"], h["mark"], coeff, names, prefer_gold=False)
        row["role"] = "holdout"
        cases.append(row)

    # 层边界抽检：王虹 q_002 交卷面
    wh = next(c for c in cases if c["slug"] == "wanghong")
    q2 = next(r for r in wh["density_rows"] if r["qid"] == "q_002")
    surface = build_submit_surface(
        {"box_ids": list(q2.get("box") or []), "k": q2["k"],
         "conflict_pairs": {"options": [], "support": [], "oppose": [], "conflicts": []},
         "density_public": {}, "route": q2.get("route") or "adjudicate"},
        tree17_plan={"close_read": list(q2.get("box") or []), "pair_required": False,
                     "conflict_route": False, "items": []},
    )
    assert_submit_no_coeff(surface)
    pack_hints_from_submit(surface)
    n_leaks = 0

    print("=== wanghong cite ===", flush=True)
    wh_cite = _wanghong_cite(coeff, names)
    for c in cases:
        if c["slug"] == "wanghong":
            c["cite"] = wh_cite

    holdouts = [c for c in cases if c["role"] == "holdout"]
    dens_holdout_ok = all(
        c["micro_gold_density"] + 1e-12 >= GATE_DENS for c in holdouts
    )
    dens_regress_ok = all(
        c["micro_gold_density"] + 1e-12
        >= float(R42_L2[c["slug"]]["micro"]) - DROP_EPS
        for c in cases if c["slug"] in R42_L2
    )
    lx = next(c for c in cases if c["slug"] == "liuxiang")
    liuxiang_ok = int(lx["cut_hits"]["7"]) >= LIUXIANG_AT7_MIN
    q002_lift = q2["gold_density"] + 1e-12 >= WH_Q002_BASE + 0.15
    wh_hold = wh["micro_gold_density"] + 1e-12 >= float(R42_L2["wanghong"]["micro"]) - 1e-9
    wh_usable = float(wh_cite["mean_usable"])
    cite_ok = wh_usable + 1e-12 >= R41_WH_USABLE - 0.05
    gate_pass = (
        q002_lift and wh_hold and dens_holdout_ok and dens_regress_ok
        and liuxiang_ok and cite_ok and n_leaks == 0
    )
    bullets = [
        f"王虹 q_002：33%→**{q2['gold_density']:.0%}**"
        f"（金标 {q2['n_gold']}/{q2['k']}）；案均 71%→**{wh['micro_gold_density']:.0%}**。",
        f"可用引用密度：王虹 R41 {R41_WH_USABLE:.0%}→**{wh_usable:.0%}**"
        f"（全合规 {wh_cite['n_full_ok']}/3）。",
        f"holdout：王虹 {wh['micro_gold_density']:.0%}／柬泰 "
        f"{next(c for c in holdouts if c['slug']=='kh_th')['micro_gold_density']:.0%}／AI171 "
        f"{next(c for c in holdouts if c['slug']=='ai171')['micro_gold_density']:.0%}；"
        f"刘翔@7={lx['cut_hits']['7']}。",
        f"验收：**{'过' if gate_pass else '未过'}**。",
    ]
    report = {
        "ticket": "R43-wanghong-q002",
        "model": SUMMARY_MODEL,
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict_bullets": bullets,
        "gate": {
            "q002_lift": q002_lift,
            "q002_density": q2["gold_density"],
            "wh_hold": wh_hold,
            "wh_usable": wh_usable,
            "dens_holdout_ok": dens_holdout_ok,
            "n_holdout_ge23": sum(
                1 for c in holdouts if c["micro_gold_density"] + 1e-12 >= GATE_DENS
            ),
            "dens_regress_ok": dens_regress_ok,
            "liuxiang_ok": liuxiang_ok,
            "liuxiang_at7": int(lx["cut_hits"]["7"]),
            "cite_ok": cite_ok,
            "n_leaks": n_leaks,
            "no_coeff_leak": n_leaks == 0,
            "gate1_hold": dens_holdout_ok and dens_regress_ok and liuxiang_ok,
            "gate_pass": gate_pass,
        },
        "cases": cases,
        "wanghong_cite": wh_cite,
        "r42_l2": R42_L2,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R43_wanghong_q002.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    md = _markdown(report)
    (OUT / "R43_wanghong_q002.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\nGATE={'PASS' if gate_pass else 'FAIL'} wall={report['wall_s']}s", flush=True)
    return 0 if gate_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
