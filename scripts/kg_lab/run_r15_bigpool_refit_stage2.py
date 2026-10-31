#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R15：一筛放大到池 30，二筛加维后整表重拟合，再缩到交卷前 7。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.config import DEFAULT_K, WIDE_K  # noqa: E402
from app.kg_lab.eval_metrics import leak_check  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.r8_fit import FEATURE_NAMES, augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import R9_ADDED, apply_r9, r9_names  # noqa: E402
from app.kg_lab.r15_stage2 import R15_DIMS, cut_question, fit_r15, pool_rows  # noqa: E402
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slice_dims import SLICE_DIMS, apply_slice_dims  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
OUT = ROOT / "artifacts"
POOL = 30


def _rank(order: list[tuple[str, float]], pid: str) -> int | None:
    for i, (p, _sc) in enumerate(order, 1):
        if p == pid:
            return i
    return None


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R15 — 大盒后再拟合二筛",
        "",
        f"一筛沿用 R14 已拟合的系数，候选池放到 **{POOL}**，盖住 `doc_009#p5`（约第 10）和 `doc_029#p7`（约第 19）。",
        "二筛在这只大盒上重搜整张系数表，网格 ±0.12，初值全 0。新加的维是综述、一筛分在盒内的位置、以及是否把别的段拼进去。",
        "分数 < 0 的踢掉，剩下按二筛分数取前 7。不够 7 就短交，被踢的不补回。线上不读金标 id。",
        f"leak_any_bad：**{report['leak_any_bad']}**。墙钟 {report['wall_s']}s。",
        "",
        "## 金标进大盒",
        "",
        f"14 条里进了池 {POOL} 的有 **{report['gold_in_pool']}** 条。",
        "",
    ]
    for row in report["missing"]:
        lines.append(f"- `{row['id']}` {row['qid']}：{row['why']}")
    if not report["missing"]:
        lines.append("14 条都在大盒里。")
    lines += [
        "",
        "## 二筛后交卷 @7",
        "",
        f"严格命中 **{report['sum_hits']}**，交卷一共 **{report['sum_final']}** 条，其中非金标 **{report['sum_nongold']}** 条。",
        "",
        "| qid | 金标 | 进大盒 | 交卷 | 命中 | 还剩非金标 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for q in report["questions"]:
        nongold = "、".join(f"`{x}`" for x in q["nongold"]) or "无"
        lines.append(
            f"| {q['qid']} | {q['n_l2']} | {q['gold_in_pool']} | {q['n_final']} | {q['n_hits']} | {nongold} |"
        )
    lines += ["", "交卷：", ""]
    for q in report["questions"]:
        lines.append(f"- {q['qid']}：" + "、".join(f"`{x}`" for x in q["final"]))
    lines += ["", "## 二筛系数", "", "| 维 | 系数 |", "|---|---:|"]
    for name, val in report["coeff_table"]:
        lines.append(f"| `{name}` | {val} |")
    lines += ["", "轨迹：", ""]
    for step in report["trace"]:
        lines.append(
            f"- {step['step']}：交卷金标 {step['gold_kept']}，非金标 {step['nongold_kept']}，L2={step['l2']}"
        )
    lines += [
        "",
        "## 读法",
        "",
        report["reading"],
        "",
        "系数在这 3 题上拟合，没有留出题。",
        "",
        "## 路径",
        f"- `{OUT / 'R15_bigpool_refit_stage2.json'}`",
        f"- `{OUT / 'R15_bigpool_refit_stage2.md'}`",
        "",
    ]
    return "\n".join(lines)


def _reading(report: dict[str, Any]) -> str:
    miss = "、".join(f"`{r['id']}`" for r in report["missing"]) or "没有缺"
    return (
        f"池 {POOL} 收进严格金标 {report['gold_in_pool']}/14，没进的是 {miss}。"
        f"二筛再缩到交卷后严格命中 {report['sum_hits']}，非金标还剩 {report['sum_nongold']} 条。"
    )


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
    r14 = json.loads((OUT / "R14_refit_both_stages.json").read_text(encoding="utf-8"))
    names = R9_ADDED + tuple(n for n in r9_names(FEATURE_NAMES) if n not in R9_ADDED)
    names = names + tuple(n for n in SLICE_DIMS if n not in names)
    coeff = {n: float(r14["stage1_coeff"].get(n) or 0.0) for n in names}
    case = next(
        p for p in (ROOT / "data" / "trs-samples").iterdir()
        if p.is_dir() and "刘翔" in p.name and (p / "raw_documents.json").is_file()
    )
    url_of = {
        str(d.get("doc_id")): str(d.get("content_url") or "")
        for d in json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    }
    dossier, union_ids, questions = union_pack_ids(case)
    rows_all = build_corpus_rows(dossier, case_slug=SLUG, para_ids=union_ids)
    index = KgIndex(SLUG, rows_all)
    index.ensure_embeddings(force=False)
    bundles = []
    leak_any = False
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        print(f"=== fuse {qid} ===", flush=True)
        gold, _ = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for _d, p in gold if p in universe)
        sub_rows = [r for r in rows_all if r["para_id"] in universe]
        sub = KgIndex(SLUG, sub_rows)
        sub.embeddings = {pid: v for pid, v in index.embeddings.items() if pid in universe}
        fused, queries, _pm, _n = _fuse_rrf(sub, question)
        if not leak_check({"queries": queries, "selection_used_gold": False}, gold=gold).get("ok"):
            leak_any = True
        bundle = build_bundle(sub_rows, fused, question, frames=True, prefer_ids=None)
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question)
        apply_slice_dims(bundle["feats"], bundle["metas"], question)
        bundle["qid"] = qid
        bundle["question"] = question
        bundle["l2"] = l2
        bundles.append(bundle)
    print("=== stage1 ===", flush=True)
    stage1 = evaluate(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K, names=names)
    missing = []
    gold_in_pool = 0
    per = []
    for b in bundles:
        order = stage1["ranked"][b["qid"]]
        inside = []
        for pid in b["l2"]:
            rank = _rank(order, pid)
            if rank is not None and rank <= POOL:
                gold_in_pool += 1
                inside.append(pid)
            else:
                why = "一筛去重后没有单独占一个名次" if rank is None else f"名次 {rank}，超出池 {POOL}"
                missing.append({"qid": b["qid"], "id": pid, "rank": rank, "why": why})
        per.append({"qid": b["qid"], "n_l2": len(b["l2"]), "gold_in_pool": len(inside), "order": order})
    print(f"  gold in pool {gold_in_pool}", flush=True)
    rows = pool_rows(bundles, stage1["ranked"], POOL)
    print("=== fit stage2 ===", flush=True)
    w, trace, ev = fit_r15(rows, names=R15_DIMS, laps=2, k=DEFAULT_K)
    print(f"  {ev['gold_kept']} gold / {ev['nongold_kept']} nongold", flush=True)
    by_bundle = {b["qid"]: b for b in bundles}
    questions = []
    for block in per:
        b = by_bundle[block["qid"]]
        group = [r for r in rows if r["qid"] == block["qid"]]
        chosen = cut_question(group, w, R15_DIMS, DEFAULT_K)
        final = [r["id"] for r in chosen]
        questions.append({
            "qid": block["qid"],
            "n_l2": block["n_l2"],
            "gold_in_pool": block["gold_in_pool"],
            "final": final,
            "n_final": len(final),
            "hits": [r["id"] for r in chosen if r["gold"]],
            "n_hits": sum(1 for r in chosen if r["gold"]),
            "nongold": [r["id"] for r in chosen if not r["gold"]],
        })
    report: dict[str, Any] = {
        "ticket": "R15-bigpool-refit-stage2",
        "defaults": {
            "pool": POOL,
            "k": DEFAULT_K,
            "stage1": "R14 coefficients",
            "prefer_ids": False,
            "refill_kicked": False,
        },
        "leak_any_bad": leak_any,
        "gold_in_pool": gold_in_pool,
        "missing": missing,
        "questions": questions,
        "sum_hits": sum(q["n_hits"] for q in questions),
        "sum_final": sum(q["n_final"] for q in questions),
        "sum_nongold": sum(len(q["nongold"]) for q in questions),
        "coeff_table": [(n, w.get(n, 0.0)) for n in R15_DIMS],
        "trace": trace,
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    report["reading"] = _reading(report)
    (OUT / "R15_bigpool_refit_stage2.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R15_bigpool_refit_stage2.md").write_text(_markdown(report), encoding="utf-8")
    print(report["reading"], flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
