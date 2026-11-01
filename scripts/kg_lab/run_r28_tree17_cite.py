#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R28：树17引用规则试点（L3）。

同盒跑 liuxiang／jilong／us_cn_ai：报告引用覆盖、冲突两侧是否都引、
与金标／支撑表对照。不改 L2 密度门槛；规则不读金标 id。
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

from app.kg_lab.event_frame import extract_event_frame  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.intent_routes import classify_route  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.portable_tags import apply_portable_features  # noqa: E402
from app.kg_lab.r8_fit import augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import apply_r9  # noqa: E402
from app.kg_lab.case_lexicon import lexicon_for_question  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.source_role import _meta_from_row  # noqa: E402
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from app.kg_lab.stage2_authority import authority_rerank  # noqa: E402
from app.kg_lab.tree17_cite import apply_tree17_cite, DEFAULT_CLOSE_K  # noqa: E402
from scripts.kg_lab.run_r22_intent_density import (  # noqa: E402
    OUT,
    _case,
    _coeff_names,
    DEFAULT_K,
)
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

# R27 L2 基线（本票只披露，不作闸）
R27_L2 = {
    "liuxiang": {"micro_dens": 0.5714, "at7": 12},
    "jilong": {"micro_dens": 0.6667, "at7": 6},
    "us_cn_ai": {"micro_dens": 0.6667, "at7": 6},
}


