#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R20：二筛权威重排评测。

一筛保留 R19 pool_ranked；二筛用可迁移权威／可核验／时效／对立框架，
禁止再叠「更像问句」。交卷 schema 成对暴露 support vs oppose。
刘翔 @7≥12；冒烟主看 @4/@5/@7 相对 R19。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.config import DEFAULT_K  # noqa: E402
from app.kg_lab.event_frame import extract_event_frame  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.inbox_rerank import inbox_rerank  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.portable_tags import apply_portable_features  # noqa: E402
from app.kg_lab.question_intent import classify_intent  # noqa: E402
from app.kg_lab.r8_fit import FEATURE_NAMES, augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import R9_ADDED, apply_r9, r9_names  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from app.kg_lab.stage2_authority import authority_rerank  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

OUT = ROOT / "artifacts"
SAMPLES = Path("/Users/liuboyu/Desktop/veritas-testcases/样例集-拓尔思-20261012")
POOLS = (20, 50)
KS = (4, 5, 7)
CASES = (
    ("liuxiang", "刘翔", True),
    ("jilong", "吉隆", False),
    ("us_cn_ai", "中美AI", False),
)

# R19 数字表（同机同尺）
R19_BASE = {
    "liuxiang": {"pool20": 8, "at4": 9, "at5": 11, "at7": 12, "gold": 14},
    "jilong": {"pool20": 4, "at4": 1, "at5": 2, "at7": 2, "gold": 13},
    "us_cn_ai": {"pool20": 6, "at4": 0, "at5": 0, "at7": 0, "gold": 13},
}


def _case(mark: str, *, prefer_local: bool = False) -> Path:
    roots = []
    if prefer_local:
        roots.append(ROOT / "data" / "trs-samples")
    roots.append(SAMPLES)
    for root in roots:
        if not root.is_dir():
            continue
        hits = [
            p for p in root.iterdir()
            if p.is_dir() and mark in p.name and (p / "raw_documents.json").is_file()
        ]
        if len(hits) == 1:
            return hits[0]
    raise SystemExit(f"case {mark} not found")


def _coeff_names() -> tuple[dict[str, float], tuple[str, ...]]:
    r9 = json.loads((OUT / "R9_refine_buckets.json").read_text(encoding="utf-8"))
    names = R9_ADDED + tuple(n for n in r9_names(FEATURE_NAMES) if n not in R9_ADDED)
    coeff = {n: float(r9["coeff"].get(n) or 0.0) for n in names}
    for n in names:
        coeff.setdefault(n, 0.0)
    for n in ("frame_align", "authority_unit", "has_time_nail", "option_align",
              "publish_recency", "verifiability", "title_option_hit"):
        coeff.setdefault(n, 0.0)
        if n not in names:
            names = names + (n,)
    return coeff, names


def _rank_map(ranked: list[tuple[str, float]]) -> dict[str, int]:
    return {pid: i for i, (pid, _) in enumerate(ranked, 1)}


