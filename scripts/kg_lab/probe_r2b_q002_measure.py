#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2b：q_002 金标盲区只量探针（只读；不改召回逻辑）。"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bm25 import _tokens  # noqa: E402, PLC2701
from app.core.citation_check import normalize  # noqa: E402
from app.kg_lab.graph import load_adjacency  # noqa: E402
from app.kg_lab.index_build import (  # noqa: E402
    KgIndex,
    build_corpus_rows,
    keyword_expand_query,
)
from app.kg_lab.recall_arms import (  # noqa: E402
    arm_embedding,
    arm_q_bm25,
    arm_rrf,
    arm_rrf_hop,
    arm_summary_bm25,
)
from app.kg_lab.slices import (  # noqa: E402
    pack_selected_for_question,
    safe_name,
    segment_map,
    union_pack_ids,
)
from app.kg_lab.summarize import load_summary  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

CASE_FILTER = "刘翔"
QID = "q_002"
RANK_K = 50
FOCUS_TERMS = ("不愿走", "未放行", "11年", "十一年", "不想走", "没让我走", "买断", "放行")


def _overlap(a: str, b: str) -> dict[str, Any]:
    ta = set(_tokens(a or ""))
    tb = set(_tokens(b or ""))
    if not ta or not tb:
        return {
            "n_q_tok": len(ta), "n_doc_tok": len(tb),
            "n_inter": 0, "jaccard": 0.0, "cover_q": 0.0,
            "char_substr_hits": [],
        }
    inter = ta & tb
    # 粗字面：问句里 ≥2 字片是否落在正文
    hits = []
    qa = normalize(a or "")
    qb = normalize(b or "")
    for i in range(len(qa) - 1):
        gram = qa[i:i + 2]
        if gram and gram in qb and gram not in hits:
            hits.append(gram)
        if len(hits) >= 12:
            break
    return {
        "n_q_tok": len(ta),
        "n_doc_tok": len(tb),
        "n_inter": len(inter),
        "jaccard": round(len(inter) / len(ta | tb), 4),
        "cover_q": round(len(inter) / len(ta), 4),
        "char_substr_hits": hits,
        "n_char_bigram_hits": len(hits),
    }


def _snip(text: str, n: int = 80) -> dict[str, str]:
    t = (text or "").replace("\n", " ").strip()
    if len(t) <= 2 * n:
        return {"head": t, "tail": "", "n_chars": len(t)}
    return {"head": t[:n], "tail": t[-n:], "n_chars": len(t)}


def _rank_of(ranked_ids: list[str], pid: str) -> int | None:
    try:
        return ranked_ids.index(pid) + 1  # 1-based
    except ValueError:
        return None


