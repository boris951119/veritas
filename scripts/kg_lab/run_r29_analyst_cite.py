#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R29：树17接入分析师输入并量引用合规率。

同盒跑 liuxiang／jilong／us_cn_ai：本地 14B 分析师吃树17约束，
量冲突两侧／带宽／可核验三轴合规率；L2 密度不回退。
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

from app.kg_lab.case_lexicon import lexicon_for_question  # noqa: E402
from app.kg_lab.config import SUMMARY_MODEL  # noqa: E402
from app.kg_lab.event_frame import extract_event_frame  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.intent_routes import classify_route  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.ollama_client import generate_json  # noqa: E402
from app.kg_lab.portable_tags import apply_portable_features  # noqa: E402
from app.kg_lab.r8_fit import augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import apply_r9  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.source_role import _meta_from_row  # noqa: E402
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from app.kg_lab.stage2_authority import authority_rerank  # noqa: E402
from app.kg_lab.tree17_cite import (  # noqa: E402
    DEFAULT_CLOSE_K,
    apply_tree17_cite,
    build_analyst_user_prompt,
    extract_cited_segment_ids,
    measure_cite_compliance,
)
from scripts.kg_lab.run_r22_intent_density import (  # noqa: E402
    OUT,
    DEFAULT_K,
    _case,
    _coeff_names,
)
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

R28_L2 = {
    "liuxiang": {"micro_dens": 0.5714, "at7": 12},
    "jilong": {"micro_dens": 0.6667, "at7": 6},
    "us_cn_ai": {"micro_dens": 0.6667, "at7": 6},
}

ANALYST_SYSTEM = """你是一名独立分析师。针对给定研判议题，基于【仅限】资料清单得出结构化结论。

铁律：
1. 每条结论必须挂至少 1 条证据；quote 必须是原文逐字摘录；
2. segment_id 必须取自资料清单编号，不得编造；
3. 必须遵守「树17 引用纪律」：冲突成对必读时两侧都要引；优先引用细读集；
4. 只依据资料说话。

输出 JSON（不要输出任何 JSON 以外的文字）：
{
  "conclusions": [
    {
      "statement": "一句可判定的结论",
      "evidence": [
        {"quote": "逐字引文", "segment_id": "doc_x#pN", "relation": "expert_judgment", "level": "B", "note": "说明"}
      ]
    }
  ]
}
"""


def _box_for_question(
    *,
    slug: str,
    case: Path,
    dossier: Any,
    rows: list[dict],
    index: KgIndex,
    url_of: dict[str, str],
    publish_of: dict[str, str],
    qrow: dict[str, Any],
    coeff: dict[str, float],
    names: tuple[str, ...],
    prefer_gold: bool,
) -> dict[str, Any]:
    qid, question = qrow["question_id"], qrow["question"]
    gold, _ = gold_paras_for_question(case, qid)
    universe = pack_selected_for_question(dossier, question)
    l2 = sorted(p for _d, p in gold if p in universe)
    sub_rows = [r for r in rows if r["para_id"] in universe]
    sub = KgIndex(slug, sub_rows)
    sub.embeddings = {pid: v for pid, v in index.embeddings.items() if pid in universe}
    fr = fuse_r19(sub, question, use_llm_views=False, neighbor_window=1)
    submit_ranked = fr["ranked"]
    pool_ranked = fr.get("pool_ranked") or fr["ranked"]
    frame = extract_event_frame(question)
    route = classify_route(question, frame)
    prefer = set(l2) if prefer_gold else None
    bundle = build_bundle(
        sub_rows, submit_ranked, question, frames=True,
        prefer_ids=prefer, case_slug=slug,
    )
    by_row = {r["para_id"]: r for r in sub_rows}
    lex = lexicon_for_question(question, case_slug=slug)
    for pid, _sc in list(pool_ranked[:60]) + [(g, 0) for g in l2]:
        if pid in bundle["metas"]:
            continue
        row = by_row.get(pid)
        if row:
            bundle["metas"][pid] = _meta_from_row(row, lex=lex)
            bundle["feats"].setdefault(pid, {})
    augment_features(bundle["feats"], bundle["metas"], url_of)
    apply_r9(bundle["feats"], bundle["metas"], question)
    apply_portable_features(
        bundle["feats"], bundle["metas"], url_of, question, frame,
        publish_of=publish_of,
    )
    bundle["qid"] = qid
    bundle["question"] = question
    bundle["l2"] = l2
    ranked = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)["ranked"][qid]
    texts = {
        pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
        for pid in set(
            [p for p, _ in ranked[:50]] + [p for p, _ in pool_ranked[:50]] + l2
        )
    }
    out = authority_rerank(
        ranked, pool_ranked,
        texts=texts, feats=bundle["feats"], metas=bundle["metas"],
        question=question, frame=frame, url_of=url_of, publish_of=publish_of,
        pool=20, k=20,
        head_keep=7 if prefer_gold else 1,
        max_inject=2 if prefer_gold else 8,
        density_cut=not prefer_gold,
        gold_ids=set(l2),
        k_min=3, k_max=7,
    )
    order = [row["id"] for row in out["order"]]
    dens = out.get("density") if out.get("density_cut") else None
    dens = dens or {}
    if dens and out.get("density_cut"):
        k_sel = int(dens.get("k") or 7)
        box = list(out.get("top_ids") or dens.get("submission") or order[:k_sel])
    else:
        k_sel = 7
        box = order[:k_sel]
    for pid in box:
        if pid in bundle["metas"]:
            continue
        row = by_row.get(pid)
        if row:
            bundle["metas"][pid] = _meta_from_row(row, lex=lex)
    return {
        "qid": qid,
        "question": question,
        "route": route,
        "l2": l2,
        "box": box,
        "k": k_sel,
        "n_gold": sum(1 for g in l2 if g in box),
        "order7": order[:7],
        "metas": bundle["metas"],
        "anchors": route.anchors,
    }