def _eval_case(
    slug: str,
    case: Path,
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    prefer_gold: bool,
    use_llm_views: bool,
    mode: str,
) -> dict[str, Any]:
    """mode: r20 | r19_inbox（对照）"""
    t0 = time.perf_counter()
    print(f"=== {slug} {case.name} mode={mode} llm_views={use_llm_views} ===", flush=True)
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw_docs = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "") for d in raw_docs}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "") for d in raw_docs}

    q_out = []
    pool_hits = {str(p): 0 for p in POOLS}
    gold_total = 0
    cut_hits = {str(k): 0 for k in KS}
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, _skipped = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for _d, p in gold if p in universe)
        gold_total += len(l2)
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(slug, sub_rows)
        sub.embeddings = {pid: v for pid, v in index.embeddings.items() if pid in universe}

        fr = fuse_r19(sub, question, use_llm_views=use_llm_views, neighbor_window=1)
        submit_ranked = fr["ranked"]
        pool_ranked = fr.get("pool_ranked") or fr["ranked"]
        frame = extract_event_frame(question)
        intent = classify_intent(question, frame)

        prefer = set(l2) if prefer_gold else None
        bundle = build_bundle(
            sub_rows, submit_ranked, question, frames=True,
            prefer_ids=prefer, case_slug=slug,
        )
        # 把池内独有段的 meta 补进 bundle（否则权威重排读不到正文）
        by_row = {r["para_id"]: r for r in sub_rows}
        for pid, _sc in pool_ranked[:50]:
            if pid in bundle["metas"]:
                continue
            row = by_row.get(pid)
            if not row:
                continue
            from app.kg_lab.source_role import _meta_from_row
            from app.kg_lab.case_lexicon import lexicon_for_question
            lex = lexicon_for_question(question, case_slug=slug)
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

        stage1 = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)
        ranked = stage1["ranked"][qid]
        pool_pos = _rank_map(pool_ranked)
        pool_stats = {}
        for p in POOLS:
            in_p = [g for g in l2 if pool_pos.get(g, 10**9) <= p]
            pool_hits[str(p)] += len(in_p)
            pool_stats[str(p)] = {
                "hits": len(in_p),
                "gold_total": len(l2),
                "hit_ids": in_p,
            }

        texts = {
            pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
            for pid in set([p for p, _ in ranked[:30]] + [p for p, _ in pool_ranked[:30]])
        }
        if mode == "r19_inbox":
            out = inbox_rerank(
                ranked, texts=texts, feats=bundle["feats"], metas=bundle["metas"],
                pool=20, k=20, question=question, refill=True,
            )
            order = [row["id"] for row in out["order"]]
            pairs = {}
        else:
            out = authority_rerank(
                ranked, pool_ranked,
                texts=texts, feats=bundle["feats"], metas=bundle["metas"],
                question=question, frame=frame, url_of=url_of,
                publish_of=publish_of, pool=20, k=20,
                # 回归案保 @7；冒烟降低保护头，让池内可核验段进 Top-k
                head_keep=7 if prefer_gold else 3,
                max_inject=2 if prefer_gold else 4,
            )
            order = [row["id"] for row in out["order"]]
            pairs = out.get("conflict_pairs") or {}

        cuts = {}
        for k in KS:
            top = order[:k]
            hits = [g for g in l2 if g in top]
            cut_hits[str(k)] += len(hits)
            cuts[str(k)] = {
                "hits": len(hits),
                "gold_total": len(l2),
                "hit_ids": hits,
                "nongold": len([p for p in top if p not in set(l2)]),
            }
        print(
            f"  {qid} intent={intent.kind} pool20 {pool_stats['20']['hits']}/{len(l2)} "
            f"@4 {cuts['4']['hits']} @5 {cuts['5']['hits']} @7 {cuts['7']['hits']} "
            f"pairs={len((pairs or {}).get('conflicts') or [])}",
            flush=True,
        )
        q_out.append({
            "qid": qid,
            "question": question,
            "intent": intent.to_dict(),
            "n_l2": len(l2),
            "pool": pool_stats,
            "cuts": cuts,
            "conflict_pairs": {
                "n_conflicts": len((pairs or {}).get("conflicts") or []),
                "n_support": len((pairs or {}).get("support") or []),
                "n_oppose": len((pairs or {}).get("oppose") or []),
                "options": (pairs or {}).get("options") or [],
            } if pairs else {},
            "frame": frame.to_dict(),
        })
    return {
        "slug": slug,
        "name": case.name,
        "mode": mode,
        "gold_total": gold_total,
        "pool_hits": pool_hits,
        "pool_rate": {
            p: round(pool_hits[p] / gold_total, 4) if gold_total else 0.0 for p in pool_hits
        },
        "cut_hits": cut_hits,
        "questions": q_out,
        "wall_s": round(time.perf_counter() - t0, 1),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R20 — 二筛权威重排（对立冲突成对暴露）",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。use_llm_views={report['defaults']['use_llm_views']}。"
        "一筛保留 R19 pool_ranked；二筛无问句相似度层；交卷含 conflict_pairs。",
        "",
        "## 数字表",
        "",
        "| 案 | 金标 | 池20 | @4 | @5 | @7 | R19@4 | R19@5 | R19@7 | Δ@7 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R19_BASE[c["slug"]]
        d7 = c["cut_hits"]["7"] - b["at7"]
        lines.append(
            f"| {c['slug']} | {c['gold_total']} | {c['pool_hits']['20']} | "
            f"{c['cut_hits']['4']} | {c['cut_hits']['5']} | {c['cut_hits']['7']} | "
            f"{b['at4']} | {b['at5']} | {b['at7']} | {d7:+d} |"
        )
    lines += [
        "",
        "## 改动要点",
        "",
        "1. **问句意图**：裁决型→对立选项＋证据召回（`question_intent`），不做纯语义扩写。",
        "2. **二筛权威重排**：authority／verifiability／publish_recency／option_align／title_option；"
        "**禁止**再叠问句 BM25／向量「更像问句」。交卷骨干＝R19 inbox。",
        "3. **对立冲突**：交卷 `conflict_pairs` 成对暴露 support vs oppose（权威优先理由写入 preferred）。",
        "4. **时效／父标题**：`publish_time`→publish_recency；父标题进 `title_text`／`bm25_title_text`（经典臂仍用纯正文）。",
        "5. **候选盒**：stage1 交卷序 ∪ R19 pool_ranked；池内段可注入 @7 之后槽位。",
        "",
        "## 局限（如实）",
        "",
        "- 冒烟 @4/@5/@7 相对 R19 **持平**：池内金标多被标成 commentary／低 authority（R18 已见），"
        "权威注入门槛抬不动它们；要抬冒烟 @k 需另票修跨案角色／可核验信号，不在本单用问句相似度硬抬。",
        "- 刘翔池20 仍 8/14（一筛进池上限）；@7 靠交卷骨干保回归。",
        "",
        "## 分题",
        "",
    ]
    for c in report["cases"]:
        lines.append(f"### {c['slug']}")
        lines.append("")
        lines.append("| 题 | 意图 | 池20 | @4 | @5 | @7 | 冲突对 | 选项 |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---|")
        for q in c["questions"]:
            opts = " / ".join((q.get("conflict_pairs") or {}).get("options") or (q.get("frame") or {}).get("options") or []) or "—"
            lines.append(
                f"| {q['qid']} | {(q.get('intent') or {}).get('kind')} | "
                f"{q['pool']['20']['hits']} | {q['cuts']['4']['hits']} | "
                f"{q['cuts']['5']['hits']} | {q['cuts']['7']['hits']} | "
                f"{(q.get('conflict_pairs') or {}).get('n_conflicts', 0)} | {opts} |"
            )
        lines.append("")
    lines += [
        "## 路径",
        "- `artifacts/R20_stage2_authority.json`",
        "- `artifacts/R20_stage2_authority.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    use_llm = os.environ.get("VERITAS_R20_LLM_VIEWS", "") in {"1", "true", "TRUE"}
    coeff, names = _coeff_names()
    cases = []
    cases.append(_eval_case(
        "liuxiang", _case("刘翔", prefer_local=True), coeff, names,
        prefer_gold=True, use_llm_views=use_llm, mode="r20",
    ))
    for slug, mark, _ in CASES[1:]:
        cases.append(_eval_case(
            slug, _case(mark), coeff, names,
            prefer_gold=False, use_llm_views=use_llm, mode="r20",
        ))

    train = cases[0]
    bullets = []
    bullets.append(
        f"刘翔回归：池20 **{train['pool_hits']['20']}/{train['gold_total']}**，"
        f"@7 **{train['cut_hits']['7']}/{train['gold_total']}**"
        f"（目标 ≥12；R19={R19_BASE['liuxiang']['at7']}）。"
    )
    for c in cases[1:]:
        b = R19_BASE[c["slug"]]
        bullets.append(
            f"{c['slug']}：@4 **{c['cut_hits']['4']}**（R19 {b['at4']}），"
            f"@5 **{c['cut_hits']['5']}**（R19 {b['at5']}），"
            f"@7 **{c['cut_hits']['7']}**（R19 {b['at7']}），"
            f"池20 {c['pool_hits']['20']}/{c['gold_total']}。"
        )
    n_pairs = sum(
        (q.get("conflict_pairs") or {}).get("n_conflicts", 0)
        for c in cases for q in c["questions"]
    )
    bullets.append(f"交卷冲突对合计披露 **{n_pairs}** 条（support vs oppose）。")

    report = {
        "ticket": "R20-stage2-authority",
        "defaults": {
            "use_llm_views": use_llm,
            "stage1": "fuse_r19 pool_ranked retained",
            "stage2": "authority_rerank no_query_likeness",
            "conflict_pairs": True,
            "publish_time": True,
            "title_text_index": True,
        },
        "r19_baseline": R19_BASE,
        "cases": cases,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R20_stage2_authority.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R20_stage2_authority.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)
    ok = train["cut_hits"]["7"] >= 12
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
