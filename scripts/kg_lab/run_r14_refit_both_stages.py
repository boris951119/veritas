#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R14：补切片维后，一筛、二筛两套系数都重新拟合。线上不读金标 id。"""

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
from app.kg_lab.r8_fit import FEATURE_NAMES, augment_features, evaluate, fit_coefficients  # noqa: E402
from app.kg_lab.r9_buckets import R9_ADDED, apply_r9, r9_names  # noqa: E402
from app.kg_lab.r14_stages import (  # noqa: E402
    STAGE2_DIMS,
    STAGE2_GRID,
    apply_stage2,
    fit_stage2,
    stage2_features,
)
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slice_dims import SLICE_DIMS, apply_slice_dims  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
OUT = ROOT / "artifacts"
GRID = (-0.12, -0.08, -0.04, -0.02, 0.0, 0.02, 0.04, 0.08, 0.12)
FOCUS = ("doc_033#p6", "doc_009#p5", "doc_029#p7")


def _rank(order: list[tuple[str, float]], pid: str) -> int | None:
    for i, (p, _sc) in enumerate(order, 1):
        if p == pid:
            return i
    return None


def _markdown(report: dict[str, Any]) -> str:
    s1 = report["stage1"]
    lines = [
        "# R14 — 两套系数重新拟合",
        "",
        "线上规则不读金标 id：去重不再指定留哪一个 id，金标只出现在拟合的目标里。同一题既拿来拟合也拿来报告，没有留出题。",
        "",
        "## 新切片维",
        "",
        "- `identity_synonym`：问句在问编制／岗位／在编不在岗时，正文出现「不是公务员／不坐班／无行政级别／团委副书记」。问买断则这条为 0。",
        "- `resume_noise`：正文里有伤退、被绊倒、单脚跳或缔造历史。泛提奥运会不算。",
        "- `identity_resume`：上面两件写在同一段。",
        "",
        "一筛分数 = RRF + Σ 系数 × 特征。旧维和新切片维放在一起重搜，网格 ±0.12，不再沿用盒内那套固定加减分。",
        "二筛是另一套加权和，只看一筛前 7。分数 ≥ 0 留下，否则踢掉。空位不从第 8 名补。二筛特征是身份同义词、履历噪声、两者同段、对题、口径、标题党、小节标题、补偿金蹭分、伪制度说明，系数同样重搜，初值全 0。",
        f"leak_any_bad：**{report['leak_any_bad']}**。墙钟 {report['wall_s']}s。",
        "",
        "## 一筛",
        "",
        f"去重不保金标 id 时，用 R9 系数重放（含新维但新维权重为 0）：严格 @7 **{report['replay']['sum7']}** / @15 **{report['replay']['sum15']}**。",
        f"重拟合后 @7 **{s1['sum7']}** / @15 **{s1['sum15']}**，L2 = {s1['l2']}，非零 {report['n_nonzero_stage1']} 维。",
        "",
        "| 维 | 系数 |",
        "|---|---:|",
    ]
    for name, val in report["stage1_nonzero"]:
        lines.append(f"| `{name}` | {val} |")
    lines += ["", "关注段的一筛名次（重放 → 拟合）：", ""]
    for row in report["focus_stage1"]:
        flag = "，**进前 7**" if row["in7"] else ""
        lines.append(
            f"- `{row['id']}` {row['qid']}：{row['replay_rank']} → {row['fit_rank']}"
            f"，identity={row['identity']} resume={row['resume']} both={row['both']}{flag}"
        )
    lines += ["", "## 二筛", ""]
    lines.append(
        f"一筛前 7 里金标留下 **{report['stage2']['gold_kept']}**，非金标留下 **{report['stage2']['nongold_kept']}**，L2 = {report['stage2']['l2']}。"
    )
    lines += ["", "| 维 | 系数 |", "|---|---:|"]
    if report["stage2_nonzero"]:
        for name, val in report["stage2_nonzero"]:
            lines.append(f"| `{name}` | {val} |")
    else:
        lines.append("| （全零，前 7 里分不开） | 0 |")
    lines += ["", "| qid | 金标 | 交卷 | 命中 | 还剩非金标 |", "|---|---:|---:|---:|---|"]
    meta = {m["qid"]: m for m in report["questions_meta"]}
    for q in report["questions"]:
        nongold = "、".join(f"`{x}`" for x in q["nongold"]) or "无"
        lines.append(
            f"| {q['qid']} | {meta[q['qid']]['n_l2']} | {q['n_final']} | {q['n_hits']} | {nongold} |"
        )
    lines += ["", "交卷：", ""]
    for q in report["questions"]:
        lines.append(f"- {q['qid']}：" + "、".join(f"`{x}`" for x in q["final"]))
    lines += [
        "",
        "## 读法",
        "",
        report["reading"],
        "",
        "拟合轨迹（一筛）：",
        "",
    ]
    for step in report["stage1_trace"]:
        lines.append(f"- {step['step']}：@7={step['sum7']} @15={step['sum15']} L2={step['l2']}")
    lines += ["", "拟合轨迹（二筛）：", ""]
    for step in report["stage2_trace"]:
        lines.append(
            f"- {step['step']}：金标留下 {step['gold_kept']}，非金标留下 {step['nongold_kept']}，L2={step['l2']}"
        )
    lines += [
        "",
        "## 过拟合",
        "",
        report["overfit"],
        "",
        "## 路径",
        f"- `{OUT / 'R14_refit_both_stages.json'}`",
        f"- `{OUT / 'R14_refit_both_stages.md'}`",
        "",
    ]
    return "\n".join(lines)


