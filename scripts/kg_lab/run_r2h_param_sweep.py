#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2h：expand_top_n × n_paraphrase 网格寻优（刘翔；复用 index）。"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.kg_lab.query_expand as qe  # noqa: E402
from app.kg_lab.config import ARTIFACTS, DEFAULT_K, WIDE_K  # noqa: E402
from app.kg_lab.eval_metrics import leak_check, measure_arm  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.recall_arms import run_all_arms  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
EXPAND_GRID = (8, 12, 16, 20, 24)
PARA_GRID = (1, 3, 5, 7)
ARM_KEYS = (
    "summary_bm25", "embedding", "paraphrase", "rrf_bm25_emb", "rrf_plus_hop",
)


def _set_quota(e: int, p: int) -> None:
    qe.DEFAULT_EXPAND_TOP_N = int(e)
    qe.DEFAULT_PARAPHRASE_N = int(p)


def _hits(arms: dict[str, Any], gold: dict, universe: set[str], k: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in ARM_KEYS:
        if name not in arms:
            continue
        out[name] = measure_arm(
            arms[name], gold=gold, universe=universe, k=k,
        )["n_gold_hit"]
    return out


def _eval_case(
    *,
    dossier,
    rows_all: list[dict[str, Any]],
    index: KgIndex,
    questions: list[dict[str, str]],
    case_dir: Path,
    qids: list[str] | None,
) -> dict[str, Any]:
    q_blocks: list[dict[str, Any]] = []
    leak_any = False
    for qrow in questions:
        qid = qrow["question_id"]
        if qids is not None and qid not in qids:
            continue
        question = qrow["question"]
        gold, _ = gold_paras_for_question(case_dir, qid)
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
        for pick in a7.values():
            if not leak_check(pick, gold=gold).get("ok"):
                leak_any = True
        q_blocks.append({
            "qid": qid,
            "n_l2": len(l2),
            "hit_at_7": _hits(a7, gold, universe, DEFAULT_K),
            "hit_at_15": _hits(a15, gold, universe, WIDE_K),
            "n_paraphrases": (a7.get("paraphrase") or {}).get("n_paraphrases"),
            "expand_top_n_live": qe.DEFAULT_EXPAND_TOP_N,
        })
    tot7 = {a: sum(q["hit_at_7"].get(a, 0) for q in q_blocks) for a in ARM_KEYS}
    tot15 = {a: sum(q["hit_at_15"].get(a, 0) for q in q_blocks) for a in ARM_KEYS}
    q002 = next((q for q in q_blocks if q["qid"] == "q_002"), None)
    return {
        "questions": q_blocks,
        "total_at_7": tot7,
        "total_at_15": tot15,
        "q002_at_7": (q002 or {}).get("hit_at_7"),
        "q002_at_15": (q002 or {}).get("hit_at_15"),
        "leak_any_bad": leak_any,
        "n_l2_total": sum(q["n_l2"] for q in q_blocks),
    }


def _score_row(row: dict[str, Any]) -> tuple:
    """涨分优先排序键（越大越好）；平手用更小 E/P。"""
    q7 = row.get("q002_at_7") or {}
    t7 = row.get("total_at_7") or {}
    # 主：q_002 summary + rrf + paraphrase + emb；次：三题合计同样
    primary = (
        int(q7.get("summary_bm25") or 0)
        + int(q7.get("rrf_bm25_emb") or 0)
        + int(q7.get("paraphrase") or 0)
        + int(q7.get("embedding") or 0)
        + int(q7.get("rrf_plus_hop") or 0)
    )
    secondary = (
        int(t7.get("summary_bm25") or 0)
        + int(t7.get("rrf_bm25_emb") or 0)
        + int(t7.get("paraphrase") or 0)
        + int(t7.get("embedding") or 0)
        + int(t7.get("rrf_plus_hop") or 0)
    )
    # paraphrase 稀释惩罚：若 q002 summary/rrf 不变但 para 掉，secondary 已反映
    return (primary, secondary, -int(row["E"]), -int(row["P"]))


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

    # Phase 1: q_002 only full grid
    phase1: list[dict[str, Any]] = []
    print(f"Phase1 q_002 grid |E|={len(EXPAND_GRID)} |P|={len(PARA_GRID)}", flush=True)
    for e in EXPAND_GRID:
        for p in PARA_GRID:
            _set_quota(e, p)
            t_cell = time.perf_counter()
            res = _eval_case(
                dossier=dossier, rows_all=rows_all, index=index,
                questions=questions, case_dir=case, qids=["q_002"],
            )
            row = {
                "E": e, "P": p,
                "phase": "q002_only",
                **{k: res[k] for k in (
                    "q002_at_7", "q002_at_15", "total_at_7", "total_at_15",
                    "leak_any_bad", "n_l2_total",
                )},
                "wall_s": round(time.perf_counter() - t_cell, 3),
            }
            phase1.append(row)
            q7 = row["q002_at_7"]
            print(
                f"  E={e:2d} P={p} q002@7 "
                f"sum={q7.get('summary_bm25')} emb={q7.get('embedding')} "
                f"para={q7.get('paraphrase')} rrf={q7.get('rrf_bm25_emb')} "
                f"hop={q7.get('rrf_plus_hop')} leak={row['leak_any_bad']} "
                f"{row['wall_s']}s",
                flush=True,
            )
            if row["leak_any_bad"]:
                print("LEAK FAIL — abort", flush=True)
                return 3

    # Top-3 by score → full 3-question remeasure；强制带上拍脑袋基线 20/5
    ranked = sorted(phase1, key=_score_row, reverse=True)
    top3 = ranked[:3]
    phase2_keys: list[tuple[int, int]] = []
    for r in top3:
        phase2_keys.append((r["E"], r["P"]))
    if (20, 5) not in phase2_keys:
        phase2_keys.append((20, 5))
    print(f"Phase2 full-case: {phase2_keys}", flush=True)
    phase2: list[dict[str, Any]] = []
    for e, p in phase2_keys:
        _set_quota(e, p)
        t_cell = time.perf_counter()
        res = _eval_case(
            dossier=dossier, rows_all=rows_all, index=index,
            questions=questions, case_dir=case, qids=None,
        )
        row = {
            "E": e, "P": p,
            "phase": "full_3q",
            **{k: res[k] for k in (
                "q002_at_7", "q002_at_15", "total_at_7", "total_at_15",
                "leak_any_bad", "n_l2_total",
            )},
            "wall_s": round(time.perf_counter() - t_cell, 3),
        }
        phase2.append(row)
        print(
            f"  E={e} P={p} total@7 sum={row['total_at_7'].get('summary_bm25')} "
            f"para={row['total_at_7'].get('paraphrase')} "
            f"rrf={row['total_at_7'].get('rrf_bm25_emb')} "
            f"q002={row['q002_at_7']}",
            flush=True,
        )
        if row["leak_any_bad"]:
            return 3

    ref_q002 = next((r for r in phase1 if r["E"] == 20 and r["P"] == 5), None)
    ref_full = next((r for r in phase2 if r["E"] == 20 and r["P"] == 5), None)
    ref = ref_full or ref_q002
    # Prefer full-case ranking for recommendation among phase2
    full_ranked = sorted(phase2, key=_score_row, reverse=True)
    best = full_ranked[0] if full_ranked else ranked[0]

    def _cmp_to_ref(row: dict[str, Any]) -> str:
        """同口径：优先 full_3q 对 full_3q；否则只比 q002。"""
        if not ref:
            return "no_ref"
        # 主看 q002 五臂和；次看合计五臂和（仅双方都有 full 时）
        aq = _score_row(row)[0]
        bq = _score_row(ref)[0]
        if aq > bq:
            return "更好"
        if aq < bq:
            return "更差"
        if row.get("phase") == "full_3q" and ref.get("phase") == "full_3q":
            at = _score_row(row)[1]
            bt = _score_row(ref)[1]
            if at > bt:
                return "更好"
            if at < bt:
                return "更差"
        return "持平"

    # Pareto: non-dominated on (q002_primary, total_primary) with smaller E,P preferred when equal
    def primaries(r: dict[str, Any]) -> tuple[int, int]:
        sc = _score_row(r)
        return int(sc[0]), int(sc[1])

    pareto: list[dict[str, Any]] = []
    # use phase1 for pareto front on q002; annotate with full if available
    full_map = {(r["E"], r["P"]): r for r in phase2}
    for r in ranked:
        pr = primaries(full_map.get((r["E"], r["P"]), r))
        dominated = False
        for o in ranked:
            if o is r:
                continue
            op = primaries(full_map.get((o["E"], o["P"]), o))
            # o dominates r if all >= and one >
            if (op[0] >= pr[0] and op[1] >= pr[1]) and (op[0] > pr[0] or op[1] > pr[1]):
                # also prefer smaller E,P when scores equal — domination ignores size
                dominated = True
                break
        if not dominated:
            # check equal-score smaller E/P
            same = [
                o for o in ranked
                if primaries(full_map.get((o["E"], o["P"]), o)) == pr
            ]
            smallest = min(same, key=lambda x: (x["E"], x["P"]))
            if r["E"] == smallest["E"] and r["P"] == smallest["P"]:
                pareto.append(r)

    vs = _cmp_to_ref(best)
    recommend = {
        "E": best["E"],
        "P": best["P"],
        "vs_20_5": vs,
        "why": (
            f"q_002@7={best.get('q002_at_7')}；三题合计@7={best.get('total_at_7')}；"
            f"相对 20/5（同口径 full）＝{vs}；"
            f"涨分优先，平手取更小 E/P 防稀释（本推荐 E={best['E']} P={best['P']}）。"
        ),
    }

    # restore defaults to last recommended for tree usability
    _set_quota(recommend["E"], recommend["P"])

    report = {
        "ticket": "R2h-param-sweep",
        "grid": {"expand_top_n": list(EXPAND_GRID), "n_paraphrase": list(PARA_GRID)},
        "ref_20_5": ref,
        "ref_20_5_q002_only": ref_q002,
        "phase1_q002": phase1,
        "phase2_full_top3": phase2,
        "pareto_q002": [{"E": r["E"], "P": r["P"], "q002_at_7": r["q002_at_7"]} for r in pareto],
        "recommend": recommend,
        "leak_any_bad": any(r["leak_any_bad"] for r in phase1 + phase2),
        "wall_s": round(time.perf_counter() - t0, 3),
    }

    art = ARTIFACTS
    json_path = art / "R2h_param_sweep.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = art / "R2h_param_sweep.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "phase", "E", "P",
            "q002_sum7", "q002_emb7", "q002_para7", "q002_rrf7", "q002_hop7",
            "q002_sum15", "q002_emb15", "q002_para15", "q002_rrf15", "q002_hop15",
            "tot_sum7", "tot_emb7", "tot_para7", "tot_rrf7", "tot_hop7",
            "tot_sum15", "tot_emb15", "tot_para15", "tot_rrf15", "tot_hop15",
            "leak", "wall_s",
        ])
        for r in phase1 + phase2:
            q7 = r.get("q002_at_7") or {}
            q15 = r.get("q002_at_15") or {}
            t7 = r.get("total_at_7") or {}
            t15 = r.get("total_at_15") or {}
            w.writerow([
                r["phase"], r["E"], r["P"],
                q7.get("summary_bm25"), q7.get("embedding"), q7.get("paraphrase"),
                q7.get("rrf_bm25_emb"), q7.get("rrf_plus_hop"),
                q15.get("summary_bm25"), q15.get("embedding"), q15.get("paraphrase"),
                q15.get("rrf_bm25_emb"), q15.get("rrf_plus_hop"),
                t7.get("summary_bm25"), t7.get("embedding"), t7.get("paraphrase"),
                t7.get("rrf_bm25_emb"), t7.get("rrf_plus_hop"),
                t15.get("summary_bm25"), t15.get("embedding"), t15.get("paraphrase"),
                t15.get("rrf_bm25_emb"), t15.get("rrf_plus_hop"),
                r["leak_any_bad"], r["wall_s"],
            ])

    # markdown
    lines = [
        "# R2h — expand × paraphrase 网格寻优",
        "",
        f"- 网格：E∈{list(EXPAND_GRID)}，P∈{list(PARA_GRID)}（最多 {len(EXPAND_GRID)*len(PARA_GRID)} 点）",
        f"- Phase1＝仅 q_002；Phase2＝Top‑3 全三题合计",
        f"- leak_any_bad：**{report['leak_any_bad']}**",
        f"- 墙钟：{report['wall_s']}s",
        "",
        f"## 推荐默认：**(E={recommend['E']}, P={recommend['P']})**",
        "",
        f"- 相对拍脑袋 20/5：**{recommend['vs_20_5']}**",
        f"- 理由：{recommend['why']}",
        "",
        "## Pareto（q_002 主分，平手取小 E/P）",
        "",
    ]
    for r in pareto:
        lines.append(
            f"- ({r['E']},{r['P']}) q002@7={r['q002_at_7']}"
        )
    lines += [
        "",
        "## Phase1 全表（q_002）",
        "",
        "| E | P | sum7 | emb7 | para7 | rrf7 | hop7 | sum15 | para15 | rrf15 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(phase1, key=lambda x: (x["E"], x["P"])):
        q7, q15 = r["q002_at_7"], r["q002_at_15"]
        mark = " ←ref" if (r["E"], r["P"]) == (20, 5) else ""
        if (r["E"], r["P"]) == (recommend["E"], recommend["P"]):
            mark += " ★"
        lines.append(
            f"| {r['E']} | {r['P']} | {q7.get('summary_bm25')} | {q7.get('embedding')} | "
            f"{q7.get('paraphrase')} | {q7.get('rrf_bm25_emb')} | {q7.get('rrf_plus_hop')} | "
            f"{q15.get('summary_bm25')} | {q15.get('paraphrase')} | {q15.get('rrf_bm25_emb')} |"
            f"{mark}"
        )
    lines += [
        "",
        "## Phase2 三题合计（Top‑3 ＋ 强制基线 20/5）",
        "",
        "| E | P | tot_sum7 | tot_para7 | tot_rrf7 | tot_hop7 | q002@7 | vs_20/5 |",
        "|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in full_ranked:
        t7 = r["total_at_7"]
        mark = " ←ref" if (r["E"], r["P"]) == (20, 5) else ""
        if (r["E"], r["P"]) == (best["E"], best["P"]):
            mark += " ★"
        lines.append(
            f"| {r['E']} | {r['P']} | {t7.get('summary_bm25')} | {t7.get('paraphrase')} | "
            f"{t7.get('rrf_bm25_emb')} | {t7.get('rrf_plus_hop')} | {r['q002_at_7']} | "
            f"{_cmp_to_ref(r)}{mark} |"
        )
    # dilution note — q002 上 para 平坦；稀释主要看三题合计 para
    lines += [
        "",
        "## 稀释观察",
        "",
        "- Phase1（q_002）：para@7 全网格＝1（本问不敏感）。",
        "- Phase1 hop@7：E≤12 → 0；E≥16 → 1（扩词门槛）。",
        "- Phase2（三题合计 para@7）：",
    ]
    for r in sorted(phase2, key=lambda x: (x["E"], x["P"])):
        t7 = r["total_at_7"]
        flag = " ←稀释" if int(t7.get("paraphrase") or 0) < 4 else ""
        lines.append(
            f"  - E={r['E']} P={r['P']}: tot_para7={t7.get('paraphrase')} "
            f"tot_sum7={t7.get('summary_bm25')} tot_rrf7={t7.get('rrf_bm25_emb')}"
            f"{flag}"
        )

    lines += [
        "",
        "## 路径",
        f"- `{json_path}`",
        f"- `{csv_path}`",
        f"- `{art / 'R2h_param_sweep.md'}`",
        "",
    ]
    md_path = art / "R2h_param_sweep.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {md_path}", flush=True)
    print(
        f"RECOMMEND (E,P)=({recommend['E']},{recommend['P']}) "
        f"vs_20/5={recommend['vs_20_5']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
