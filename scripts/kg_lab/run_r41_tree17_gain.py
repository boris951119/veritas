#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R41：门槛②——树17（L3 引用）相对 R30 基线增益。

接 R40 密度闸；不动一／二筛。量 holdout＋回归引用合规／可用引用密度。
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

from app.kg_lab.config import SUMMARY_MODEL  # noqa: E402
from app.kg_lab.ollama_client import generate_json  # noqa: E402
from app.kg_lab.tree17_cite import (  # noqa: E402
    apply_tree17_cite,
    build_analyst_user_prompt,
    extract_cited_segment_ids,
    measure_cite_compliance,
    repair_cites_to_band,
)
from scripts.kg_lab.run_r29_analyst_cite import (  # noqa: E402
    ANALYST_SYSTEM,
    _box_for_question,
)
from scripts.kg_lab.run_r22_intent_density import (  # noqa: E402
    OUT,
    _case,
    _coeff_names,
)
from scripts.kg_lab.run_r31_holdout3 import HOLDOUT  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.slices import union_pack_ids  # noqa: E402

# R30 引用合规基线（回归／冒烟）
R30_COMP = {
    "liuxiang": {"axes_ok": 9, "axes_total": 9, "n_full_ok": 3, "n_q": 3},
    "jilong": {"axes_ok": 9, "axes_total": 9, "n_full_ok": 3, "n_q": 3},
    "us_cn_ai": {"axes_ok": 9, "axes_total": 9, "n_full_ok": 3, "n_q": 3},
}
# R40 密度闸（门槛①）
R40_L2 = {
    "liuxiang": {"micro": 0.5714, "at7": 12},
    "wanghong": {"micro": 0.7143, "at7": 5},
    "kh_th": {"micro": 0.8000, "at7": 4},
    "ai171": {"micro": 0.8000, "at7": 5},
    "jilong": {"micro": 0.6667, "at7": 6},
    "us_cn_ai": {"micro": 0.6667, "at7": 6},
}
GATE_DENS = 2.0 / 3.0
DROP_EPS = 0.05
LIUXIANG_AT7_MIN = 11


def _run_analyst(
    question: str,
    plan: dict[str, Any],
    metas: dict[str, Any],
) -> dict[str, Any]:
    user = build_analyst_user_prompt(
        question, plan=plan, metas=metas, include_non_close=False,
    )
    prompt = ANALYST_SYSTEM + "\n\n" + user
    t0 = time.perf_counter()
    resp = generate_json(prompt, model=SUMMARY_MODEL, num_predict=900, temperature=0.0)
    elapsed = round(time.perf_counter() - t0, 2)
    parsed = resp.get("parsed") or {}
    cited0 = extract_cited_segment_ids(parsed)
    comp0 = measure_cite_compliance(plan, cited0, metas=metas)

    def _gen(p: str) -> dict[str, Any]:
        return generate_json(p, model=SUMMARY_MODEL, num_predict=900, temperature=0.0)

    repair = repair_cites_to_band(
        parsed, plan, question=question, metas=metas,
        generate_fn=_gen, system_prompt=ANALYST_SYSTEM,
    )
    return {
        "cited_ids_raw": cited0,
        "compliance_raw": comp0,
        "cited_ids": repair["cited_ids"],
        "compliance": repair["compliance"],
        "oob_before": repair["oob_before"],
        "repaired_by_regen": repair["repaired_by_regen"],
        "n_dropped_evidence": repair["n_dropped_evidence"],
        "elapsed_s": elapsed,
        "model": SUMMARY_MODEL,
        "has_tree17_block": "【树17 引用纪律】" in prompt,
    }


