#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2g：expand top_n=30 + paraphrase×10 RRF 融合后重测。"""

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
from app.kg_lab.index_build import KgIndex, build_corpus_rows, keyword_expand_query  # noqa: E402
from app.kg_lab.query_expand import (  # noqa: E402
    DEFAULT_EXPAND_TOP_N,
    DEFAULT_PARAPHRASE_N,
    expand_query_parts,
    rule_paraphrase_questions,
)
from app.kg_lab.recall_arms import run_all_arms  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
ARMS = (
    "q_bm25", "summary_bm25", "embedding", "paraphrase",
    "rrf_bm25_emb", "rrf_plus_hop", "oracle",
)
RANK_K = 50


def _rank_at(
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


def main() -> int:
    t0 = time.perf_counter()
    case = next(
        p for p in (ROOT / "data" / "trs-samples").iterdir()
        if p.is_dir() and "刘翔" in p.name and (p / "raw_documents.json").is_file()
    )
    dossier, union_ids, questions = union_pack_ids(case)
    rows_all = build_corpus_rows(dossier, case_slug=SLUG, para_ids=union_ids)
    index = KgIndex(SLUG, rows_all)
    index.ensure_embeddings(force=False)

    # expand / paraphrase audit on q_002
    q002_row = next(q for q in questions if q["question_id"] == "q_002")
    parts = expand_query_parts(q002_row["question"], rows_all, top_n=DEFAULT_EXPAND_TOP_N)
    paras = rule_paraphrase_questions(q002_row["question"], n=DEFAULT_PARAPHRASE_N)

    q_rows: list[dict[str, Any]] = []
    for qrow in questions:
        qid = qrow["question_id"]
        question = qrow["question"]
        gold, _ = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = {p for _d, p in gold if p in universe}
        sub_rows = [r for r in rows_all if r["para_id"] in universe]
        sub = KgIndex(SLUG, sub_rows)
        sub.embeddings = {
            pid: v for pid, v in index.embeddings.items() if pid in universe
        }
        a7 = run_all_arms(
            sub, question, k=DEFAULT_K, universe=universe, case_slug=SLUG,
            gold_para_ids=l2, include_oracle=True,
        )
        a15 = run_all_arms(
            sub, question, k=WIDE_K, universe=universe, case_slug=SLUG,
            gold_para_ids=l2, include_oracle=True,
        )
        leaks = {n: leak_check(p, gold=gold) for n, p in a7.items()}
        m7 = {
            n: measure_arm(p, gold=gold, universe=universe, k=DEFAULT_K)
            for n, p in a7.items()
        }
        m15 = {
            n: measure_arm(p, gold=gold, universe=universe, k=WIDE_K)
            for n, p in a15.items()
        }
        row = {
            "qid": qid,
            "n_l2": len(l2),
            "hit_at_7": {a: m7[a]["n_gold_hit"] for a in ARMS if a in m7},
            "hit_at_15": {a: m15[a]["n_gold_hit"] for a in ARMS if a in m15},
            "leak_ok": all(lk.get("ok") for lk in leaks.values()),
            "paraphrase_variants": (a7.get("paraphrase") or {}).get("paraphrase_variants"),
            "n_paraphrases": (a7.get("paraphrase") or {}).get("n_paraphrases"),
        }
        if qid == "q_002":
            # @50 ranks for gold
            q_exp = keyword_expand_query(question, sub.rows)
            r_sum = sub.bm25_summary(q_exp)
            r_emb = sub.embed_rank(question)
            r_q = sub.bm25_text(question)
            # paraphrase fused list
            para_ids = [
                x["para_id"] for x in (a15.get("paraphrase") or {}).get("picked") or []
            ]
            # rebuild full paraphrase ranking via arm at k=50
            a50 = run_all_arms(
                sub, question, k=RANK_K, universe=universe, case_slug=SLUG,
                gold_para_ids=l2, include_oracle=True,
            )
            ranks50 = {}
            for pid in sorted(l2):
                ranks50[pid] = {
                    "q_bm25": _rank_at(r_q, universe, pid, RANK_K),
                    "summary_bm25": _rank_at(r_sum, universe, pid, RANK_K),
                    "embedding": _rank_at(r_emb, universe, pid, RANK_K),
                    "paraphrase": _rank_at(
                        [
                            (p["para_id"], p["score"])
                            for p in (a50.get("paraphrase") or {}).get("picked") or []
                        ]
                        + [
                            # pad: use score order already in picked; if truncated miss
                        ],
                        universe,
                        pid,
                        RANK_K,
                    ),
                }
                # better: from full fused list in arm internals — re-call ranking
            # Fix paraphrase ranks using full fused from arm at k=50 picked only —
            # if not in top50, miss. Also compute via picked index:
            para_picked = [
                p["para_id"]
                for p in (a50.get("paraphrase") or {}).get("picked") or []
            ]
            for pid in ranks50:
                try:
                    ranks50[pid]["paraphrase"] = para_picked.index(pid) + 1
                except ValueError:
                    ranks50[pid]["paraphrase"] = None
            row["ranks_at_50"] = ranks50
            row["expand_n_merged"] = parts["n_merged_extras"]
            row["expanded_query"] = parts["expanded_query"]
        q_rows.append(row)
        print(
            f"  {qid} sum7={row['hit_at_7'].get('summary_bm25')} "
            f"para7={row['hit_at_7'].get('paraphrase')} "
            f"rrf7={row['hit_at_7'].get('rrf_bm25_emb')}",
            flush=True,
        )

    table7 = {a: sum(r["hit_at_7"].get(a, 0) for r in q_rows) for a in ARMS}
    table15 = {a: sum(r["hit_at_15"].get(a, 0) for r in q_rows) for a in ARMS}
    leak_any = any(not r["leak_ok"] for r in q_rows)

    r2f = json.loads(
        (ARTIFACTS / "R2f_expand20_para5.json").read_text(encoding="utf-8")
    )
    r2f7 = r2f.get("table_at_7") or {}
    r2f15 = r2f.get("table_at_15") or {}
    r2f_q2 = (r2f.get("q002_detail") or {}).get("hit_at_7") or {}
    r2f_q2_15 = None
    for q in r2f.get("questions") or []:
        if q.get("qid") == "q_002":
            r2f_q2 = q.get("hit_at_7") or r2f_q2
            r2f_q2_15 = q.get("hit_at_15")
            break
    q2 = next(r for r in q_rows if r["qid"] == "q_002")

    delta7 = {a: table7.get(a, 0) - (r2f7.get(a) or 0) for a in ARMS if a in r2f7 or a == "paraphrase"}
    # include paraphrase always
    for a in ARMS:
        delta7[a] = table7.get(a, 0) - (r2f7.get(a) or 0)
    delta15 = {a: table15.get(a, 0) - (r2f15.get(a) or 0) for a in ARMS}

    any_change = any(v != 0 for v in delta7.values()) or any(
        v != 0 for v in delta15.values()
    )
    q2_change = q2["hit_at_7"] != r2f_q2

    report = {
        "ticket": "R2g-expand30-para10",
        "params": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "paraphrase_n": DEFAULT_PARAPHRASE_N,
            "paraphrase_fuse": f"rrf_over_{DEFAULT_PARAPHRASE_N}x(summary_bm25+embedding)",
        },
        "expand_q002": {
            "n_merged_extras": parts["n_merged_extras"],
            "synonyms_added": parts["synonyms_added"],
            "corpus_extras": parts["corpus_extras"],
            "expanded_query": parts["expanded_query"],
        },
        "paraphrase_queries_q002": paras,
        "table_at_7": table7,
        "table_at_15": table15,
        "delta_vs_r2f_at_7": delta7,
        "delta_vs_r2f_at_15": delta15,
        "q002_hit_at_7": {"r2f": r2f_q2, "r2g": q2["hit_at_7"]},
        "q002_hit_at_15": {"r2f": r2f_q2_15, "r2g": q2["hit_at_15"]},
        "q002_ranks_at_50": q2.get("ranks_at_50"),
        "questions": q_rows,
        "leak_any_bad": leak_any,
        "any_numeric_change_vs_r2f": any_change or q2_change,
        "one_liner": (
            "有实质变化" if (any_change or q2_change) else "相对 R2f 无实质数字变化（持平）"
        )
        + (
            f"：三题@7 paraphrase {r2f7.get('paraphrase')}→{table7['paraphrase']}，"
            f"summary {r2f7.get('summary_bm25')}→{table7['summary_bm25']}，"
            f"RRF {r2f7.get('rrf_bm25_emb')}→{table7['rrf_bm25_emb']}，"
            f"hop {r2f7.get('rrf_plus_hop')}→{table7['rrf_plus_hop']}；"
            f"q_002@7 {r2f_q2}→{q2['hit_at_7']}。"
        ),
        "wall_s": round(time.perf_counter() - t0, 3),
    }

    json_path = ARTIFACTS / "R2g_expand30_para10.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# R2g — expand top_n=30 + paraphrase×10 融合重测",
        "",
        "## 参数变更",
        f"- `expand` 合计上限：**20 → {DEFAULT_EXPAND_TOP_N}**（同义优先）",
        f"- 整句改写：**5 → {DEFAULT_PARAPHRASE_N}**；融合=`rrf_over_{DEFAULT_PARAPHRASE_N}x(summary_bm25+embedding)`（与 R2f 同形）",
        f"- 未改 hop／因果／摘要；主仓未动",
        f"- leak_any_bad：**{leak_any}**",
        "",
        f"## {DEFAULT_PARAPHRASE_N} 条改写问句（q_002）",
        "",
    ]
    for v in paras:
        lines.append(f"- **{v['id']}**（{v['rule']}）")
        lines.append(f"  - `{v['query']}`")
    lines += [
        "",
        f"- expand 后 extras 数：{parts['n_merged_extras']}／{DEFAULT_EXPAND_TOP_N}",
        f"- expanded：`{parts['expanded_query']}`",
        "",
        "## 相对 R2f 数字",
        "",
        "### 三题合计 @7",
        "",
        "| arm | R2f@7 | R2g@7 | Δ |",
        "|---|---:|---:|---:|",
    ]
    for a in ARMS:
        lines.append(
            f"| {a} | {r2f7.get(a)} | {table7.get(a)} | {delta7.get(a, 0):+d} |"
        )
    lines += [
        "",
        "### 三题合计 @15",
        "",
        "| arm | R2f@15 | R2g@15 | Δ |",
        "|---|---:|---:|---:|",
    ]
    for a in ARMS:
        lines.append(
            f"| {a} | {r2f15.get(a)} | {table15.get(a)} | {delta15.get(a, 0):+d} |"
        )
    lines += [
        "",
        "### q_002 hit",
        "",
        f"- R2f@7：{r2f_q2}",
        f"- R2g@7：{q2['hit_at_7']}",
        f"- R2f@15：{r2f_q2_15}",
        f"- R2g@15：{q2['hit_at_15']}",
        "",
        "### q_002 金标 @50",
        "",
        "| para_id | ① | ②sum | ③emb | ⑥para融合 |",
        "|---|---:|---:|---:|---:|",
    ]
    for pid, rk in (q2.get("ranks_at_50") or {}).items():
        def fmt(v: int | None) -> str:
            return "miss" if v is None else str(v)
        lines.append(
            f"| `{pid}` | {fmt(rk.get('q_bm25'))} | {fmt(rk.get('summary_bm25'))} | "
            f"{fmt(rk.get('embedding'))} | {fmt(rk.get('paraphrase'))} |"
        )
    lines += [
        "",
        "## 一句话",
        "",
        report["one_liner"],
        "",
        f"- 墙钟：{report['wall_s']}s",
        f"- 报告：`{json_path}`／`{ARTIFACTS / 'R2g_expand30_para10.md'}`",
        "",
    ]
    md_path = ARTIFACTS / "R2g_expand30_para10.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {md_path}", flush=True)
    print(report["one_liner"], flush=True)
    print(f"leak={leak_any} change={report['any_numeric_change_vs_r2f']}", flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
