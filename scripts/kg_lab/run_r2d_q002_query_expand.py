#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2d：q_002 问句侧同义／改写验收（不改 hop／因果）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bm25 import _tokens  # noqa: E402, PLC2701
from app.core.citation_check import normalize  # noqa: E402
from app.kg_lab.config import ARTIFACTS  # noqa: E402
from app.kg_lab.eval_metrics import leak_check, measure_arm  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows, rrf_merge  # noqa: E402
from app.kg_lab.query_expand import expand_query_parts  # noqa: E402
from app.kg_lab.recall_arms import (  # noqa: E402
    arm_embedding,
    arm_paraphrase,
    arm_q_bm25,
    arm_rrf,
    arm_rrf_hop,
    arm_summary_bm25,
    run_all_arms,
)
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

QID = "q_002"
SLUG = "liuxiang"
RANK_K = 50


def _legacy_expand(question: str, rows: list[dict[str, Any]], *, top_n: int = 12) -> str:
    """R2b／R2c 旧拓展（无同义、无噪声过滤）— 仅对照。"""
    q = (question or "").strip()
    qn = normalize(q)
    extras: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for term in list(r.get("entities") or []) + list(r.get("keywords") or []):
            t = str(term).strip()
            if not t or t in seen or t in q:
                continue
            if t in q or (len(t) >= 2 and t in qn) or (set(_tokens(q)) & set(_tokens(t))):
                seen.add(t)
                extras.append(t)
            if len(extras) >= top_n:
                break
        if len(extras) >= top_n:
            break
    return q if not extras else q + " " + " ".join(extras)


