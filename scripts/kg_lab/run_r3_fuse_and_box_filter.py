#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R3：主融合收进 paraphrase（16/1）＋进盒前 Ollama 粗筛；刘翔三题。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.box_filter import (  # noqa: E402
    DEFAULT_BOX_MAX,
    DEFAULT_BOX_MIN,
    DEFAULT_WIDE_K,
    box_quality,
    coarse_filter_box,
)
from app.kg_lab.config import ARTIFACTS, DEFAULT_K, SUMMARY_MODEL, WIDE_K  # noqa: E402
from app.kg_lab.eval_metrics import leak_check, measure_arm  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.query_expand import (  # noqa: E402
    DEFAULT_EXPAND_TOP_N,
    DEFAULT_PARAPHRASE_N,
)
from app.kg_lab.recall_arms import arm_rrf, run_all_arms  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
ARM_KEYS = (
    "summary_bm25", "embedding", "paraphrase",
    "rrf_bm25_emb", "rrf_plus_hop",
)


def _text_by_id(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {r["para_id"]: (r.get("text") or r.get("union_text") or "") for r in rows}


def _diag_filter(
    *,
    l2: set[str],
    pool_ids: list[str],
    box_ids: list[str],
    dropped_ids: list[str],
) -> dict[str, Any]:
    """覆盖未升时归因：召回仍缺 vs 粗筛误杀。"""
    pool_set = set(pool_ids)
    box_set = set(box_ids)
    drop_set = set(dropped_ids)
    in_pool = sorted(l2 & pool_set)
    not_in_pool = sorted(l2 - pool_set)
    killed = sorted(l2 & drop_set)
    in_box = sorted(l2 & box_set)
    # 金标在 keep_raw 但被 box_max 截掉
    truncated = sorted((l2 & pool_set) - box_set - drop_set)
    if not_in_pool and not killed:
        bottleneck = "recall_miss"
    elif killed and not not_in_pool:
        bottleneck = "filter_kill"
    elif not_in_pool and killed:
        bottleneck = "both"
    elif truncated:
        bottleneck = "box_cap_truncate"
    elif len(in_box) == len(l2):
        bottleneck = "none_full_cover"
    else:
        bottleneck = "other"
    return {
        "bottleneck": bottleneck,
        "gold_in_pool": in_pool,
        "gold_not_in_pool": not_in_pool,
        "gold_filter_killed": killed,
        "gold_in_box": in_box,
        "gold_truncated_by_cap": truncated,
    }


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1, (
        f"defaults must be 16/1, got {DEFAULT_EXPAND_TOP_N}/{DEFAULT_PARAPHRASE_N}"
    )

    case = next(
        p for p in (ROOT / "data" / "trs-samples").iterdir()
        if p.is_dir() and "刘翔" in p.name and (p / "raw_documents.json").is_file()
    )
    dossier, union_ids, questions = union_pack_ids(case)
    rows_all = build_corpus_rows(dossier, case_slug=SLUG, para_ids=union_ids)
    index = KgIndex(SLUG, rows_all)
    index.ensure_embeddings(force=False)

    # 确认主融合已接 paraphrase
    import inspect
    rrf_src = inspect.getsource(arm_rrf)
    assert "rule_paraphrase_questions" in rrf_src, "arm_rrf must fuse paraphrase"

    q_rows: list[dict[str, Any]] = []
    leak_any = False
    prompt_sample = ""

    for qrow in questions:
        qid = qrow["question_id"]
        question = qrow["question"]
        print(f"=== {qid} ===", flush=True)
        gold, _ = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = {p for _d, p in gold if p in universe}
        sub_rows = [r for r in rows_all if r["para_id"] in universe]
        sub = KgIndex(SLUG, sub_rows)
        sub.embeddings = {
            pid: v for pid, v in index.embeddings.items() if pid in universe
        }
        tmap = _text_by_id(sub_rows)

        arms7 = run_all_arms(
            sub, question, k=DEFAULT_K, universe=universe, case_slug=SLUG,
            gold_para_ids=l2, include_oracle=True,
        )
        arms15 = run_all_arms(
            sub, question, k=WIDE_K, universe=universe, case_slug=SLUG,
            gold_para_ids=l2, include_oracle=True,
        )
        # 宽池：主融合 top wide_k
        arms_wide = arm_rrf(sub, question, k=DEFAULT_WIDE_K, universe=universe)

        for pick in list(arms7.values()) + [arms_wide]:
            if not leak_check(pick, gold=gold).get("ok"):
                leak_any = True

        m7 = {
            n: measure_arm(arms7[n], gold=gold, universe=universe, k=DEFAULT_K)
            for n in ARM_KEYS if n in arms7
        }
        m15 = {
            n: measure_arm(arms15[n], gold=gold, universe=universe, k=WIDE_K)
            for n in ARM_KEYS if n in arms15
        }

        # 粗筛盒子
        t_f = time.perf_counter()
        box = coarse_filter_box(
            question,
            arms_wide["picked"],
            text_by_id=tmap,
            model=SUMMARY_MODEL,
            wide_k=DEFAULT_WIDE_K,
            box_min=DEFAULT_BOX_MIN,
            box_max=DEFAULT_BOX_MAX,
        )
        filter_s = round(time.perf_counter() - t_f, 3)
        if not leak_check(box, gold=gold).get("ok"):
            leak_any = True
        if not prompt_sample:
            prompt_sample = box.get("prompt_audit_first_batch") or ""

        box_ids = [p["para_id"] for p in box["picked"]]
        bq = box_quality(box_ids, l2_gold=l2)
        # 对照：纯 RRF top7 / top15 盒子质量
        rrf7_ids = [p["para_id"] for p in arms7["rrf_bm25_emb"]["picked"]]
        rrf15_ids = [p["para_id"] for p in arms15["rrf_bm25_emb"]["picked"]]
        q_rrf7 = box_quality(rrf7_ids, l2_gold=l2)
        q_rrf15 = box_quality(rrf15_ids, l2_gold=l2)
        pool_ids = [p["para_id"] for p in arms_wide["picked"]]
        diag = _diag_filter(
            l2=l2, pool_ids=pool_ids, box_ids=box_ids,
            dropped_ids=list(box.get("dropped_ids") or []),
        )

        print(
            f"  l2={len(l2)} rrf7 recall={q_rrf7['gold_recall']} "
            f"prec={q_rrf7['gold_precision']} | "
            f"rrf15 r={q_rrf15['gold_recall']} p={q_rrf15['gold_precision']} | "
            f"box r={bq['gold_recall']} p={bq['gold_precision']} "
            f"size={bq['box_size']} drop={box['n_drop']} "
            f"bottleneck={diag['bottleneck']} {filter_s}s",
            flush=True,
        )

        q_rows.append({
            "qid": qid,
            "question": question,
            "n_l2": len(l2),
            "hit_at_7": {n: m7[n]["n_gold_hit"] for n in m7},
            "hit_at_15": {n: m15[n]["n_gold_hit"] for n in m15},
            "rrf_fuse": arms7["rrf_bm25_emb"].get("fuse"),
            "n_paraphrases": arms7["rrf_bm25_emb"].get("n_paraphrases"),
            "box_rrf7": q_rrf7,
            "box_rrf15": q_rrf15,
            "box_filtered": bq,
            "filter_meta": {
                "wide_k": box["wide_k"],
                "n_pool": box["n_pool"],
                "n_keep_raw": box["n_keep_raw"],
                "n_drop": box["n_drop"],
                "box_size": box["box_size"],
                "fallback_empty_keep": box["fallback_empty_keep"],
                "model": box["model"],
                "wall_s": filter_s,
                "n_batches": box["n_batches"],
            },
            "diag": diag,
            "decisions_sample": (box.get("decisions") or [])[:8],
        })

    # 合计
    def _sum_box(key: str) -> dict[str, Any]:
        sizes = [q[key]["box_size"] for q in q_rows]
        n_gold = sum(q[key]["n_gold_in_box"] for q in q_rows)
        n_l2 = sum(q[key]["n_l2_gold"] for q in q_rows)
        n_box = sum(sizes)
        return {
            "n_questions": len(q_rows),
            "sum_gold_in_box": n_gold,
            "sum_l2": n_l2,
            "sum_box_size": n_box,
            "gold_recall": round(n_gold / n_l2, 4) if n_l2 else None,
            "gold_precision": round(n_gold / n_box, 4) if n_box else None,
            "box_size_mean": round(sum(sizes) / len(sizes), 2) if sizes else 0,
            "box_size_min": min(sizes) if sizes else 0,
            "box_size_max": max(sizes) if sizes else 0,
            "box_sizes": sizes,
        }

    tot7 = _sum_box("box_rrf7")
    tot15 = _sum_box("box_rrf15")
    tot_f = _sum_box("box_filtered")

    def _better(a: dict, b: dict) -> dict[str, str]:
        """a 相对 b：覆盖／占比 升／平／降。"""
        def cmp(x, y):
            if x is None or y is None:
                return "n/a"
            if x > y + 1e-9:
                return "升"
            if x < y - 1e-9:
                return "降"
            return "平"
        return {
            "recall_vs": cmp(a.get("gold_recall"), b.get("gold_recall")),
            "precision_vs": cmp(a.get("gold_precision"), b.get("gold_precision")),
        }

    vs7 = _better(tot_f, tot7)
    vs15 = _better(tot_f, tot15)
    # 严格目标＝覆盖升且占比升（相对 Top-7 或 Top-15 任一对照）
    goal_vs7 = vs7["recall_vs"] == "升" and vs7["precision_vs"] == "升"
    goal_vs15 = vs15["recall_vs"] == "升" and vs15["precision_vs"] == "升"
    cover_up = vs7["recall_vs"] == "升" or vs15["recall_vs"] == "升"
    prec_up = vs7["precision_vs"] == "升" or vs15["precision_vs"] == "升"
    both_up = goal_vs7 or goal_vs15

    bottlenecks = [q["diag"]["bottleneck"] for q in q_rows]
    # 下一刀建议（二选一）
    if any(b in {"recall_miss", "both"} for b in bottlenecks):
        next_cut = "causal_R2a"
        next_why = (
            "宽池仍缺金标（q_002/q_003）；粗筛无法补召回。"
            "占比未升因盒子仍顶满 15、杂质多——但主瓶颈在召回，先开因果。"
        )
    else:
        next_cut = "tune_box_filter"
        next_why = "金标多在池内但被误杀或截断／盒子偏大；应调粗筛 prompt／box_max。"

    report = {
        "ticket": "R3-fuse-and-box-filter",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
        },
        "fuse": q_rows[0]["rrf_fuse"] if q_rows else None,
        "filter": {
            "model": SUMMARY_MODEL,
            "wide_k": DEFAULT_WIDE_K,
            "box_min": DEFAULT_BOX_MIN,
            "box_max": DEFAULT_BOX_MAX,
            "prompt_system_摘要": (
                "证据粗筛员；只据议题+原文判实质帮助；"
                "弱相关／通稿套话丢弃；不用外部知识；解析失败该批全 keep"
            ),
            "prompt_audit_first_batch": prompt_sample[:1200],
        },
        "leak_any_bad": leak_any,
        "questions": q_rows,
        "totals": {
            "rrf_top7": tot7,
            "rrf_top15": tot15,
            "filtered_box": tot_f,
            "vs_top7": vs7,
            "vs_top15": vs15,
        },
        "goal": {
            "cover_up_any": cover_up,
            "precision_up_any": prec_up,
            "goal_vs7": goal_vs7,
            "goal_vs15": goal_vs15,
            "both_up_strict": both_up,
        },
        "next_cut": next_cut,
        "next_why": next_why,
        "wall_s": round(time.perf_counter() - t0, 3),
    }

    art = ARTIFACTS
    art.mkdir(parents=True, exist_ok=True)
    jp = art / "R3_fuse_and_box_filter.json"
    jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# R3 — 主融合收进 paraphrase（16/1）＋进盒前粗筛",
        "",
        f"- 默认：expand_top_n=**{DEFAULT_EXPAND_TOP_N}**，n_paraphrase=**{DEFAULT_PARAPHRASE_N}**",
        f"- 主融合：`{report['fuse']}`",
        f"- 粗筛模型：`{SUMMARY_MODEL}`；宽池={DEFAULT_WIDE_K} → 盒子∈[{DEFAULT_BOX_MIN},{DEFAULT_BOX_MAX}]",
        f"- leak_any_bad：**{leak_any}**",
        f"- 墙钟：{report['wall_s']}s",
        "",
        "## 实现要点",
        "",
        "1. `arm_rrf`：RRF(原文BM25 ⊕ 扩词摘要BM25 ⊕ emb ⊕ paraphrase×1(摘要+emb))",
        "2. 粗筛：宽召回 Top-40 → Ollama 逐批 keep/drop（prompt 不含金标／para_id）→ 按融合分截到 ≤15",
        "3. 对照：同一融合下的 RRF Top-7／Top-15 硬切盒子",
        "",
        "### 粗筛 prompt 摘要",
        "",
        "```",
        report["filter"]["prompt_system_摘要"],
        "```",
        "",
        "首批 prompt 审计（截断）：",
        "",
        "```",
        (prompt_sample or "")[:800],
        "```",
        "",
        "## 数字表（刘翔三题合计）",
        "",
        "| 盒子 | 金标召回 | 金标占比 | Σ金标∈盒 | Σ盒大小 | 盒大小分布 |",
        "|---|---:|---:|---:|---:|---|",
        (
            f"| RRF Top-7 | {tot7['gold_recall']} | {tot7['gold_precision']} | "
            f"{tot7['sum_gold_in_box']} | {tot7['sum_box_size']} | {tot7['box_sizes']} |"
        ),
        (
            f"| RRF Top-15 | {tot15['gold_recall']} | {tot15['gold_precision']} | "
            f"{tot15['sum_gold_in_box']} | {tot15['sum_box_size']} | {tot15['box_sizes']} |"
        ),
        (
            f"| 粗筛后盒子 | {tot_f['gold_recall']} | {tot_f['gold_precision']} | "
            f"{tot_f['sum_gold_in_box']} | {tot_f['sum_box_size']} | {tot_f['box_sizes']} |"
        ),
        "",
        f"- vs Top-7：覆盖 **{vs7['recall_vs']}**，占比 **{vs7['precision_vs']}**",
        f"- vs Top-15：覆盖 **{vs15['recall_vs']}**，占比 **{vs15['precision_vs']}**",
        "",
        "## 分题",
        "",
        "| qid | l2 | rrf7 r/p | rrf15 r/p | box r/p/size | bottleneck |",
        "|---|---:|---|---|---|---|",
    ]
    for q in q_rows:
        a, b, c = q["box_rrf7"], q["box_rrf15"], q["box_filtered"]
        lines.append(
            f"| {q['qid']} | {q['n_l2']} | "
            f"{a['gold_recall']}/{a['gold_precision']} | "
            f"{b['gold_recall']}/{b['gold_precision']} | "
            f"{c['gold_recall']}/{c['gold_precision']}/{c['box_size']} | "
            f"{q['diag']['bottleneck']} |"
        )

    lines += [
        "",
        "## 是否达到「覆盖升且占比升」",
        "",
        f"- 判定标准：覆盖升 **且** 占比升",
        f"- 相对 Top-7：**{'是' if goal_vs7 else '否'}**（覆盖{vs7['recall_vs']}／占比{vs7['precision_vs']}）",
        f"- 相对 Top-15：**{'是' if goal_vs15 else '否'}**（覆盖{vs15['recall_vs']}／占比{vs15['precision_vs']}）",
        f"- 总判：**{'达到' if both_up else '未达到'}**",
        "",
        "## 建议下一刀",
        "",
        f"- **{next_cut}**：{next_why}",
        "",
        "## 路径",
        f"- `{jp}`",
        f"- `{art / 'R3_fuse_and_box_filter.md'}`",
        "",
    ]
    mp = art / "R3_fuse_and_box_filter.md"
    mp.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {mp}", flush=True)
    print(
        f"COVER vs7={vs7['recall_vs']} vs15={vs15['recall_vs']} | "
        f"PREC vs7={vs7['precision_vs']} vs15={vs15['precision_vs']} | "
        f"next={next_cut}",
        flush=True,
    )
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