def _reading(report: dict[str, Any]) -> str:
    focus = next(r for r in report["focus_stage1"] if r["id"] == "doc_033#p6")
    entered = "进了一筛前 7" if focus["in7"] else f"一筛仍在第 {focus['fit_rank']}，没进前 7"
    return (
        f"`doc_033#p6` 身份同义词={focus['identity']}，履历噪声={focus['resume']}，两者同段={focus['both']}，{entered}。"
        f"一筛严格 @7 {report['replay']['sum7']}→{report['stage1']['sum7']}，"
        f"@15 {report['replay']['sum15']}→{report['stage1']['sum15']}。"
        f"二筛在前 7 里留下金标 {report['stage2']['gold_kept']}、非金标 {report['stage2']['nongold_kept']}。"
    )


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
    r9_doc = json.loads((OUT / "R9_refine_buckets.json").read_text(encoding="utf-8"))
    names = R9_ADDED + tuple(n for n in r9_names(FEATURE_NAMES) if n not in R9_ADDED)
    names = names + tuple(n for n in SLICE_DIMS if n not in names)
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
    questions_meta = []
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
        # 线上去重不传金标 id
        bundle = build_bundle(sub_rows, fused, question, frames=True, prefer_ids=None)
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question)
        apply_slice_dims(bundle["feats"], bundle["metas"], question)
        bundle["qid"] = qid
        bundle["question"] = question
        bundle["l2"] = l2
        bundles.append(bundle)
        questions_meta.append({"qid": qid, "n_l2": len(l2), "question": question})

    init = {n: float(r9_doc["coeff"].get(n) or 0.0) for n in names}
    for n in SLICE_DIMS:
        init[n] = 0.0
    print("=== replay ===", flush=True)
    replay = evaluate(bundles, init, k7=DEFAULT_K, k15=WIDE_K, names=names)
    print(f"  {replay['sum7']}/{replay['sum15']}", flush=True)
    print("=== fit stage1 ===", flush=True)
    coeff, trace = fit_coefficients(
        bundles, k7=DEFAULT_K, k15=WIDE_K, init=init, laps=2, names=names, grid=GRID,
        protect_mean=True,
    )
    fitted = evaluate(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K, names=names)
    print(f"  {fitted['sum7']}/{fitted['sum15']} L2={fitted['l2']}", flush=True)

    focus = []
    by_q = {b["qid"]: b for b in bundles}
    for b in bundles:
        for pid in FOCUS:
            if pid not in b["l2"] and not (b["qid"] == "q_003" and pid == "doc_033#p6"):
                if pid not in b["l2"]:
                    continue
            if pid not in set(b["l2"]):
                continue
            feat = b["feats"].get(pid) or {}
            focus.append({
                "qid": b["qid"],
                "id": pid,
                "replay_rank": _rank(replay["ranked"][b["qid"]], pid),
                "fit_rank": _rank(fitted["ranked"][b["qid"]], pid),
                "in7": _rank(fitted["ranked"][b["qid"]], pid) is not None and _rank(fitted["ranked"][b["qid"]], pid) <= 7,
                "identity": feat.get("identity_synonym"),
                "resume": feat.get("resume_noise"),
                "both": feat.get("identity_resume"),
            })
    # q_003 的 033 一定写上，哪怕上面漏了
    if not any(r["id"] == "doc_033#p6" for r in focus):
        b = by_q["q_003"]
        feat = b["feats"].get("doc_033#p6") or {}
        focus.append({
            "qid": "q_003",
            "id": "doc_033#p6",
            "replay_rank": _rank(replay["ranked"]["q_003"], "doc_033#p6"),
            "fit_rank": _rank(fitted["ranked"]["q_003"], "doc_033#p6"),
            "in7": (_rank(fitted["ranked"]["q_003"], "doc_033#p6") or 99) <= 7,
            "identity": feat.get("identity_synonym"),
            "resume": feat.get("resume_noise"),
            "both": feat.get("identity_resume"),
        })

    print("=== fit stage2 ===", flush=True)
    w2, trace2, ev2 = fit_stage2(bundles, fitted["ranked"], k=DEFAULT_K, names=STAGE2_DIMS, grid=STAGE2_GRID, laps=2)
    print(f"  gold {ev2['gold_kept']} nongold {ev2['nongold_kept']}", flush=True)
    questions = []
    for b in bundles:
        arm = apply_stage2(b, fitted["ranked"][b["qid"]], w2, STAGE2_DIMS, k=DEFAULT_K)
        arm["qid"] = b["qid"]
        questions.append(arm)

    nonzero1 = [(n, coeff[n]) for n in names if abs(coeff.get(n) or 0) > 1e-12]
    nonzero2 = [(n, w2[n]) for n in STAGE2_DIMS if abs(w2.get(n) or 0) > 1e-12]
    p6 = next(r for r in focus if r["id"] == "doc_033#p6")
    overfit = (
        "两套系数都在这 3 题的严格金标上拟合，没有留出题。"
        f"一筛非零 {len(nonzero1)} 维，L2={fitted['l2']}；二筛非零 {len(nonzero2)} 维，L2={ev2['l2']}。"
        "金标 id 不进特征和去重。"
    )
    report: dict[str, Any] = {
        "ticket": "R14-refit-both-stages",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "prefer_ids": False,
            "grid": list(GRID),
            "stage2_keep": "score>=0",
            "refill": False,
        },
        "leak_any_bad": leak_any,
        "questions_meta": questions_meta,
        "replay": {k: replay[k] for k in ("sum7", "sum15", "l2")},
        "stage1": {k: fitted[k] for k in ("sum7", "sum15", "l2")},
        "stage1_questions": [
            {k: q[k] for k in ("qid", "n7", "n15", "top7", "ranks")}
            for q in fitted["questions"]
        ],
        "n_nonzero_stage1": len(nonzero1),
        "stage1_nonzero": nonzero1,
        "stage1_coeff": {n: coeff.get(n, 0.0) for n in names},
        "stage1_trace": trace,
        "focus_stage1": focus,
        "stage2": {k: ev2[k] for k in ("gold_kept", "nongold_kept", "l2")},
        "stage2_nonzero": nonzero2,
        "stage2_coeff": {n: w2.get(n, 0.0) for n in STAGE2_DIMS},
        "stage2_trace": trace2,
        "questions": questions,
        "overfit": overfit,
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    report["reading"] = _reading(report)
    (OUT / "R14_refit_both_stages.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "R14_refit_both_stages.md").write_text(_markdown(report), encoding="utf-8")
    print(report["reading"], flush=True)
    print(f"  033 rank {p6['replay_rank']} -> {p6['fit_rank']}", flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
