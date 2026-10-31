#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R30：修分析师带宽外引用。

细读带宽与盒 k 对齐＋越界剪枝／重抽；三案重测合规；L2 不掉。
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
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.slices import union_pack_ids  # noqa: E402

R29_L2 = {
    "liuxiang": {"micro_dens": 0.5714, "at7": 12},
    "jilong": {"micro_dens": 0.6667, "at7": 6},
    "us_cn_ai": {"micro_dens": 0.6667, "at7": 6},
}

# R29 合规基线（全合规题数／轴）
R29_COMP = {
    "liuxiang": {"axes_ok": 7, "axes_total": 9, "n_full_ok": 1, "n_q": 3},
    "jilong": {"axes_ok": 9, "axes_total": 9, "n_full_ok": 3, "n_q": 3},
    "us_cn_ai": {"axes_ok": 9, "axes_total": 9, "n_full_ok": 3, "n_q": 3},
}


def _run_analyst_banded(
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
        "prompt_chars": len(prompt),
        "has_tree17_block": "【树17 引用纪律】" in prompt,
        "align_to_box": bool(plan.get("align_to_box")),
        "close_k_effective": plan.get("close_k_effective"),
        "box_k": len(plan.get("box") or []),
    }


def _eval_case(
    slug: str,
    mark: str,
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    prefer_gold: bool,
) -> dict[str, Any]:
    case = _case(mark, prefer_local=(slug == "liuxiang"))
    print(f"=== eval {slug} ===", flush=True)
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "") for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "") for d in raw}

    dens_rows: list[dict[str, Any]] = []
    cite_rows: list[dict[str, Any]] = []
    sum_g = sum_k = at7 = gold_total = 0
    axes_ok = axes_total = 0

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
        gold_total += len(l2)
        at7 += sum(1 for g in l2 if g in packed["order7"])
        dens_rows.append({
            "qid": qid, "k": k_sel, "n_gold": n_gold,
            "gold_density": round(n_gold / k_sel, 4) if k_sel else 0.0,
            "box": box,
        })

        cite = apply_tree17_cite(
            box,
            metas=packed["metas"],
            question=packed["question"],
            anchors=packed["anchors"],
            align_to_box=True,  # R30：带宽＝盒
            gold_ids=set(l2),
            support_ids=set(l2),
        )
        plan = cite["plan"]
        analyst = _run_analyst_banded(packed["question"], plan, packed["metas"])
        compliance = analyst["compliance"]
        axes_ok += int(compliance["axes_ok"])
        axes_total += int(compliance["axes_total"])
        cite_rows.append({
            "qid": qid,
            "conflict": plan["conflict_route"],
            "pair_required": plan["pair_required"],
            "close_read": plan["close_read"],
            "align_to_box": plan.get("align_to_box"),
            "close_k_effective": plan.get("close_k_effective"),
            "box_k": len(box),
            "analyst": {
                k: analyst[k] for k in (
                    "cited_ids", "cited_ids_raw", "oob_before",
                    "repaired_by_regen", "n_dropped_evidence",
                    "elapsed_s", "has_tree17_block", "compliance_raw",
                )
            },
            "compliance": compliance,
            "prompt_has_tree17": analyst["has_tree17_block"],
        })
        print(
            f"  {qid} L2={n_gold}/{k_sel} close={plan['close_k_effective']}/{len(box)} | "
            f"comp={compliance['compliance_rate']:.0%} "
            f"(raw={analyst['compliance_raw']['compliance_rate']:.0%}) "
            f"band={'Y' if compliance['band_ok'] else 'N'} "
            f"oob_raw={analyst['oob_before']} "
            f"regen={analyst['repaired_by_regen']} "
            f"({analyst['elapsed_s']}s)",
            flush=True,
        )

    micro = sum_g / sum_k if sum_k else 0.0
    return {
        "slug": slug,
        "micro_gold_density": round(micro, 4),
        "sum_gold_in_boxes": sum_g,
        "sum_k": sum_k,
        "cut_hits": {"7": at7},
        "gold_total": gold_total,
        "density_rows": dens_rows,
        "cite_rows": cite_rows,
        "compliance_summary": {
            "axes_ok": axes_ok,
            "axes_total": axes_total,
            "rate": round(axes_ok / axes_total, 4) if axes_total else None,
            "n_full_ok": sum(1 for r in cite_rows if r["compliance"]["ok"]),
            "n_questions": len(cite_rows),
            "n_band_ok": sum(1 for r in cite_rows if r["compliance"]["band_ok"]),
            "prompt_injected": all(r["prompt_has_tree17"] for r in cite_rows),
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R30 — 修分析师带宽外引用",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s；模型 `{report['model']}`（本机，禁百炼）。",
        "策略：细读带宽与盒 k 对齐 + 越界证据机械剪枝／必要时一轮重抽。",
        "",
        "## L2 密度（须不回退）",
        "",
        "| 案 | R29微密度 | R30微密度 | R29@7 | R30@7 |",
        "|---|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R29_L2[c["slug"]]
        lines.append(
            f"| {c['slug']} | {b['micro_dens']:.0%} | {c['micro_gold_density']:.0%} | "
            f"{b['at7']} | {c['cut_hits']['7']} |"
        )
    lines += [
        "",
        "## 合规对照 R29",
        "",
        "| 案 | R29全合规题 | R30全合规题 | R29轴 | R30轴 | 带宽题OK |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        prev = R29_COMP[c["slug"]]
        s = c["compliance_summary"]
        lines.append(
            f"| {c['slug']} | {prev['n_full_ok']}/{prev['n_q']} | "
            f"{s['n_full_ok']}/{s['n_questions']} | "
            f"{prev['axes_ok']}/{prev['axes_total']} | "
            f"{s['axes_ok']}/{s['axes_total']} | "
            f"{s['n_band_ok']}/{s['n_questions']} |"
        )
    lines += [
        "",
        "## 分题",
        "",
        "| 案 | qid | 盒k | 细读k | 带宽 | 合规率 | 原始越界 | 重抽 |",
        "|---|---|---:|---:|---|---:|---|---|",
    ]
    for c in report["cases"]:
        for row in c["cite_rows"]:
            cp = row["compliance"]
            a = row["analyst"]
            lines.append(
                f"| {c['slug']} | {row['qid']} | {row['box_k']} | "
                f"{row['close_k_effective']} | "
                f"{'Y' if cp['band_ok'] else 'N'} | "
                f"{cp['compliance_rate']:.0%} | "
                f"{', '.join(a['oob_before']) or '—'} | "
                f"{'Y' if a['repaired_by_regen'] else 'N'} |"
            )
    lines += [
        "",
        "## 改动要点",
        "",
        "1. `plan_close_read(..., align_to_box=True)`：细读 k＝盒 k。",
        "2. 提示词：segment_id 只许细读集；资料清单默认不渲染非细读。",
        "3. `filter_payload_to_close_band`／`repair_cites_to_band`：剪枝＋可选重抽。",
        "4. L2 进盒路径零改；更高密度仍冻结。",
        "",
        "## 剩余局限",
        "",
        "- 对齐后细读＝整盒，可核验「优先排序」披露变弱（仍保留标签）。",
        "- 重抽仅在剪空／成对失败时触发，省墙钟。",
        "- 主 pipeline 自动 attach 仍待下一刀。",
        "",
        "## 路径",
        "- `artifacts/R30_cite_band.json`",
        "- `artifacts/R30_cite_band.md`",
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
    for c in cases:
        b = R29_L2[c["slug"]]
        prev = R29_COMP[c["slug"]]
        s = c["compliance_summary"]
        dens_hold = c["micro_gold_density"] + 1e-12 >= b["micro_dens"] - 0.02
        full_up = s["n_full_ok"] >= prev["n_full_ok"]
        bullets.append(
            f"{c['slug']}：L2 **{c['micro_gold_density']:.0%}**"
            f"（{'持平' if dens_hold else '回退'}）；"
            f"全合规题 {prev['n_full_ok']}→**{s['n_full_ok']}**"
            f"／{s['n_questions']}（{'升或持' if full_up else '掉'}）；"
            f"轴 {prev['axes_ok']}/{prev['axes_total']}→"
            f"**{s['axes_ok']}/{s['axes_total']}**；"
            f"带宽题 {s['n_band_ok']}/{s['n_questions']}。"
        )
    report = {
        "ticket": "R30-cite-band",
        "model": SUMMARY_MODEL,
        "cases": cases,
        "r29_l2": R29_L2,
        "r29_comp": R29_COMP,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R30_cite_band.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R30_cite_band.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)

    dens_ok = all(
        c["micro_gold_density"] + 1e-12 >= R29_L2[c["slug"]]["micro_dens"] - 0.02
        for c in cases
    )
    lx = next(c for c in cases if c["slug"] == "liuxiang")
    others = [c for c in cases if c["slug"] != "liuxiang"]
    lx_up = lx["compliance_summary"]["n_full_ok"] > R29_COMP["liuxiang"]["n_full_ok"]
    lx_band = lx["compliance_summary"]["n_band_ok"] == lx["compliance_summary"]["n_questions"]
    others_hold = all(
        c["compliance_summary"]["n_full_ok"] >= R29_COMP[c["slug"]]["n_full_ok"]
        and c["compliance_summary"]["axes_ok"] >= R29_COMP[c["slug"]]["axes_ok"]
        for c in others
    )
    liuxiang_at7 = lx["cut_hits"]["7"] >= 11
    ok = dens_ok and lx_up and lx_band and others_hold and liuxiang_at7
    print(
        f"gates: dens_ok={dens_ok} lx_up={lx_up} lx_band={lx_band} "
        f"others_hold={others_hold} liuxiang_at7={liuxiang_at7} → "
        f"{'PASS' if ok else 'FAIL'}",
        flush=True,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