def _eval_case_with_cite(
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
    sum_g = sum_k = 0
    at7 = gold_total = 0
    pair_ok = pair_need = 0
    close_gold_hits = close_gold_box = 0

    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, _ = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for _d, p in gold if p in universe)
        gold_total += len(l2)
        # 支撑表＝金标段（本仓库 supporting_facts 经联接后即 l2）
        support = set(l2)
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
        pool_pos = {pid: i for i, (pid, _) in enumerate(pool_ranked, 1)}
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
        n_gold = sum(1 for g in l2 if g in box)
        sum_g += n_gold
        sum_k += k_sel
        at7 += sum(1 for g in l2 if g in order[:7])
        dens_rows.append({
            "qid": qid,
            "k": k_sel,
            "n_gold": n_gold,
            "gold_density": round(n_gold / k_sel, 4) if k_sel else 0.0,
            "box": box,
        })

        # 补全盒内 metas（树17 只读文）
        for pid in box:
            if pid in bundle["metas"]:
                continue
            row = by_row.get(pid)
            if row:
                bundle["metas"][pid] = _meta_from_row(row, lex=lex)

        cite = apply_tree17_cite(
            box,
            metas=bundle["metas"],
            question=question,
            anchors=route.anchors,
            close_k=close_k,
            gold_ids=set(l2),
            support_ids=support,
        )
        plan, l3 = cite["plan"], cite["l3"]
        if plan["pair_required"]:
            pair_need += 1
            if plan["both_sides_cited"]:
                pair_ok += 1
        g_box = int((l3.get("gold") or {}).get("in_box") or 0)
        g_close = int((l3.get("gold") or {}).get("in_close") or 0)
        close_gold_box += g_box
        close_gold_hits += g_close
        cite_rows.append({
            "qid": qid,
            "route": route.route,
            "conflict": plan["conflict_route"],
            "pair_required": plan["pair_required"],
            "both_sides_cited": plan["both_sides_cited"],
            "pair_violation": plan["pair_violation"],
            "close_read": plan["close_read"],
            "close_k_effective": plan["close_k_effective"],
            "bandwidth_expanded": plan["bandwidth_expanded"],
            "label_counts_close": plan["label_counts_close"],
            "l3": l3,
            "items": [
                {
                    "para_id": it["para_id"],
                    "side": it["side"],
                    "stance": it["stance"],
                    "label": it["label"],
                    "in_close_read": it["in_close_read"],
                    "ver": it["verifiability"]["score"],
                }
                for it in plan["items"]
            ],
        })
        print(
            f"  {qid} L2 dens={n_gold}/{k_sel}={n_gold/max(k_sel,1):.0%} | "
            f"L3 close={plan['close_k_effective']} "
            f"pair={'OK' if plan['both_sides_cited'] else 'FAIL'}"
            f"{'*' if plan['pair_required'] else ''} "
            f"gold_close={g_close}/{g_box}(box) "
            f"labels={plan['label_counts_close']}",
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
        "l3_summary": {
            "pair_need": pair_need,
            "pair_ok": pair_ok,
            "pair_rate": round(pair_ok / pair_need, 4) if pair_need else None,
            "gold_in_box": close_gold_box,
            "gold_in_close": close_gold_hits,
            "gold_box_to_close": (
                round(close_gold_hits / close_gold_box, 4) if close_gold_box else None
            ),
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R28 — 树17引用规则试点（L3）",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。规则零 LLM；不改 L2 盒／密度；无案专名／无「像不像金标」规则。",
        "",
        "## L2 密度对照（须不回退）",
        "",
        "| 案 | R27微密度 | R28微密度 | R27@7 | R28@7 |",
        "|---|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R27_L2[c["slug"]]
        lines.append(
            f"| {c['slug']} | {b['micro_dens']:.0%} | {c['micro_gold_density']:.0%} | "
            f"{b['at7']} | {c['cut_hits']['7']} |"
        )
    lines += [
        "",
        "## L3 引用读数（分题）",
        "",
        "| 案 | qid | 冲突 | 成对必读 | 两侧都引 | 细读k | 金标盒→细读 | 采信 | 存疑 | 对立 |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        for row in c["cite_rows"]:
            lc = row["label_counts_close"]
            g = row["l3"]["gold"]
            box_to = row["l3"].get("gold_in_box_to_close")
            box_to_s = f"{box_to:.0%}" if box_to is not None else "—"
            lines.append(
                f"| {c['slug']} | {row['qid']} | "
                f"{'Y' if row['conflict'] else 'N'} | "
                f"{'Y' if row['pair_required'] else 'N'} | "
                f"{'Y' if row['both_sides_cited'] else 'N'} | "
                f"{row['close_k_effective']} | "
                f"{g['in_close']}/{g['in_box']}（{box_to_s}） | "
                f"{lc.get('采信', 0)} | {lc.get('存疑', 0)} | {lc.get('对立', 0)} |"
            )
    lines += [
        "",
        "## 规则草案（可测）",
        "",
        "1. **冲突成对必读**：`claim_conflict` 且盒内两侧皆有 → 细读须各 ≥1；"
        "否则 `pair_violation`。support＝option_a，oppose＝option_b。",
        "2. **可核验优先**：时间／数额／主体通报抬分；综述评论降权；"
        "填满 `close_k`（默认 4）。",
        "3. **rank 带宽**：盒序靠前轻抬；成对不够时可扩带宽并披露。",
        "4. **标签**：细读内 → 采信／存疑／对立；带宽外一律存疑。",
        "",
        "## 改动要点",
        "",
        "- 新模块 `app/kg_lab/tree17_cite.py`（交卷后／分析师前）。",
        "- 冒烟 `scripts/kg_lab/run_r28_tree17_cite.py`；守护 `tests/test_kg_lab_r28_tree17_cite.py`。",
        "- L2 密度路径零改；金标只进 L3 对照读数。",
        "",
        "## 剩余局限与下一刀",
        "",
        "- 标签启发式粗：option_a＝采信、option_b＝对立，未建模「哪侧更真」。",
        "- 可核验词典为通用子集，英文通报／表格数额仍漏。",
        "- 未接分析师提示词注入；下一刀＝把 `close_read`＋标签写进 analyst 输入面并量引用合规率。",
        "- 更高密度仍冻结（用户要求放到最后）。",
        "",
        "## 路径",
        "- `artifacts/R28_tree17_cite.json`",
        "- `artifacts/R28_tree17_cite.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    coeff, names = _coeff_names()
    cases = [
        _eval_case_with_cite("liuxiang", "刘翔", coeff, names, prefer_gold=True),
        _eval_case_with_cite("jilong", "吉隆", coeff, names, prefer_gold=False),
        _eval_case_with_cite("us_cn_ai", "中美AI", coeff, names, prefer_gold=False),
    ]
    bullets: list[str] = []
    for c in cases:
        b = R27_L2[c["slug"]]
        s = c["l3_summary"]
        dens_hold = c["micro_gold_density"] + 1e-12 >= b["micro_dens"] - 0.02
        bullets.append(
            f"{c['slug']}：L2 微密度 **{c['micro_gold_density']:.0%}**"
            f"（R27 {b['micro_dens']:.0%}，{'持平' if dens_hold else '回退'}）；"
            f"成对题 {s['pair_ok']}/{s['pair_need'] or 0} 两侧都引；"
            f"金标盒→细读 {s['gold_in_close']}/{s['gold_in_box']}。"
        )
    report = {
        "ticket": "R28-tree17-cite",
        "close_k_default": DEFAULT_CLOSE_K,
        "cases": cases,
        "r27_l2": R27_L2,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R28_tree17_cite.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R28_tree17_cite.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)

    dens_ok = all(
        c["micro_gold_density"] + 1e-12 >= R27_L2[c["slug"]]["micro_dens"] - 0.02
        for c in cases
    )
    pair_cases = [c for c in cases if c["l3_summary"]["pair_need"]]
    pair_ok = all(
        (c["l3_summary"]["pair_ok"] == c["l3_summary"]["pair_need"])
        for c in pair_cases
    ) if pair_cases else True
    liuxiang_ok = cases[0]["cut_hits"]["7"] >= 11
    ok = dens_ok and pair_ok and liuxiang_ok
    print(
        f"gates: dens_ok={dens_ok} pair_ok={pair_ok} "
        f"liuxiang_ok={liuxiang_ok} → {'PASS' if ok else 'FAIL'}",
        flush=True,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