def _expand_extras(question: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """复现 keyword_expand_query 入选词（只读拆解）。"""
    from app.kg_lab.index_build import keyword_expand_query as _kx
    q2 = _kx(question, rows)
    q = (question or "").strip()
    # 粗拆：expand 结果去掉原问后的 token 串
    extras_str = q2[len(q):].strip() if q2.startswith(q) else q2
    # 从 rows 里标出实际可能被选中的 entities/keywords（与实现同条件）
    qn = normalize(q)
    picked_ent: list[str] = []
    picked_kw: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for term in list(r.get("entities") or []):
            t = str(term).strip()
            if not t or t in seen or t in q:
                continue
            if t in q or (len(t) >= 2 and t in qn) or (set(_tokens(q)) & set(_tokens(t))):
                seen.add(t)
                picked_ent.append(t)
        for term in list(r.get("keywords") or []):
            t = str(term).strip()
            if not t or t in seen or t in q:
                continue
            if t in q or (len(t) >= 2 and t in qn) or (set(_tokens(q)) & set(_tokens(t))):
                seen.add(t)
                picked_kw.append(t)
        if len(seen) >= 12:
            break
    return {
        "question": q,
        "expanded_query": q2,
        "expand_changed": q2 != q,
        "expand_tail": extras_str,
        "expanded_entities_approx": picked_ent[:12],
        "expanded_keywords_approx": picked_kw[:12],
    }


def _focus_in_text(text: str) -> dict[str, bool]:
    t = text or ""
    return {term: (term in t) for term in FOCUS_TERMS}


def main() -> int:
    samples = ROOT / "data" / "trs-samples"
    case = next(
        p for p in samples.iterdir()
        if p.is_dir() and CASE_FILTER in p.name and (p / "raw_documents.json").is_file()
    )
    slug = "liuxiang"
    dossier, union_ids, questions = union_pack_ids(case)
    qrow = next(q for q in questions if q["question_id"] == QID)
    question = qrow["question"]
    gold, skipped = gold_paras_for_question(case, QID)
    universe = pack_selected_for_question(dossier, question)
    gold_paras = sorted({p for _d, p in gold})

    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=universe)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)

    expand_meta = _expand_extras(question, rows)
    q_exp = expand_meta["expanded_query"]

    # 各臂全序（取足够长的 picked 不够时直接用底层 rank）
    t0 = time.perf_counter()
    # BM25 / emb 全排序
    r_q = index.bm25_text(question)
    r_sum = index.bm25_summary(q_exp)
    r_emb = index.embed_rank(question)
    from app.kg_lab.index_build import rrf_merge
    r_rrf = rrf_merge(r_q, r_sum, r_emb)

    def ids_pos(ranked: list[tuple[str, float]], k: int = RANK_K) -> list[str]:
        out = []
        for sid, sc in ranked:
            if sid not in universe or float(sc) <= 0:
                continue
            out.append(sid)
            if len(out) >= k:
                break
        return out

    arm_ranks = {
        "q_bm25": ids_pos(r_q),
        "summary_bm25": ids_pos(r_sum),
        "embedding": ids_pos(r_emb),
        "rrf_bm25_emb": ids_pos(r_rrf),
    }
    # hop：用现有 arm（k=RANK_K）只读
    hop = arm_rrf_hop(
        index, question, k=RANK_K, universe=universe, case_slug=slug,
    )
    arm_ranks["rrf_plus_hop"] = [p["para_id"] for p in hop.get("picked") or []]
    hop_added = set(hop.get("hop_added_ids") or [])

    # R1 @7/@15 hop 是否抽中：读 r1 case 若在
    r1_hop_hits: dict[str, list[str]] = {p: [] for p in gold_paras}
    r1_path = Path("/tmp/kg_spike_recall/r1_case_liuxiang.json")
    if not r1_path.is_file():
        r1_path = Path("/tmp/kg_spike_recall/case_liuxiang.json")
    if r1_path.is_file():
        r1 = json.loads(r1_path.read_text(encoding="utf-8"))
        for q in r1.get("questions") or []:
            if q.get("qid") != QID:
                continue
            for label, diag in (
                ("@7", q.get("hop_diag_at_k") or {}),
                ("@15", q.get("hop_diag_at_wide_k") or {}),
            ):
                for pid in diag.get("hop_added_ids") or []:
                    if pid in r1_hop_hits:
                        r1_hop_hits[pid].append(f"r1_hop_added{label}")
                for pid in diag.get("only_in_hop") or []:
                    if pid in r1_hop_hits and f"r1_only_in_hop{label}" not in r1_hop_hits[pid]:
                        r1_hop_hits[pid].append(f"r1_only_in_hop{label}")

    adj = load_adjacency(slug)
    co = adj.get("co_mention") or {}
    causal = adj.get("causal_hop") or {}
    # 入边计数
    in_co: dict[str, int] = {p: 0 for p in gold_paras}
    in_ca: dict[str, int] = {p: 0 for p in gold_paras}
    for src, hops in co.items():
        for h in hops:
            t = str(h.get("to_para_id") or "")
            if t in in_co:
                in_co[t] += 1
    for src, hops in causal.items():
        for h in hops:
            t = str(h.get("to_para_id") or "")
            if t in in_ca:
                in_ca[t] += 1

    smap = segment_map(dossier)
    doc_of = {}
    for src in dossier.sources:
        for seg in src.segments:
            doc_of[str(seg.id)] = str(src.id)

    per_gold: list[dict[str, Any]] = []
    for doc_id, para_id in sorted(gold.keys()):
        text = (smap[para_id].text if para_id in smap else "") or ""
        summary = load_summary(slug, doc_id, para_id) or {}
        stext = summary.get("summary_text") or ""
        s_path = ROOT / "vaults" / "kg-lab" / "summaries" / slug / f"{safe_name(doc_id, para_id)}.md"
        in_index = para_id in index.by_id
        in_box = para_id in universe
        ranks = {
            arm: _rank_of(ids, para_id)
            for arm, ids in arm_ranks.items()
        }
        # full corpus rank（不限 @50）便于看「多远」
        full_ranks = {
            "q_bm25": _rank_of([s for s, _ in r_q if s in universe], para_id),
            "summary_bm25": _rank_of([s for s, _ in r_sum if s in universe], para_id),
            "embedding": _rank_of([s for s, _ in r_emb if s in universe], para_id),
            "rrf_bm25_emb": _rank_of([s for s, _ in r_rrf if s in universe], para_id),
        }
        row = {
            "doc_id": doc_id,
            "para_id": para_id,
            "in_box": in_box,
            "in_index": in_index,
            "n_chars": len(text),
            "text_snip": _snip(text),
            "summary_path": str(s_path.relative_to(ROOT)) if s_path.is_file() else None,
            "summary_ok": bool(summary.get("ok")),
            "summary_model": summary.get("model"),
            "summary_facts": summary.get("facts") or [],
            "summary_entities": summary.get("entities") or [],
            "summary_keywords": summary.get("keywords") or [],
            "summary_text": stext,
            "summary_snip": _snip(stext),
            "focus_in_text": _focus_in_text(text),
            "focus_in_summary": _focus_in_text(stext),
            "overlap_q_vs_text": _overlap(question, text),
            "overlap_q_vs_summary": _overlap(question, stext),
            "overlap_expand_vs_text": _overlap(q_exp, text),
            "ranks_at_50": {
                arm: (rk if rk is not None and rk <= RANK_K else None)
                for arm, rk in ranks.items()
            },
            "ranks_full_in_box": full_ranks,
            "miss_at_50": {
                arm: (ranks[arm] is None or ranks[arm] > RANK_K)
                for arm in arm_ranks
            },
            "graph": {
                "out_co_mention": len(co.get(para_id) or []),
                "out_causal": len(causal.get(para_id) or []),
                "in_co_mention": in_co.get(para_id, 0),
                "in_causal": in_ca.get(para_id, 0),
                "in_r1_hop_added_at50": para_id in hop_added,
                "r1_notes": r1_hop_hits.get(para_id) or [],
            },
            "gold_quote_head": next(iter(gold[(doc_id, para_id)]))[:100]
            if gold.get((doc_id, para_id)) else "",
        }
        per_gold.append(row)

    # 汇总假设
    n = len(per_gold)
    n_miss_all = sum(
        1 for r in per_gold
        if all(r["miss_at_50"].values())
    )
    n_focus_text = sum(
        1 for r in per_gold
        if any(r["focus_in_text"].values())
    )
    n_focus_sum = sum(
        1 for r in per_gold
        if any(r["focus_in_summary"].values())
    )
    avg_cover_text = sum(r["overlap_q_vs_text"]["cover_q"] for r in per_gold) / max(1, n)
    avg_cover_sum = sum(r["overlap_q_vs_summary"]["cover_q"] for r in per_gold) / max(1, n)
    avg_cover_exp = sum(r["overlap_expand_vs_text"]["cover_q"] for r in per_gold) / max(1, n)
    n_in_index = sum(1 for r in per_gold if r["in_index"])
    n_causal_touch = sum(
        1 for r in per_gold
        if r["graph"]["out_causal"] or r["graph"]["in_causal"]
    )
    best_full = []
    for r in per_gold:
        fr = r["ranks_full_in_box"]
        best = min((v for v in fr.values() if v is not None), default=None)
        best_full.append(best)

    hypotheses: list[dict[str, Any]] = []
    if n_in_index < n:
        hypotheses.append({
            "id": "not_in_index",
            "label": "金标段未进索引",
            "support": f"{n - n_in_index}/{n} 不在 index",
        })
    else:
        hypotheses.append({
            "id": "not_in_index",
            "label": "金标段未进索引",
            "support": "否：5/5 均在箱内索引",
            "active": False,
        })
    if avg_cover_sum + 0.02 < avg_cover_text or n_focus_sum < n_focus_text:
        hypotheses.append({
            "id": "summary_gap",
            "label": "摘要未覆盖对立口径／关键事实",
            "support": (
                f"focus词：正文命中段 {n_focus_text}/{n}，摘要命中段 {n_focus_sum}/{n}；"
                f"cover_q 问句→正文 {avg_cover_text:.3f} vs →摘要 {avg_cover_sum:.3f}"
            ),
            "active": True,
        })
    if expand_meta["expand_changed"] and avg_cover_exp <= avg_cover_text + 0.01:
        hypotheses.append({
            "id": "expand_drift",
            "label": "拓展词漂移（未抬金标重叠）",
            "support": (
                f"expand 有改写；cover expand→正文 {avg_cover_exp:.3f} "
                f"vs 原问→正文 {avg_cover_text:.3f}；"
                f"扩入≈ ent {expand_meta['expanded_entities_approx'][:6]} "
                f"kw {expand_meta['expanded_keywords_approx'][:6]}"
            ),
            "active": True,
        })
    if avg_cover_text < 0.15:
        hypotheses.append({
            "id": "weak_token_overlap",
            "label": "分词／字符重叠弱",
            "support": f"问句→正文 cover_q 均值 {avg_cover_text:.3f}",
            "active": True,
        })
    emb_miss = sum(1 for r in per_gold if r["miss_at_50"]["embedding"])
    if emb_miss == n:
        hypotheses.append({
            "id": "emb_misalign",
            "label": "向量未对齐（@50 全 miss）",
            "support": f"embedding @50 miss {emb_miss}/{n}；full ranks {[r['ranks_full_in_box']['embedding'] for r in per_gold]}",
            "active": True,
        })
    if n_causal_touch == 0:
        hypotheses.append({
            "id": "graph_unreachable",
            "label": "图因果邻域够不着（co 或有、causal 空）",
            "support": (
                f"五段 causal in/out 皆 0；co 出度 "
                f"{[r['graph']['out_co_mention'] for r in per_gold]}；"
                f"R1 hop 抽中金标: {[r['graph']['r1_notes'] for r in per_gold]}"
            ),
            "active": True,
        })

    active = [h for h in hypotheses if h.get("active", True)]
    # 下一刀建议：摘要覆盖对立口径是最直接可验、且与「不愿走／未放行」题面最贴
    next_cut = {
        "choice": "补摘要覆盖（只动 q_002 相关／对立口径字段的摘要补丁或二次摘要，不先改 expand／图）",
        "why": (
            "题面核心是对立口径「不愿走 vs 未放行／11年」；"
            "若摘要未写这些，summary_bm25／RRF 与 embedding（吃摘要窗）会系统性漂向安置通稿。"
            "expand 若只扩实体名，难补对立谓词。"
        ),
        "accept_same_table": (
            "重跑本探针：五段 `focus_in_summary` 对关键词至少各命中 1；"
            "且至少 1 条金标 `ranks_at_50.summary_bm25` 或 `embedding` 从 miss→≤50；"
            "不动 expand／graph 也可对照。"
        ),
    }

    out = {
        "ticket": "R2b-q002-measure",
        "case": case.name,
        "qid": QID,
        "question": question,
        "rank_k": RANK_K,
        "n_gold": n,
        "skipped_locator": skipped,
        "n_box": len(universe),
        "expand": expand_meta,
        "per_gold": per_gold,
        "aggregates": {
            "n_miss_all_arms_at_50": n_miss_all,
            "avg_cover_q_text": round(avg_cover_text, 4),
            "avg_cover_q_summary": round(avg_cover_sum, 4),
            "avg_cover_expand_text": round(avg_cover_exp, 4),
            "n_focus_in_text": n_focus_text,
            "n_focus_in_summary": n_focus_sum,
            "n_in_index": n_in_index,
            "best_full_rank_min_per_gold": best_full,
            "wall_s": round(time.perf_counter() - t0, 3),
        },
        "hypotheses": hypotheses,
        "next_cut": next_cut,
    }

    art = ROOT / "artifacts" / "kg-index"
    art.mkdir(parents=True, exist_ok=True)
    json_path = art / "R2b_q002_measure.json"
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # markdown
    lines = [
        "# R2b — q_002 检索盲区度量（只量）",
        "",
        f"- 案：{case.name}／`{QID}`",
        f"- 问句：{question}",
        f"- 金标 L2：{n} 段；箱内 `{len(universe)}`；排名窗 **@{RANK_K}**",
        f"- expand 后查询：`{q_exp}`",
        f"- expand 相对原问改写：{expand_meta['expand_changed']}",
        f"- 扩入实体≈ {expand_meta['expanded_entities_approx']}",
        f"- 扩入关键词≈ {expand_meta['expanded_keywords_approx']}",
        f"- 墙钟：{out['aggregates']['wall_s']}s（复用 embeddings／摘要缓存）",
        "",
        "## 主因假设（可多选）",
        "",
    ]
    for h in hypotheses:
        mark = "✅" if h.get("active", True) else "❌"
        lines.append(f"- {mark} **{h['label']}**：{h['support']}")
    lines += [
        "",
        f"### 建议的唯一下一刀",
        f"**{next_cut['choice']}**",
        "",
        f"- 理由：{next_cut['why']}",
        f"- 同表验收：{next_cut['accept_same_table']}",
        "",
        "## 逐段表",
        "",
    ]
    for r in per_gold:
        ft = [k for k, v in r["focus_in_text"].items() if v]
        fs = [k for k, v in r["focus_in_summary"].items() if v]
        lines += [
            f"### `{r['para_id']}`",
            "",
            f"- 索引：in_box={r['in_box']} in_index={r['in_index']} chars={r['n_chars']}",
            f"- 原文首：{r['text_snip']['head']}",
            f"- 原文尾：{r['text_snip']['tail'] or '（短段）'}",
            f"- 摘要路径：`{r['summary_path']}` model={r['summary_model']}",
            f"- 摘要 facts：{r['summary_facts']}",
            f"- 摘要正文首：{r['summary_snip']['head']}",
            f"- focus 正文命中：{ft or '∅'}／摘要命中：{fs or '∅'}",
            (
                f"- 重叠 cover_q：问→文 {r['overlap_q_vs_text']['cover_q']} "
                f"（j={r['overlap_q_vs_text']['jaccard']} inter={r['overlap_q_vs_text']['n_inter']}）；"
                f"问→摘要 {r['overlap_q_vs_summary']['cover_q']}；"
                f"expand→文 {r['overlap_expand_vs_text']['cover_q']}"
            ),
            f"- @{RANK_K} 排名：" + ", ".join(
                f"{a}={'miss' if r['ranks_at_50'][a] is None else r['ranks_at_50'][a]}"
                for a in ("q_bm25", "summary_bm25", "embedding", "rrf_bm25_emb", "rrf_plus_hop")
            ),
            f"- 箱内全序（参考）：{r['ranks_full_in_box']}",
            (
                f"- 图：out_co={r['graph']['out_co_mention']} out_ca={r['graph']['out_causal']} "
                f"in_co={r['graph']['in_co_mention']} in_ca={r['graph']['in_causal']}；"
                f"本探针 hop_added@50={r['graph']['in_r1_hop_added_at50']}；"
                f"R1笔记={r['graph']['r1_notes'] or '∅'}"
            ),
            "",
        ]

    lines += [
        "## 汇总数字",
        "",
        f"- @{RANK_K} 五臂全 miss：{n_miss_all}/{n}",
        f"- cover 均值 问→文 / 问→摘要 / expand→文 = "
        f"{avg_cover_text:.3f} / {avg_cover_sum:.3f} / {avg_cover_exp:.3f}",
        f"- focus 段数 正文/摘要 = {n_focus_text}/{n_focus_sum}",
        "",
        "## 路径",
        f"- 本报告：`artifacts/kg-index/R2b_q002_measure.md`",
        f"- JSON：`artifacts/kg-index/R2b_q002_measure.json`",
        f"- 不改：`recall_arms`／`keyword_expand`／summarize／graph 建边",
        "",
    ]
    md_path = art / "R2b_q002_measure.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {md_path}", flush=True)
    print(f"wrote {json_path}", flush=True)
    print("NEXT_CUT:", next_cut["choice"], flush=True)
    print("ACTIVE:", [h["label"] for h in active], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
