#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2e：R2d 后刘翔同尺重测（只量；RRF 未融 paraphrase 则分列）。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.config import ARTIFACTS, DEFAULT_K, WIDE_K  # noqa: E402
from app.kg_lab.eval_metrics import leak_check, measure_arm  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.recall_arms import arm_rrf, run_all_arms  # noqa: E402
from app.kg_lab.slices import (  # noqa: E402
    pack_selected_for_question,
    union_pack_ids,
)
from scripts.kg_lab.probe_kg_spike_recall import hop_vs_rrf_diag  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
ARMS = (
    "q_bm25", "summary_bm25", "embedding", "paraphrase",
    "rrf_bm25_emb", "rrf_plus_hop", "oracle",
)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    t0 = time.perf_counter()
    case = next(
        p for p in (ROOT / "data" / "trs-samples").iterdir()
        if p.is_dir() and "刘翔" in p.name and (p / "raw_documents.json").is_file()
    )
    dossier, union_ids, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=SLUG, para_ids=union_ids)
    index = KgIndex(SLUG, rows)
    index.ensure_embeddings(force=False)

    # 确认当前 RRF 未融 paraphrase
    rrf_fuses_para = "paraphrase" in (
        arm_rrf.__doc__ or ""
    )  # weak; inspect source below
    import inspect
    rrf_src = inspect.getsource(arm_rrf)
    rrf_fuses_paraphrase = ("paraphrase" in rrf_src) or ("q_para" in rrf_src)

    q_rows: list[dict[str, Any]] = []
    for qrow in questions:
        qid = qrow["question_id"]
        question = qrow["question"]
        gold, skipped = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = {p for _d, p in gold if p in universe}
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(SLUG, sub_rows)
        sub.embeddings = {
            pid: v for pid, v in index.embeddings.items() if pid in universe
        }

        arms7 = run_all_arms(
            sub, question, k=DEFAULT_K, universe=universe, case_slug=SLUG,
            gold_para_ids=l2, include_oracle=True,
        )
        arms15 = run_all_arms(
            sub, question, k=WIDE_K, universe=universe, case_slug=SLUG,
            gold_para_ids=l2, include_oracle=True,
        )
        leaks = {n: leak_check(p, gold=gold) for n, p in arms7.items()}
        metrics7 = {
            n: measure_arm(p, gold=gold, universe=universe, k=DEFAULT_K)
            for n, p in arms7.items()
        }
        metrics15 = {
            n: measure_arm(p, gold=gold, universe=universe, k=WIDE_K)
            for n, p in arms15.items()
        }
        hop7 = hop_vs_rrf_diag(
            arms7["rrf_plus_hop"], arms7["rrf_bm25_emb"], gold_l2=l2, k=DEFAULT_K,
        )
        hop15 = hop_vs_rrf_diag(
            arms15["rrf_plus_hop"], arms15["rrf_bm25_emb"], gold_l2=l2, k=WIDE_K,
        )
        q_rows.append({
            "qid": qid,
            "question": question,
            "n_gold": len(gold),
            "n_l2": len(l2),
            "n_pack": len(universe),
            "skipped_locator": skipped,
            "hit_at_7": {a: metrics7[a]["n_gold_hit"] for a in ARMS if a in metrics7},
            "hit_at_15": {a: metrics15[a]["n_gold_hit"] for a in ARMS if a in metrics15},
            "hop_at_7": hop7,
            "hop_at_15": hop15,
            "leak_fail": [n for n, lk in leaks.items() if not lk.get("ok")],
            "leaks_ok": all(lk.get("ok") for lk in leaks.values()),
        })
        print(
            f"  {qid} L2={len(l2)} "
            f"sum7={metrics7['summary_bm25']['n_gold_hit']} "
            f"para7={metrics7.get('paraphrase', {}).get('n_gold_hit')} "
            f"rrf7={metrics7['rrf_bm25_emb']['n_gold_hit']} "
            f"hop_added={hop7['n_hop_added']} gold_via_hop={hop7['n_gold_via_hop']}",
            flush=True,
        )

    def sum_hit(key: str, arm: str) -> int:
        return sum(r[key].get(arm, 0) for r in q_rows)

    table7 = {a: sum_hit("hit_at_7", a) for a in ARMS}
    table15 = {a: sum_hit("hit_at_15", a) for a in ARMS}
    n_l2 = sum(r["n_l2"] for r in q_rows)
    leak_any = any(not r["leaks_ok"] for r in q_rows)
    hop_sum7 = {
        "n_hop_added": sum(r["hop_at_7"]["n_hop_added"] for r in q_rows),
        "n_gold_via_hop": sum(r["hop_at_7"]["n_gold_via_hop"] for r in q_rows),
        "gold_via_hop_ids": sorted({
            gid for r in q_rows for gid in r["hop_at_7"]["gold_via_hop"]
        }),
        "n_q_diff_rrf": sum(
            1 for r in q_rows if not r["hop_at_7"]["picked_equal_rrf"]
        ),
    }
    hop_sum15 = {
        "n_hop_added": sum(r["hop_at_15"]["n_hop_added"] for r in q_rows),
        "n_gold_via_hop": sum(r["hop_at_15"]["n_gold_via_hop"] for r in q_rows),
        "gold_via_hop_ids": sorted({
            gid for r in q_rows for gid in r["hop_at_15"]["gold_via_hop"]
        }),
    }

    # baselines
    r0 = _load_json(ARTIFACTS / "baseline_r0_liuxiang" / "summary.json")
    r0_7 = {
        row["arm"]: row["n_gold_hit"] for row in (r0.get("table_at_k") or [])
    }
    r0_case = _load_json(ARTIFACTS / "baseline_r0_liuxiang" / "case_liuxiang.json")
    r0_15 = {}
    if r0_case.get("questions"):
        # R0 case may lack wide summary — derive from metrics_at_wide_k if present
        for arm in ARMS:
            if arm == "paraphrase":
                continue
            r0_15[arm] = sum(
                (q.get("metrics_at_wide_k") or {}).get(arm, {}).get("n_gold_hit") or 0
                for q in r0_case["questions"]
            )

    r1_sum = _load_json(Path("/tmp/kg_spike_recall/r1_summary.json"))
    if not r1_sum:
        r1_sum = _load_json(Path("/tmp/kg_spike_recall/summary.json"))
    r1_7 = {row["arm"]: row["n_gold_hit"] for row in (r1_sum.get("table_at_k") or [])}
    r1_15 = {
        row["arm"]: row["n_gold_hit"] for row in (r1_sum.get("table_at_wide_k") or [])
    }
    r1_case = _load_json(Path("/tmp/kg_spike_recall/r1_case_liuxiang.json"))
    if not r1_case:
        r1_case = _load_json(Path("/tmp/kg_spike_recall/case_liuxiang.json"))
    r1_q002 = next(
        (q for q in (r1_case.get("questions") or []) if q.get("qid") == "q_002"),
        None,
    )
    r2c = _load_json(ARTIFACTS / "R2c_q002_summary_fix.json")
    r2d = _load_json(ARTIFACTS / "R2d_q002_query_expand.json")

    q002 = next(r for r in q_rows if r["qid"] == "q_002")

    # 下一刀建议
    para7 = table7.get("paraphrase", 0)
    rrf7 = table7.get("rrf_bm25_emb", 0)
    sum7 = table7.get("summary_bm25", 0)
    next_cut = {
        "choice": "收进主融合／粗筛",
        "why": (
            f"R2d 后 paraphrase 单臂@7={para7}、summary_bm25@7={sum7}，"
            f"而当前 RRF（未融 paraphrase）@7={rrf7}；"
            f"q_002 上 paraphrase/summary 已能打中对立口径金标，但 RRF 未吃到改写路。"
            f"下一刀把 paraphrase（或同义 expand 后的 summary 路）收进 RRF／粗筛，"
            f"比开 R2a 因果更直接——R1 hop 已上场但 gold_via_hop@7 仍弱，"
            f"因果对齐解决不了问句谓词↔金标用词的主缺口（R2d 已证明问句侧有效）。"
        ),
    }

    report = {
        "ticket": "R2e-post-expand-remeasure",
        "case": case.name,
        "k": DEFAULT_K,
        "wide_k": WIDE_K,
        "n_l2_total": n_l2,
        "rrf_fuses_paraphrase": rrf_fuses_paraphrase,
        "note_rrf": (
            "当前 arm_rrf = BM25原文 ⊕ summary(expand) ⊕ embedding；"
            "**未**融合 paraphrase 臂——报表分列。"
        ),
        "table_at_7": table7,
        "table_at_15": table15,
        "vs_r0_at_7": {a: table7.get(a, 0) - r0_7.get(a, 0) for a in r0_7},
        "vs_r1_at_7": {a: table7.get(a, 0) - r1_7.get(a, 0) for a in r1_7},
        "vs_r0_at_15": {
            a: table15.get(a, 0) - r0_15.get(a, 0) for a in r0_15
        },
        "vs_r1_at_15": {
            a: table15.get(a, 0) - r1_15.get(a, 0) for a in r1_15
        },
        "hop_at_7": hop_sum7,
        "hop_at_15": hop_sum15,
        "leak_any_bad": leak_any,
        "questions": q_rows,
        "q002_detail": {
            "hit_at_7": q002["hit_at_7"],
            "hit_at_15": q002["hit_at_15"],
            "r1_at_7": {
                a: (r1_q002 or {}).get("metrics_at_k", {}).get(a, {}).get("n_gold_hit")
                for a in ARMS if a != "paraphrase"
            },
            "r2c_at_7": (r2c.get("q002_hit_at_7") or {}).get("r2c"),
            "r2d_at_7": (r2d.get("q002_hit_at_7") or {}).get("r2d"),
        },
        "next_cut": next_cut,
        "wall_s": round(time.perf_counter() - t0, 3),
    }

    json_path = ARTIFACTS / "R2e_post_expand_remeasure.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# R2e — R2d 后刘翔同尺重测",
        "",
        f"- 案：{case.name}；k={DEFAULT_K}／wide_k={WIDE_K}；L2 合计={n_l2}",
        f"- RRF 是否融合 paraphrase：**{rrf_fuses_paraphrase}**（{report['note_rrf']}）",
        f"- leak_any_bad：**{leak_any}**",
        f"- 墙钟：{report['wall_s']}s（复用 embeddings）",
        "",
        "## 1) q_002 @7 / @15",
        "",
        "| arm | R1@7 | R2c@7 | R2d探针@7 | R2e@7 | R1@15 | R2e@15 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        lines.append(
            f"| {arm} | "
            f"{(report['q002_detail']['r1_at_7'] or {}).get(arm)} | "
            f"{(report['q002_detail']['r2c_at_7'] or {}).get(arm)} | "
            f"{(report['q002_detail']['r2d_at_7'] or {}).get(arm)} | "
            f"{q002['hit_at_7'].get(arm)} | "
            f"{(r1_q002 or {}).get('metrics_at_wide_k', {}).get(arm, {}).get('n_gold_hit') if r1_q002 and arm != 'paraphrase' else (q002['hit_at_15'].get(arm) if arm == 'paraphrase' else None)} | "
            f"{q002['hit_at_15'].get(arm)} |"
        )
    # fix messy R1@15 column - rewrite cleaner below in second pass
    lines = [
        "# R2e — R2d 后刘翔同尺重测",
        "",
        f"- 案：{case.name}；k={DEFAULT_K}／wide_k={WIDE_K}；L2 合计={n_l2}",
        f"- RRF 是否融合 paraphrase：**{rrf_fuses_paraphrase}**",
        f"- 说明：{report['note_rrf']}",
        f"- leak_any_bad：**{leak_any}**",
        f"- 墙钟：{report['wall_s']}s（复用 embeddings／vault）",
        "",
        "## 1) q_002 @7 / @15（相对 R1／R2c／R2d）",
        "",
        "| arm | R1@7 | R2c@7 | R2d@7 | **R2e@7** | R1@15 | **R2e@15** |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    r1_15_q2 = {
        a: (r1_q002 or {}).get("metrics_at_wide_k", {}).get(a, {}).get("n_gold_hit")
        for a in ARMS if a != "paraphrase"
    }
    for arm in ARMS:
        lines.append(
            f"| {arm} | "
            f"{(report['q002_detail']['r1_at_7'] or {}).get(arm)} | "
            f"{(report['q002_detail']['r2c_at_7'] or {}).get(arm)} | "
            f"{(report['q002_detail']['r2d_at_7'] or {}).get(arm)} | "
            f"**{q002['hit_at_7'].get(arm)}** | "
            f"{r1_15_q2.get(arm)} | "
            f"**{q002['hit_at_15'].get(arm)}** |"
        )

    lines += [
        "",
        f"- q_002 hop@7：n_hop_added={q002['hop_at_7']['n_hop_added']} "
        f"gold_via_hop={q002['hop_at_7']['n_gold_via_hop']} "
        f"equal_rrf={q002['hop_at_7']['picked_equal_rrf']}",
        "",
        "## 2) 三题合计 @7 / @15（相对 R0／R1）",
        "",
        "| arm | R0@7 | R1@7 | **R2e@7** | ΔR0 | ΔR1 | R0@15 | R1@15 | **R2e@15** |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        if arm == "paraphrase":
            lines.append(
                f"| paraphrase（单臂） | — | — | **{table7[arm]}** | — | — | — | — | **{table15[arm]}** |"
            )
            continue
        lines.append(
            f"| {arm} | {r0_7.get(arm)} | {r1_7.get(arm)} | **{table7.get(arm)}** | "
            f"{table7.get(arm, 0) - (r0_7.get(arm) or 0):+d} | "
            f"{table7.get(arm, 0) - (r1_7.get(arm) or 0):+d} | "
            f"{r0_15.get(arm)} | {r1_15.get(arm)} | **{table15.get(arm)}** |"
        )

    lines += [
        "",
        "## 3) hop／leak 健康度",
        "",
        f"- @7：n_hop_added={hop_sum7['n_hop_added']} "
        f"gold_via_hop={hop_sum7['n_gold_via_hop']} "
        f"ids={hop_sum7['gold_via_hop_ids']} "
        f"q_diff_vs_rrf={hop_sum7['n_q_diff_rrf']}/3",
        f"- @15：n_hop_added={hop_sum15['n_hop_added']} "
        f"gold_via_hop={hop_sum15['n_gold_via_hop']} "
        f"ids={hop_sum15['gold_via_hop_ids']}",
        f"- leak_any_bad={leak_any}",
        "",
        "## 分题 hit@7",
        "",
        "| qid | L2 | ① | ②sum | ③emb | ⑥para | ④RRF | ⑤hop |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in q_rows:
        h = r["hit_at_7"]
        lines.append(
            f"| {r['qid']} | {r['n_l2']} | {h.get('q_bm25')} | {h.get('summary_bm25')} | "
            f"{h.get('embedding')} | {h.get('paraphrase')} | {h.get('rrf_bm25_emb')} | "
            f"{h.get('rrf_plus_hop')} |"
        )

    lines += [
        "",
        "## 4) 建议的唯一下一刀",
        "",
        f"**{next_cut['choice']}**",
        "",
        next_cut["why"],
        "",
        "## 路径",
        f"- `{json_path}`",
        f"- `{ARTIFACTS / 'R2e_post_expand_remeasure.md'}`",
        "",
    ]
    md_path = ARTIFACTS / "R2e_post_expand_remeasure.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {md_path}", flush=True)
    print(f"q002@7={q002['hit_at_7']}", flush=True)
    print(f"total@7={table7}", flush=True)
    print(f"NEXT={next_cut['choice']}", flush=True)
    print(f"leak={leak_any} rrf_fuses_para={rrf_fuses_paraphrase}", flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
