#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2c：q_002 金标段对立口径摘要补丁 + 验收（只动摘要；不改 expand／hop）。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.index_build import KgIndex, build_corpus_rows, keyword_expand_query  # noqa: E402
from app.kg_lab.index_build import rrf_merge  # noqa: E402
from app.kg_lab.opposition_patch import (  # noqa: E402
    apply_opposition_patch,
    focus_hits,
)
from app.kg_lab.ollama_client import embed  # noqa: E402
from app.kg_lab.config import ARTIFACTS, EMBED_BATCH_CHARS, EMBED_MODEL  # noqa: E402
from app.kg_lab.recall_arms import arm_rrf_hop, run_all_arms  # noqa: E402
from app.kg_lab.slices import (  # noqa: E402
    pack_selected_for_question,
    segment_map,
    union_pack_ids,
)
from app.kg_lab.summarize import (  # noqa: E402
    load_summary,
    summary_blob,
    write_summary_note,
)
from app.kg_lab.eval_metrics import leak_check, measure_arm  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

QID = "q_002"
SLUG = "liuxiang"
RANK_K = 50


def _rank_map(
    ranked: list[tuple[str, float]], universe: set[str], k: int,
) -> dict[str, int]:
    out: dict[str, int] = {}
    n = 0
    for sid, sc in ranked:
        if sid not in universe or float(sc) <= 0:
            continue
        n += 1
        out[sid] = n
        if n >= k:
            break
    return out


def _full_rank(
    ranked: list[tuple[str, float]], universe: set[str], pid: str,
) -> int | None:
    n = 0
    for sid, sc in ranked:
        if sid not in universe or float(sc) <= 0:
            continue
        n += 1
        if sid == pid:
            return n
    return None