def _eval_case(
    slug: str,
    mark: str,
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    prefer_gold: bool,
    role: str,
) -> dict[str, Any]:
    case = _case(mark, prefer_local=(slug == "liuxiang"))
    print(f"=== eval {slug} ({role}) ===", flush=True)
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "") for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "") for d in raw}

    dens_rows: list[dict[str, Any]] = []
    cite_rows: list[dict[str, Any]] = []
    sum_g = sum_k = at7 = 0
    axes_ok = axes_total = 0
    usable_sum = 0.0
    gold_box_close_hits = gold_box_total = 0

    for qrow in questions:
        packed = _box_for_question(
            slug=slug, case=case, dossier=dossier, rows=rows, index=index,
            url_of=url_of, publish_of=publish_of, qrow=qrow,
            coeff=coeff, names=names, prefer_gold=prefer_gold,
        )
        qid = packed["qid"]
        box = packed["box"]
        k_sel = packed["k"]
        l2 = packed["l2"]
        n_gold = packed["n_gold"]
        sum_g += n_gold
        sum_k += k_sel
        at7 += sum(1 for g in l2 if g in packed["order7"])
        dens_rows.append({
            "qid": qid, "k": k_sel, "n_gold": n_gold,
            "gold_density": round(n_gold / k_sel, 4) if k_sel else 0.0,
        })

        cite = apply_tree17_cite(
            box,
            metas=packed["metas"],
            question=packed["question"],
            anchors=packed["anchors"],
            align_to_box=True,
            gold_ids=set(l2),
            support_ids=set(l2),
        )
        plan = cite["plan"]
        l3 = cite["l3"]
        g_box = int((l3.get("gold") or {}).get("in_box") or 0)
        g_close = int((l3.get("gold") or {}).get("in_close") or 0)
        gold_box_total += g_box
        gold_box_close_hits += g_close

        analyst = _run_analyst(packed["question"], plan, packed["metas"])
        compliance = analyst["compliance"]
        axes_ok += int(compliance["axes_ok"])
        axes_total += int(compliance["axes_total"])
        usable_sum += float(compliance.get("usable_cite_density") or 0.0)
        cite_rows.append({
            "qid": qid,
            "conflict": plan["conflict_route"],
            "pair_required": plan["pair_required"],
            "close_k_effective": plan.get("close_k_effective"),
            "box_k": len(box),
            "gold_in_box_to_close": l3.get("gold_in_box_to_close"),
            "compliance": compliance,
            "usable_cite_density": compliance.get("usable_cite_density"),
            "analyst": {
                k: analyst[k] for k in (
                    "cited_ids", "oob_before", "repaired_by_regen",
                    "elapsed_s", "has_tree17_block",
                )
            },
        })
        print(
            f"  {qid} L2={n_gold}/{k_sel} | "
            f"comp={compliance['compliance_rate']:.0%} "
            f"usable={compliance.get('usable_cite_density', 0):.0%} "
            f"band={'Y' if compliance['band_ok'] else 'N'} "
            f"pair={'Y' if compliance['pair_ok'] else 'N'} "
            f"({analyst['elapsed_s']}s)",
            flush=True,
        )

    micro = sum_g / sum_k if sum_k else 0.0
    n_q = len(cite_rows) or 1
    return {
        "slug": slug,
        "role": role,
        "micro_gold_density": round(micro, 4),
        "sum_gold_in_boxes": sum_g,
        "sum_k": sum_k,
        "cut_hits": {"7": at7},
        "density_rows": dens_rows,
        "cite_rows": cite_rows,
        "compliance_summary": {
            "axes_ok": axes_ok,
            "axes_total": axes_total,
            "rate": round(axes_ok / axes_total, 4) if axes_total else None,
            "n_full_ok": sum(1 for r in cite_rows if r["compliance"]["ok"]),
            "n_questions": len(cite_rows),
            "n_band_ok": sum(1 for r in cite_rows if r["compliance"]["band_ok"]),
            "n_pair_ok": sum(1 for r in cite_rows if r["compliance"]["pair_ok"]),
            "mean_usable_cite_density": round(usable_sum / n_q, 4),
            "gold_box_to_close": (
                round(gold_box_close_hits / gold_box_total, 4)
                if gold_box_total else None
            ),
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    g = report["gate"]
    lines = [
        "# R41 — 门槛②：树17（L3 引用）相对基线增益",
        "",
        "> 接 R40；不动一／二筛。冲突成对／时点·数额优先／排名靠前／采信·对立标签。",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s；模型 `{report['model']}`（本机，禁百炼）。",
        f"门槛②判定：**{'过' if g['gate2_pass'] else '未过'}**。",
        "",
        "## 密度回归（门槛①须守）",
        "",
        "| 案 | 角色 | R40微密度 | R41微密度 | Δ | R40@7 | R41@7 | ≥2/3 |",
        "|---|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for c in report["cases"]:
        b = R40_L2.get(c["slug"], {})
        d = c["micro_gold_density"] - float(b.get("micro") or 0)
        ge = "✓" if c["micro_gold_density"] + 1e-12 >= GATE_DENS else (
            "—" if c["role"] != "holdout" else "·"
        )
        if c["role"] != "holdout":
            ge = "—"
        lines.append(
            f"| {c['slug']} | {c['role']} | {b.get('micro', 0):.0%} | "
            f"{c['micro_gold_density']:.0%} | {d:+.0%} | "
            f"{b.get('at7', '—')} | {c['cut_hits']['7']} | {ge} |"
        )
    lines += [
        "",
        "## 引用合规／可用密度（对照 R30）",
        "",
        "| 案 | 角色 | R30全合规 | R41全合规 | R30轴 | R41轴 | 可用引用密度 | 金标盒→细读 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        s = c["compliance_summary"]
        prev = R30_COMP.get(c["slug"])
        if prev:
            full = f"{prev['n_full_ok']}/{prev['n_q']}"
            ax = f"{prev['axes_ok']}/{prev['axes_total']}"
        else:
            full = ax = "（无）"
        g2c = s.get("gold_box_to_close")
        g2c_s = f"{g2c:.0%}" if g2c is not None else "—"
        lines.append(
            f"| {c['slug']} | {c['role']} | {full} | "
            f"{s['n_full_ok']}/{s['n_questions']} | {ax} | "
            f"{s['axes_ok']}/{s['axes_total']} | "
            f"{s['mean_usable_cite_density']:.0%} | {g2c_s} |"
        )
    lines += [
        "",
        "### 分题",
        "",
        "| 案 | qid | 盒k | 合规率 | 可用密度 | 带宽 | 成对 | 重抽 |",
        "|---|---|---:|---:|---:|---|---|---|",
    ]
    for c in report["cases"]:
        for row in c["cite_rows"]:
            cp = row["compliance"]
            a = row["analyst"]
            lines.append(
                f"| {c['slug']} | {row['qid']} | {row['box_k']} | "
                f"{cp['compliance_rate']:.0%} | "
                f"{float(row.get('usable_cite_density') or 0):.0%} | "
                f"{'Y' if cp['band_ok'] else 'N'} | "
                f"{'Y' if cp['pair_ok'] else 'N'} | "
                f"{'Y' if a['repaired_by_regen'] else 'N'} |"
            )
    lines += [
        "",
        "## 验收闸",
        "",
        f"- 门槛① holdout 各≥2/3：{'✓' if g['dens_holdout_ok'] else '✗'}"
        f"（{g['n_holdout_ge23']}/3）",
        f"- 回归／冒烟密度不掉：{'✓' if g['dens_smoke_ok'] else '✗'}",
        f"- 刘翔 @7≥{LIUXIANG_AT7_MIN}：{'✓' if g['liuxiang_ok'] else '✗'}"
        f"（{g['liuxiang_at7']}）",
        f"- R30 重叠案合规不掉：{'✓' if g['r30_cite_hold'] else '✗'}",
        f"- holdout 引用增益：{'✓' if g['holdout_cite_gain'] else '✗'}"
        f"（{g['holdout_cite_note']}）",
        f"- 门槛②：{'✓ 过' if g['gate2_pass'] else '✗ 未过'}",
        "",
        "## 改了什么",
        "",
        "1. 可核验分补英文时点／数额／声明声部（AAIB／preliminary report 等）。",
        "2. 细读对外序按可核验＋盒序重排；提示词强调优先引靠前采信／对立。",
        "3. 合规读数新增 `usable_cite_density`（带宽内可用引用÷盒长）。",
        "4. L2 密度路径零改。",
        "",
        "## 路径",
        "- `artifacts/R41_tree17_gain.json`",
        "- `artifacts/R41_tree17_gain.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    coeff, names = _coeff_names()
    cases: list[dict[str, Any]] = [
        _eval_case("liuxiang", "刘翔", coeff, names, prefer_gold=True, role="regression"),
        _eval_case("jilong", "吉隆", coeff, names, prefer_gold=False, role="smoke"),
        _eval_case("us_cn_ai", "中美AI", coeff, names, prefer_gold=False, role="smoke"),
    ]
    for h in HOLDOUT:
        cases.append(
            _eval_case(
                h["slug"], h["mark"], coeff, names,
                prefer_gold=False, role="holdout",
            )
        )

    by = {c["slug"]: c for c in cases}
    holdouts = [c for c in cases if c["role"] == "holdout"]
    smoke = [c for c in cases if c["role"] in {"regression", "smoke"}]

    dens_holdout_ok = all(
        c["micro_gold_density"] + 1e-12 >= GATE_DENS for c in holdouts
    )
    dens_smoke_ok = all(
        c["micro_gold_density"] + 1e-12
        >= float(R40_L2[c["slug"]]["micro"]) - DROP_EPS
        for c in smoke
    )
    lx_ok = by["liuxiang"]["cut_hits"]["7"] >= LIUXIANG_AT7_MIN

    r30_cite_hold = True
    for slug, prev in R30_COMP.items():
        s = by[slug]["compliance_summary"]
        if s["n_full_ok"] < prev["n_full_ok"] or s["axes_ok"] < prev["axes_ok"]:
            r30_cite_hold = False

    # holdout 增益：案均全合规题≥2／3 或 轴达标率≥85% 且可用密度均值≥0.35
    h_full = sum(c["compliance_summary"]["n_full_ok"] for c in holdouts)
    h_q = sum(c["compliance_summary"]["n_questions"] for c in holdouts) or 1
    h_axes_ok = sum(c["compliance_summary"]["axes_ok"] for c in holdouts)
    h_axes_tot = sum(c["compliance_summary"]["axes_total"] for c in holdouts) or 1
    h_usable = (
        sum(c["compliance_summary"]["mean_usable_cite_density"] for c in holdouts)
        / max(len(holdouts), 1)
    )
    holdout_cite_gain = (
        (h_full / h_q + 1e-12 >= 2.0 / 3.0)
        or (h_axes_ok / h_axes_tot + 1e-12 >= 0.85 and h_usable + 1e-12 >= 0.35)
    )
    holdout_cite_note = (
        f"全合规 {h_full}/{h_q}；轴 {h_axes_ok}/{h_axes_tot}；"
        f"可用密度均值 {h_usable:.0%}"
    )

    gate2_pass = bool(
        dens_holdout_ok and dens_smoke_ok and lx_ok
        and r30_cite_hold and holdout_cite_gain
    )

    bullets = [
        f"门槛②：**{'过' if gate2_pass else '未过'}**"
        f"（R30 重叠合规{'守' if r30_cite_hold else '掉'}；"
        f"holdout {holdout_cite_note}）。",
        f"密度：王虹 {by['wanghong']['micro_gold_density']:.0%}／"
        f"柬泰 {by['kh_th']['micro_gold_density']:.0%}／"
        f"AI171 {by['ai171']['micro_gold_density']:.0%}；"
        f"刘翔@7={by['liuxiang']['cut_hits']['7']}；"
        f"吉隆 {by['jilong']['micro_gold_density']:.0%}／"
        f"中美AI {by['us_cn_ai']['micro_gold_density']:.0%}。",
    ]
    for c in cases:
        s = c["compliance_summary"]
        prev = R30_COMP.get(c["slug"])
        if prev:
            bullets.append(
                f"{c['slug']}：全合规 {prev['n_full_ok']}→**{s['n_full_ok']}**／"
                f"{s['n_questions']}；轴 {prev['axes_ok']}→**{s['axes_ok']}**／"
                f"{s['axes_total']}；可用密度 **{s['mean_usable_cite_density']:.0%}**。"
            )
        else:
            bullets.append(
                f"{c['slug']}：全合规 **{s['n_full_ok']}**／{s['n_questions']}；"
                f"轴 **{s['axes_ok']}**／{s['axes_total']}；"
                f"可用密度 **{s['mean_usable_cite_density']:.0%}**。"
            )

    gate = {
        "dens_holdout_ok": dens_holdout_ok,
        "n_holdout_ge23": sum(
            1 for c in holdouts if c["micro_gold_density"] + 1e-12 >= GATE_DENS
        ),
        "dens_smoke_ok": dens_smoke_ok,
        "liuxiang_ok": lx_ok,
        "liuxiang_at7": by["liuxiang"]["cut_hits"]["7"],
        "r30_cite_hold": r30_cite_hold,
        "holdout_cite_gain": holdout_cite_gain,
        "holdout_cite_note": holdout_cite_note,
        "holdout_mean_usable": round(h_usable, 4),
        "gate2_pass": gate2_pass,
    }

    report = {
        "ticket": "R41-tree17-gain",
        "model": SUMMARY_MODEL,
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict_bullets": bullets,
        "gate": gate,
        "cases": cases,
        "r30_comp": R30_COMP,
        "r40_l2": R40_L2,
        "changes": [
            "EN verifiability cues for time/amount/bulletin",
            "close_read ordered by ver+rank; prompt prefers front accept/oppose",
            "usable_cite_density metric",
            "L2 density path untouched",
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
    (OUT / "R41_tree17_gain.json").write_text(
        json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R41_tree17_gain.md").write_text(_markdown(report), encoding="utf-8")
    print(
        f"R41 gate2={gate2_pass} dens_h={dens_holdout_ok} "
        f"r30_hold={r30_cite_hold} usable_h={h_usable:.0%} "
        f"wall={report['wall_s']}s",
        flush=True,
    )
    return 0 if gate2_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