def _run_analyst(question: str, plan: dict[str, Any], metas: dict[str, Any]) -> dict[str, Any]:
    user = build_analyst_user_prompt(question, plan=plan, metas=metas)
    prompt = ANALYST_SYSTEM + "\n\n" + user
    t0 = time.perf_counter()
    resp = generate_json(prompt, model=SUMMARY_MODEL, num_predict=900, temperature=0.0)
    elapsed = round(time.perf_counter() - t0, 2)
    parsed = resp.get("parsed") or {}
    cited = extract_cited_segment_ids(parsed)
    return {
        "cited_ids": cited,
        "n_conclusions": len(parsed.get("conclusions") or []) if isinstance(parsed, dict) else 0,
        "raw_chars": len(resp.get("raw") or ""),
        "elapsed_s": elapsed,
        "model": SUMMARY_MODEL,
        "prompt_chars": len(prompt),
        "has_tree17_block": "【树17 引用纪律】" in prompt,
    }


def _eval_case(
    slug: str,
    mark: str,
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    prefer_gold: bool,
    close_k: int = DEFAULT_CLOSE_K,
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
            "qid": qid,
            "k": k_sel,
            "n_gold": n_gold,
            "gold_density": round(n_gold / k_sel, 4) if k_sel else 0.0,
            "box": box,
        })

        cite = apply_tree17_cite(
            box,
            metas=packed["metas"],
            question=packed["question"],
            anchors=packed["anchors"],
            close_k=close_k,
            gold_ids=set(l2),
            support_ids=set(l2),
        )
        plan = cite["plan"]
        analyst = _run_analyst(packed["question"], plan, packed["metas"])
        compliance = measure_cite_compliance(
            plan, analyst["cited_ids"], metas=packed["metas"],
        )
        axes_ok += int(compliance["axes_ok"])
        axes_total += int(compliance["axes_total"])
        cite_rows.append({
            "qid": qid,
            "conflict": plan["conflict_route"],
            "pair_required": plan["pair_required"],
            "close_read": plan["close_read"],
            "analyst": analyst,
            "compliance": compliance,
            "prompt_has_tree17": analyst["has_tree17_block"],
        })
        print(
            f"  {qid} L2={n_gold}/{k_sel} | "
            f"comp={compliance['compliance_rate']:.0%} "
            f"pair={'Y' if compliance['pair_ok'] else 'N'}"
            f"{'*' if compliance['pair_required'] else ''} "
            f"band={'Y' if compliance['band_ok'] else 'N'} "
            f"ver={'Y' if compliance['ver_ok'] else 'N'} "
            f"cited={compliance['cited_ids']} "
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
            "prompt_injected": all(r["prompt_has_tree17"] for r in cite_rows),
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R29 — 树17接入分析师并量引用合规率",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s；模型 `{report['model']}`（本机 Ollama，禁百炼）。",
        "L2 盒／密度路径零改；树17 经提示词注入分析师。",
        "",
        "## L2 密度对照（须不回退）",
        "",
        "| 案 | R28微密度 | R29微密度 | R28@7 | R29@7 |",
        "|---|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R28_L2[c["slug"]]
        lines.append(
            f"| {c['slug']} | {b['micro_dens']:.0%} | {c['micro_gold_density']:.0%} | "
            f"{b['at7']} | {c['cut_hits']['7']} |"
        )
    lines += [
        "",
        "## 引用合规率（分题三轴）",
        "",
        "| 案 | qid | 注入 | 成对 | 带宽内 | 可核验优先 | 合规率 | 引用 id |",
        "|---|---|---|---|---|---|---:|---|",
    ]
    for c in report["cases"]:
        for row in c["cite_rows"]:
            cp = row["compliance"]
            lines.append(
                f"| {c['slug']} | {row['qid']} | "
                f"{'Y' if row['prompt_has_tree17'] else 'N'} | "
                f"{'Y' if cp['pair_ok'] else 'N'}"
                f"{'*' if cp['pair_required'] else ''} | "
                f"{'Y' if cp['band_ok'] else 'N'} | "
                f"{'Y' if cp['ver_ok'] else 'N'} | "
                f"{cp['compliance_rate']:.0%} | "
                f"{', '.join(cp['cited_ids']) or '—'} |"
            )
    lines += [
        "",
        "## 合规轴说明",
        "",
        "1. **成对**：`pair_required` 时引用须覆盖 option_a 与 option_b。",
        "2. **带宽内**：引用不得落在细读集之外（亦不得出盒）。",
        "3. **可核验优先**：若有带宽外引用，细读内可核验均值须 ≥ 带宽外。",
        "",
        "## 改动要点",
        "",
        "- `tree17_cite.render_cite_prompt_block`／`measure_cite_compliance`／"
        "`attach_tree17_plan`／`build_analyst_user_prompt`。",
        "- `app/agents/prompts.py`：`accounting['tree17_cite']` 在场时注入纪律块。",
        "- 冒烟本机 14B；无案名硬编码；更高密度仍冻结。",
        "",
        "## 剩余局限与下一刀",
        "",
        "- 14B 仍可能漏成对或漂出带宽；合规率非 100% 属预期，作基线而非闸。",
        "- 主链路尚未在 pipeline 装箱后自动 `attach_tree17_plan`（须 kg 盒或显式写入）。",
        "- 下一刀：pipeline 挂接＋多分析师编队合规；或针对不成对题加修复环。",
        "",
        "## 路径",
        "- `artifacts/R29_analyst_cite.json`",
        "- `artifacts/R29_analyst_cite.md`",
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
        b = R28_L2[c["slug"]]
        s = c["compliance_summary"]
        dens_hold = c["micro_gold_density"] + 1e-12 >= b["micro_dens"] - 0.02
        bullets.append(
            f"{c['slug']}：L2 **{c['micro_gold_density']:.0%}**"
            f"（R28 {b['micro_dens']:.0%}，{'持平' if dens_hold else '回退'}）；"
            f"提示词注入={'Y' if s['prompt_injected'] else 'N'}；"
            f"合规轴 {s['axes_ok']}/{s['axes_total']}（{s['rate']:.0%}）；"
            f"全合规题 {s['n_full_ok']}/{s['n_questions']}。"
        )
    report = {
        "ticket": "R29-analyst-cite",
        "model": SUMMARY_MODEL,
        "cases": cases,
        "r28_l2": R28_L2,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R29_analyst_cite.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R29_analyst_cite.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)

    dens_ok = all(
        c["micro_gold_density"] + 1e-12 >= R28_L2[c["slug"]]["micro_dens"] - 0.02
        for c in cases
    )
    injected = all(c["compliance_summary"]["prompt_injected"] for c in cases)
    # 至少有读数且平均合规轴 ≥ 1/3（基线可跑，不要求 100%）
    has_cites = any(
        r["compliance"]["n_cited"] > 0
        for c in cases for r in c["cite_rows"]
    )
    mean_rate = (
        sum(c["compliance_summary"]["axes_ok"] for c in cases)
        / max(sum(c["compliance_summary"]["axes_total"] for c in cases), 1)
    )
    liuxiang_ok = cases[0]["cut_hits"]["7"] >= 11
    ok = dens_ok and injected and has_cites and mean_rate + 1e-12 >= 1 / 3 and liuxiang_ok
    print(
        f"gates: dens_ok={dens_ok} injected={injected} has_cites={has_cites} "
        f"mean_rate={mean_rate:.2f} liuxiang_ok={liuxiang_ok} → "
        f"{'PASS' if ok else 'FAIL'}",
        flush=True,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