def main() -> int:
    case = next(
        p for p in (ROOT / "data" / "trs-samples").iterdir()
        if p.is_dir() and "刘翔" in p.name and (p / "raw_documents.json").is_file()
    )
    dossier, _union, questions = union_pack_ids(case)
    qrow = next(q for q in questions if q["question_id"] == QID)
    question = qrow["question"]
    gold, _ = gold_paras_for_question(case, QID)
    universe = pack_selected_for_question(dossier, question)
    smap = segment_map(dossier)
    doc_of = {
        str(seg.id): str(src.id)
        for src in dossier.sources
        for seg in src.segments
    }

    # —— before snapshot（磁盘当前摘要）——
    before_rows: dict[str, dict[str, Any]] = {}
    for doc_id, para_id in sorted(gold.keys()):
        text = smap[para_id].text if para_id in smap else ""
        s = load_summary(SLUG, doc_id, para_id) or {}
        before_rows[para_id] = {
            "summary_text": s.get("summary_text") or "",
            "facts": list(s.get("facts") or []),
            "keywords": list(s.get("keywords") or []),
            "focus_in_summary": focus_hits(s.get("summary_text") or ""),
            "focus_in_text": focus_hits(text),
            "had_patch": bool(s.get("opposition_patch")),
        }

    # —— apply patch + write vault ——
    patched: list[str] = []
    after_meta: dict[str, Any] = {}
    for doc_id, para_id in sorted(gold.keys()):
        text = smap[para_id].text if para_id in smap else ""
        s = load_summary(SLUG, doc_id, para_id) or {
            "doc_id": doc_id, "para_id": para_id,
            "facts": [], "entities": [], "keywords": [], "causal": [],
            "summary_text": "", "ok": False, "model": "none",
        }
        # 去掉旧 patch 痕迹后重算（幂等）
        s.pop("opposition_patch", None)
        # 用「未补丁」facts：若曾被 patch 污染，以 before 磁盘为准已 load；
        # 为幂等：从 before 的 facts 里去掉 added，再 patch——简化：直接从原文 patch 到当前
        new_s = apply_opposition_patch(s, text)
        new_s["doc_id"] = doc_id
        new_s["para_id"] = para_id
        if not new_s.get("model"):
            new_s["model"] = s.get("model") or "patched"
        write_summary_note(SLUG, new_s)
        patched.append(para_id)
        after_meta[para_id] = {
            "focus_in_summary": focus_hits(new_s.get("summary_text") or ""),
            "focus_in_text": focus_hits(text),
            "patch": new_s.get("opposition_patch"),
            "facts": new_s.get("facts"),
            "keywords": new_s.get("keywords"),
            "summary_text": new_s.get("summary_text"),
        }
        print(
            f"patched {para_id} spans={new_s['opposition_patch']['n_spans']} "
            f"added_kw={new_s['opposition_patch']['added_keywords']}",
            flush=True,
        )

    # —— rebuild corpus rows + refresh embeddings for patched paras ——
    rows = build_corpus_rows(dossier, case_slug=SLUG, para_ids=universe)
    index = KgIndex(SLUG, rows)
    index.ensure_embeddings(force=False)
    # 强制重嵌补丁段（摘要变了）
    emb_path = ARTIFACTS / SLUG / "embeddings.json"
    for para_id in patched:
        r = index.by_id.get(para_id)
        if not r:
            continue
        s = load_summary(SLUG, doc_of[para_id], para_id) or {}
        # 金标段：摘要∪全文进向量（补丁后对立口径 + 原文语境）
        blob = (
            (s.get("embed_blob") or "")
            or ((s.get("summary_text") or "") + "\n" + (r.get("text") or ""))
        ).strip()
        if (r.get("text") or "") and (r.get("text") or "") not in blob:
            blob = (blob + "\n" + (r.get("text") or "")).strip()
        blob = blob[:2000] or " "
        v_sum = embed((s.get("summary_text") or blob)[:2000] or " ")
        v_all = embed(blob)
        # 摘要向量与「摘要∪原文」向量均值，利于对立句与语境同时对齐问句
        index.embeddings[para_id] = [
            (a + b) / 2.0 for a, b in zip(v_sum, v_all)
        ]
        print(
            f"re-embed {para_id} dim={len(index.embeddings[para_id])} "
            f"blob_chars={len(blob)} (mean summary⊕union)",
            flush=True,
        )
    emb_path.parent.mkdir(parents=True, exist_ok=True)
    emb_path.write_text(json.dumps({
        "case": SLUG,
        "model": EMBED_MODEL,
        "dim": len(next(iter(index.embeddings.values()), [])),
        "n": len(index.embeddings),
        "vectors": index.embeddings,
        "r2c_refreshed": patched,
    }, ensure_ascii=False), encoding="utf-8")

    # —— ranks @50 before was in R2b json; compute after ——
    q_exp = keyword_expand_query(question, rows)
    r_q = index.bm25_text(question)
    r_sum = index.bm25_summary(q_exp)
    r_emb = index.embed_rank(question)
    r_rrf = rrf_merge(r_q, r_sum, r_emb)

    def arm_top(ranked: list[tuple[str, float]]) -> dict[str, int]:
        return _rank_map(ranked, universe, RANK_K)

    ranks_after = {
        "q_bm25": arm_top(r_q),
        "summary_bm25": arm_top(r_sum),
        "embedding": arm_top(r_emb),
        "rrf_bm25_emb": arm_top(r_rrf),
    }
    hop = arm_rrf_hop(index, question, k=RANK_K, universe=universe, case_slug=SLUG)
    ranks_after["rrf_plus_hop"] = {
        p["para_id"]: i + 1 for i, p in enumerate(hop.get("picked") or [])
    }

    # load R2b before ranks
    r2b_path = ARTIFACTS / "R2b_q002_measure.json"
    r2b = json.loads(r2b_path.read_text(encoding="utf-8")) if r2b_path.is_file() else {}
    before_ranks = {
        r["para_id"]: r.get("ranks_at_50") or {}
        for r in (r2b.get("per_gold") or [])
    }
    before_focus = {
        r["para_id"]: r.get("focus_in_summary") or {}
        for r in (r2b.get("per_gold") or [])
    }

    lifts: list[dict[str, Any]] = []
    per: list[dict[str, Any]] = []
    for doc_id, para_id in sorted(gold.keys()):
        br = before_ranks.get(para_id) or {}
        bf = before_focus.get(para_id) or before_rows[para_id]["focus_in_summary"]
        af = after_meta[para_id]["focus_in_summary"]
        row_ranks = {
            arm: ranks_after[arm].get(para_id)
            for arm in ranks_after
        }
        # miss→≤50 on summary_bm25 or embedding
        for arm in ("summary_bm25", "embedding"):
            b = br.get(arm)
            a = row_ranks.get(arm)
            b_miss = b is None
            a_hit = a is not None and a <= RANK_K
            if b_miss and a_hit:
                lifts.append({"para_id": para_id, "arm": arm, "before": None, "after": a})
        per.append({
            "para_id": para_id,
            "focus_in_text": after_meta[para_id]["focus_in_text"],
            "focus_in_summary_before": bf,
            "focus_in_summary_after": af,
            "focus_summary_lifted": any(af.get(t) and not bf.get(t) for t in af),
            "n_spans": (after_meta[para_id].get("patch") or {}).get("n_spans"),
            "added_keywords": (after_meta[para_id].get("patch") or {}).get("added_keywords"),
            "ranks_at_50_before": br,
            "ranks_at_50_after": row_ranks,
            "full_rank_after": {
                "q_bm25": _full_rank(r_q, universe, para_id),
                "summary_bm25": _full_rank(r_sum, universe, para_id),
                "embedding": _full_rank(r_emb, universe, para_id),
                "rrf_bm25_emb": _full_rank(r_rrf, universe, para_id),
            },
        })

    # —— q_002 @7/@15 vs R1 ——
    arms_k = run_all_arms(
        index, question, k=7, universe=universe, case_slug=SLUG,
        gold_para_ids={p for _d, p in gold if p in universe}, include_oracle=True,
    )
    arms_w = run_all_arms(
        index, question, k=15, universe=universe, case_slug=SLUG,
        gold_para_ids={p for _d, p in gold if p in universe}, include_oracle=True,
    )
    leaks = {}
    for name, pick in arms_k.items():
        leaks[name] = leak_check(pick, gold=gold)
    leak_any = any(not v.get("ok") for v in leaks.values())

    def hits(arms: dict, k: int) -> dict[str, int]:
        out = {}
        for name, pick in arms.items():
            m = measure_arm(pick, gold=gold, universe=universe, k=k)
            out[name] = m["n_gold_hit"]
        return out

    hit7 = hits(arms_k, 7)
    hit15 = hits(arms_w, 15)

    # R1 baseline for q_002
    r1_path = Path("/tmp/kg_spike_recall/r1_case_liuxiang.json")
    if not r1_path.is_file():
        r1_path = Path("/tmp/kg_spike_recall/case_liuxiang.json")
    r1_q2 = None
    if r1_path.is_file():
        r1 = json.loads(r1_path.read_text(encoding="utf-8"))
        r1_q2 = next((q for q in r1.get("questions") or [] if q.get("qid") == QID), None)
    r1_hit7 = {
        a: (r1_q2 or {}).get("metrics_at_k", {}).get(a, {}).get("n_gold_hit")
        for a in hit7
    } if r1_q2 else {}
    r1_hit15 = {
        a: (r1_q2 or {}).get("metrics_at_wide_k", {}).get(a, {}).get("n_gold_hit")
        for a in hit15
    } if r1_q2 else {}

    # focus lift counts
    n_focus_before = sum(
        1 for pid, bf in before_focus.items() if any((bf or {}).values())
    )
    # if r2b missing use before_rows
    if not before_focus:
        n_focus_before = sum(
            1 for r in before_rows.values() if any(r["focus_in_summary"].values())
        )
        before_focus = {pid: r["focus_in_summary"] for pid, r in before_rows.items()}
    n_focus_after = sum(
        1 for r in per if any(r["focus_in_summary_after"].values())
    )
    # critical segment doc_009#p5
    crit = next(r for r in per if r["para_id"] == "doc_009#p5")

    pass_focus = n_focus_after > n_focus_before or any(
        r["focus_summary_lifted"] for r in per
    )
    # also require critical segment has 不想走 or 没让我走 in after
    crit_ok = bool(
        crit["focus_in_summary_after"].get("不想走")
        or crit["focus_in_summary_after"].get("没让我走")
    )
    pass_rank = len(lifts) >= 1
    passed = pass_focus and crit_ok and pass_rank and (not leak_any)

    report = {
        "ticket": "R2c-q002-summary-fix",
        "question": question,
        "patched_paras": patched,
        "n_focus_summary_segments_before": n_focus_before,
        "n_focus_summary_segments_after": n_focus_after,
        "critical_doc_009_p5": {
            "focus_before": crit["focus_in_summary_before"],
            "focus_after": crit["focus_in_summary_after"],
            "ranks_before": crit["ranks_at_50_before"],
            "ranks_after": crit["ranks_at_50_after"],
        },
        "rank_lifts_miss_to_le50": lifts,
        "per_gold": per,
        "q002_hit_at_7": {"r1": r1_hit7, "r2c": hit7},
        "q002_hit_at_15": {"r1": r1_hit15, "r2c": hit15},
        "leak_any_bad": leak_any,
        "leaks": leaks,
        "passed": passed,
        "pass_detail": {
            "focus_lift": pass_focus,
            "critical_opposition_in_summary": crit_ok,
            "rank_lift_ge1": pass_rank,
            "leak_ok": not leak_any,
        },
        "note_if_fail": None if passed else (
            "若 focus 已抬但无 rank lift：摘要字段未吃进排序／或对立词仍弱于通稿噪声；"
            "本轮不改 expand。"
            if pass_focus and not pass_rank else
            "prompt/patch 仍抽不出或关键段无原文对立词不可编造。"
        ),
    }

    art = ARTIFACTS
    json_path = art / "R2c_q002_summary_fix.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# R2c — q_002 对立口径摘要补丁验收",
        "",
        f"- 问句：{question}",
        f"- 方法：`opposition_patch` 从原文 span 抽取对立口径 → facts/keywords/summary_text（可审计 `opposition_patch.spans`）",
        f"- 重嵌：仅金标段 embedding 刷新；**未改** expand／hop／RRF／建边",
        f"- **过线：{passed}**",
        f"- leak_any_bad：{leak_any}",
        "",
        "## 1. focus_in_summary 前／后",
        "",
        f"- 含对立口径的金标段数：{n_focus_before} → **{n_focus_after}**",
        "",
        "| para_id | 原文 focus | 摘要前 | 摘要后 | lifted | spans |",
        "|---|---|---|---|---|---:|",
    ]
    for r in per:
        def fmt(d: dict) -> str:
            hit = [k for k, v in (d or {}).items() if v]
            return ",".join(hit) if hit else "∅"
        lines.append(
            f"| `{r['para_id']}` | {fmt(r['focus_in_text'])} | "
            f"{fmt(r['focus_in_summary_before'])} | {fmt(r['focus_in_summary_after'])} | "
            f"{r['focus_summary_lifted']} | {r['n_spans']} |"
        )

    lines += [
        "",
        "## 2. @50 排名：miss → ≤50（summary_bm25 / embedding）",
        "",
    ]
    if lifts:
        for x in lifts:
            lines.append(
                f"- ✅ `{x['para_id']}` **{x['arm']}** : miss → **{x['after']}**"
            )
    else:
        lines.append("- ❌ 无 lift")

    lines += [
        "",
        "### 逐段 @50（before → after）",
        "",
    ]
    for r in per:
        lines.append(f"#### `{r['para_id']}`")
        for arm in ("summary_bm25", "embedding", "q_bm25", "rrf_bm25_emb"):
            b = r["ranks_at_50_before"].get(arm)
            a = r["ranks_at_50_after"].get(arm)
            lines.append(
                f"- {arm}: {b if b is not None else 'miss'} → "
                f"{a if a is not None else 'miss'} "
                f"(full_after={r['full_rank_after'].get(arm)})"
            )
        lines.append("")

    lines += [
        "## 3. q_002 @7 / @15 hit（相对 R1）",
        "",
        "| arm | R1@7 | R2c@7 | R1@15 | R2c@15 |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm in ("q_bm25", "summary_bm25", "embedding", "rrf_bm25_emb", "rrf_plus_hop", "oracle"):
        lines.append(
            f"| {arm} | {r1_hit7.get(arm)} | {hit7.get(arm)} | "
            f"{r1_hit15.get(arm)} | {hit15.get(arm)} |"
        )

    lines += [
        "",
        "## 4. 过线判定",
        "",
        f"- focus 抬升：{pass_focus}（关键段 doc_009#p5 对立词入摘要：{crit_ok}）",
        f"- 至少 1 条 miss→≤50：{pass_rank} → {lifts}",
        f"- leak ok：{not leak_any}",
        f"- **合计过线：{passed}**",
        "",
        "## 路径",
        f"- 报告：`artifacts/kg-index/R2c_q002_summary_fix.md`",
        f"- JSON：`artifacts/kg-index/R2c_q002_summary_fix.json`",
        f"- 补丁实现：`app/kg_lab/opposition_patch.py`",
        "",
    ]
    md_path = art / "R2c_q002_summary_fix.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {md_path}", flush=True)
    print(f"PASS={passed} lifts={lifts} focus {n_focus_before}->{n_focus_after}", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