def _rank_at_k(
    ranked: list[tuple[str, float]], universe: set[str], pid: str, k: int,
) -> int | None:
    n = 0
    for sid, sc in ranked:
        if sid not in universe or float(sc) <= 0:
            continue
        n += 1
        if sid == pid:
            return n if n <= k else None
        if n >= k:
            break
    return None


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
    dossier, _u, questions = union_pack_ids(case)
    question = next(q["question"] for q in questions if q["question_id"] == QID)
    gold, _ = gold_paras_for_question(case, QID)
    universe = pack_selected_for_question(dossier, question)
    gold_paras = sorted({p for _d, p in gold})

    rows = build_corpus_rows(dossier, case_slug=SLUG, para_ids=universe)
    index = KgIndex(SLUG, rows)
    index.ensure_embeddings(force=False)

    legacy_q = _legacy_expand(question, rows)
    parts = expand_query_parts(question, rows)
    new_q = parts["expanded_query"]
    q_para = parts["paraphrase_query"]

    # 各臂全序
    r_q = index.bm25_text(question)
    r_sum = index.bm25_summary(new_q)
    r_sum_legacy = index.bm25_summary(legacy_q)
    r_emb = index.embed_rank(question)
    r_para_sum = index.bm25_summary(
        expand_query_parts(q_para, rows)["expanded_query"]
    )
    r_para_emb = index.embed_rank(q_para)
    r_para = rrf_merge(r_para_sum, r_para_emb)
    r_rrf = rrf_merge(r_q, r_sum, r_emb)

    # before ranks from R2c
    r2c_path = ARTIFACTS / "R2c_q002_summary_fix.json"
    r2c = json.loads(r2c_path.read_text(encoding="utf-8")) if r2c_path.is_file() else {}
    before = {
        r["para_id"]: r.get("ranks_at_50_after") or r.get("ranks_at_50_before") or {}
        for r in (r2c.get("per_gold") or [])
    }
    # R2c "after" is the pre-R2d baseline for miss→≤50
    if not before:
        r2b = json.loads((ARTIFACTS / "R2b_q002_measure.json").read_text(encoding="utf-8"))
        before = {r["para_id"]: r.get("ranks_at_50") or {} for r in r2b.get("per_gold") or []}

    arm_rankings = {
        "q_bm25": r_q,
        "summary_bm25": r_sum,
        "summary_bm25_legacy_expand": r_sum_legacy,
        "embedding": r_emb,
        "paraphrase": r_para,
        "rrf_bm25_emb": r_rrf,
    }

    lifts: list[dict[str, Any]] = []
    per: list[dict[str, Any]] = []
    for pid in gold_paras:
        br = before.get(pid) or {}
        row_ranks = {
            arm: _rank_at_k(ranked, universe, pid, RANK_K)
            for arm, ranked in arm_rankings.items()
        }
        full = {
            arm: _full_rank(ranked, universe, pid)
            for arm, ranked in arm_rankings.items()
        }
        for arm in ("summary_bm25", "embedding", "paraphrase"):
            b = br.get(arm) if arm != "paraphrase" else None
            # paraphrase is new — treat "before" as miss if absent
            b_miss = b is None
            a = row_ranks.get(arm)
            a_hit = a is not None and a <= RANK_K
            if b_miss and a_hit:
                lifts.append({
                    "para_id": pid, "arm": arm,
                    "before": b, "after": a,
                })
        per.append({
            "para_id": pid,
            "ranks_at_50_before_r2c": br,
            "ranks_at_50_after": {
                k: v for k, v in row_ranks.items()
                if k != "summary_bm25_legacy_expand"
            },
            "ranks_full": full,
            "legacy_summary_rank_at_50": row_ranks["summary_bm25_legacy_expand"],
        })

    # @7/@15 hits
    arms7 = run_all_arms(
        index, question, k=7, universe=universe, case_slug=SLUG,
        gold_para_ids=set(gold_paras) & universe, include_oracle=True,
    )
    arms15 = run_all_arms(
        index, question, k=15, universe=universe, case_slug=SLUG,
        gold_para_ids=set(gold_paras) & universe, include_oracle=True,
    )
    leaks = {n: leak_check(p, gold=gold) for n, p in arms7.items()}
    leak_any = any(not v.get("ok") for v in leaks.values())

    def hit_map(arms: dict, k: int) -> dict[str, int]:
        return {
            n: measure_arm(p, gold=gold, universe=universe, k=k)["n_gold_hit"]
            for n, p in arms.items()
        }

    hit7 = hit_map(arms7, 7)
    hit15 = hit_map(arms15, 15)

    # R1 / R2c baselines
    r1_path = Path("/tmp/kg_spike_recall/r1_case_liuxiang.json")
    if not r1_path.is_file():
        r1_path = Path("/tmp/kg_spike_recall/case_liuxiang.json")
    r1_q2 = None
    if r1_path.is_file():
        r1 = json.loads(r1_path.read_text(encoding="utf-8"))
        r1_q2 = next((q for q in r1.get("questions") or [] if q.get("qid") == QID), None)
    r1_7 = {
        a: (r1_q2 or {}).get("metrics_at_k", {}).get(a, {}).get("n_gold_hit")
        for a in ("q_bm25", "summary_bm25", "embedding", "rrf_bm25_emb", "rrf_plus_hop", "oracle")
    }
    r1_15 = {
        a: (r1_q2 or {}).get("metrics_at_wide_k", {}).get(a, {}).get("n_gold_hit")
        for a in r1_7
    }
    r2c_7 = (r2c.get("q002_hit_at_7") or {}).get("r2c") or {}
    r2c_15 = (r2c.get("q002_hit_at_15") or {}).get("r2c") or {}

    passed = len(lifts) >= 1 and (not leak_any)

    report = {
        "ticket": "R2d-q002-query-expand",
        "question": question,
        "expand_before_legacy": legacy_q,
        "expand_after": new_q,
        "expand_parts": parts,
        "paraphrase_query": q_para,
        "synonyms_added": parts["synonyms_added"],
        "noise_skipped_sample": parts["noise_skipped_sample"],
        "rank_lifts_miss_to_le50": lifts,
        "per_gold": per,
        "q002_hit_at_7": {"r1": r1_7, "r2c": r2c_7, "r2d": hit7},
        "q002_hit_at_15": {"r1": r1_15, "r2c": r2c_15, "r2d": hit15},
        "leak_any_bad": leak_any,
        "leaks": {k: {"ok": v.get("ok"), "leaked": v.get("leaked")} for k, v in leaks.items()},
        "passed": passed,
        "pass_detail": {
            "rank_lift_ge1": len(lifts) >= 1,
            "leak_ok": not leak_any,
        },
        "note_if_fail": None if passed else (
            "同义不够／噪声仍主导／或向量侧仍盲——按票停止，不开因果。"
        ),
    }

    json_path = ARTIFACTS / "R2d_q002_query_expand.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# R2d — q_002 问句侧同义／改写验收",
        "",
        f"- 问句：{question}",
        f"- **过线：{passed}**",
        f"- leak_any_bad：{leak_any}",
        "",
        "## 1. expand 词表：改前／改后",
        "",
        "### 改前（legacy，R2b/R2c）",
        f"```\n{legacy_q}\n```",
        "",
        "### 改后（R2d）",
        f"```\n{new_q}\n```",
        "",
        f"- **新增对立同义**：{parts['synonyms_added']}",
        f"- **语料补强（过滤后）**：{parts['corpus_extras']}",
        f"- **剔除噪声样例**：{parts['noise_skipped_sample'][:12]}",
        f"- **规则 paraphrase**：`{q_para}`",
        "",
        "## 2. 五条金标 @50 排名",
        "",
        "| para_id | ①q_bm25 | ②summary | ③emb | ⑥paraphrase | ②legacy对照 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in per:
        def fmt(v: int | None) -> str:
            return "miss" if v is None else str(v)
        a = r["ranks_at_50_after"]
        lines.append(
            f"| `{r['para_id']}` | {fmt(a.get('q_bm25'))} | {fmt(a.get('summary_bm25'))} | "
            f"{fmt(a.get('embedding'))} | {fmt(a.get('paraphrase'))} | "
            f"{fmt(r.get('legacy_summary_rank_at_50'))} |"
        )
    lines += ["", "### miss→≤50 lifts", ""]
    if lifts:
        for x in lifts:
            lines.append(
                f"- ✅ `{x['para_id']}` **{x['arm']}**: "
                f"{x['before'] if x['before'] is not None else 'miss'} → **{x['after']}**"
            )
    else:
        lines.append("- ❌ 无")

    lines += [
        "",
        "### vs R2c（同臂）",
        "",
    ]
    for r in per:
        br = r["ranks_at_50_before_r2c"]
        ar = r["ranks_at_50_after"]
        lines.append(
            f"- `{r['para_id']}` summary {br.get('summary_bm25')}→{ar.get('summary_bm25')}；"
            f" emb {br.get('embedding')}→{ar.get('embedding')}；"
            f" full_sum={r['ranks_full'].get('summary_bm25')} "
            f"full_para={r['ranks_full'].get('paraphrase')}"
        )

    lines += [
        "",
        "## 3. q_002 @7 / @15 hit",
        "",
        "| arm | R1@7 | R2c@7 | R2d@7 | R1@15 | R2c@15 | R2d@15 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    arms = ["q_bm25", "summary_bm25", "embedding", "paraphrase",
            "rrf_bm25_emb", "rrf_plus_hop", "oracle"]
    for arm in arms:
        lines.append(
            f"| {arm} | {r1_7.get(arm)} | {r2c_7.get(arm)} | {hit7.get(arm)} | "
            f"{r1_15.get(arm)} | {r2c_15.get(arm)} | {hit15.get(arm)} |"
        )

    lines += [
        "",
        "## 4. 过线",
        f"- miss→≤50 ≥1：{len(lifts) >= 1} → {lifts}",
        f"- leak ok：{not leak_any}",
        f"- **合计：{passed}**",
        "",
        "## 路径",
        f"- `{ARTIFACTS / 'R2d_q002_query_expand.md'}`",
        f"- `{json_path}`",
        f"- 实现：`app/kg_lab/query_expand.py`；`keyword_expand_query`／`arm_paraphrase`",
        "",
    ]
    if not passed:
        lines += [
            "## 未过线",
            report["note_if_fail"] or "",
            "",
        ]

    md_path = ARTIFACTS / "R2d_q002_query_expand.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {md_path}", flush=True)
    print(f"PASS={passed} lifts={lifts}", flush=True)
    print(f"expand_after={new_q[:120]}…", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
