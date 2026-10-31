#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R12：盒内再按问句主张、小节标题、伪制度说明、同文引语筛。不读金标 id。"""

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
from app.kg_lab.inbox_rerank import (  # noqa: E402
    FAKE_GLOSS_PENALTY,
    OFF_TOPIC_PENALTY,
    ON_TOPIC_BOOST,
    SECTION_BAIT_PENALTY,
    TITLE_BAIT_PENALTY,
    claim_delta,
    inbox_rerank,
    is_fake_gloss,
    is_offtopic_money,
    is_section_bait,
)
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.r8_fit import FEATURE_NAMES, augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import R9_ADDED, apply_r9, r9_names  # noqa: E402
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
OUT = ROOT / "artifacts"
POOLS = (7, 15, 20)
BLOCKERS = (
    "doc_029#p4", "doc_024#p1", "doc_035#p7", "doc_027#p4", "doc_033#p5",
    "doc_051#p5", "doc_012#p3", "doc_030#p9", "doc_029#p5",
)
MISSES = ("doc_009#p5", "doc_029#p7", "doc_033#p6")
WATCH = BLOCKERS + MISSES


def _zh(fate: str) -> str:
    return {
        "outside_pool": "池外",
        "kept_outside_top7": "在池内、未进前7",
        "in_top7": "进前7",
        "swallowed": "拼段丢掉",
        "near_dup_replaced": "近同文让位",
        "absent": "不在名单",
    }.get(fate, fate or "—")


def _why(pid: str, bundle: dict[str, Any], question: str) -> str:
    meta = bundle["metas"].get(pid) or {}
    feat = bundle["feats"].get(pid) or {}
    text = str(meta.get("text") or "")
    bits = []
    if is_section_bait(text, question):
        bits.append("小节标题蹭分")
    if is_offtopic_money(text, feat, meta, question):
        bits.append("只剩自主择业／补偿金")
    if is_fake_gloss(feat, meta):
        bits.append("伪制度说明")
    delta = claim_delta(feat, meta, question)
    if delta < 0 and not bits:
        bits.append("正文对题，抬权")
    if not bits:
        bits.append("这题上没加减")
    return "、".join(bits) + f"（{delta:+.2f}）"


def _fate(pid: str, out: dict[str, Any], stage1_rank: int | None, bundle: dict[str, Any]) -> dict[str, Any]:
    order = {row["id"]: i for i, row in enumerate(out["order"], 1)}
    if pid in out["swallowed"]:
        where = "swallowed"
    elif pid in out["near_dup_dropped"]:
        where = "near_dup_replaced"
    elif pid in out["top_ids"]:
        where = "in_top7"
    elif pid in order:
        where = "kept_outside_top7"
    elif stage1_rank is None or (stage1_rank > out["pool"]):
        where = "outside_pool"
    else:
        where = "absent"
    return {
        "id": pid,
        "stage1_rank": stage1_rank,
        "fate": where,
        "inbox_rank": order.get(pid),
        "replaced_by": out["rep_of"].get(pid) if where == "near_dup_replaced" else None,
        "why": _why(pid, bundle, str(bundle.get("question") or "")),
    }


def _arm(bundle: dict[str, Any], ranked: list[tuple[str, float]], pool: int) -> dict[str, Any]:
    texts = {pid: str((bundle["metas"].get(pid) or {}).get("text") or "") for pid, _ in ranked[:pool]}
    question = str(bundle.get("question") or "")
    out = inbox_rerank(
        ranked, texts=texts, feats=bundle["feats"], metas=bundle["metas"],
        pool=pool, k=DEFAULT_K, question=question,
    )
    l2 = list(bundle["l2"])
    l2set = set(l2)
    stage1 = {pid: i for i, (pid, _) in enumerate(ranked, 1)}
    top = out["top_ids"]
    return {
        "pool": pool,
        "top7": top,
        "submission": out["submission"],
        "hits": [g for g in l2 if g in top],
        "n7": sum(1 for g in l2 if g in top),
        "n_nongold": sum(1 for pid in top if pid not in l2set),
        "watch": [_fate(pid, out, stage1.get(pid), bundle) for pid in WATCH],
        "gold_removed": [
            _fate(gid, out, stage1.get(gid), bundle)
            for gid in l2
            if gid in out["swallowed"] or gid in out["near_dup_dropped"]
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    r11 = {row["pool"]: row["sum7"] for row in report["r11_summary"]}
    lines = [
        "# R12 — 盒内按问句主张把蹭分段踢下去",
        "",
        "第一阶段仍是 R9。第二阶段保留拼段、近同文、综述降权和标题党，再加四条，都不读金标 id。",
        "",
        "## 规则",
        "",
        f"- 正文命中本题主张词（不愿走／没让我走／未放行，或编制题上的编制／岗位／还在单位，或买断题上的补偿金）抬 **{ON_TOPIC_BOOST}**。小节标题里的词不算正文。",
        f"- 「不愿走」这题上，正文没有这些词、只剩自主择业／补偿金／组织安置的，降 **{OFF_TOPIC_PENALTY}**。`official_primary` 和通报转述不降，避免把官方办结通报一起踢掉。",
        f"- 主张只出现在「8月27日 …」这种小节标题、正文主体没有：降 **{SECTION_BAIT_PENALTY}**。",
        f"- 评论被标成 `institutional_gloss`，正文却没有「工作人员表示／也曾解释／通报」：再降 **{FAKE_GLOSS_PENALTY}**。",
        "- 两段正文都写着「没让我走」、共享原句不少于 12 字、篇幅相差不超过 1.85 倍：只留一条。转述当事人原话优先于对立框架，然后才是渠道和原分。长文里顺带引一句不并。",
        f"- 标题党仍是 −{TITLE_BAIT_PENALTY}。",
        f"池 {', '.join(str(p) for p in POOLS)}。expand {report['defaults']['expand_top_n']} / paraphrase {report['defaults']['n_paraphrase']}，因果关。",
        f"leak_any_bad：**{report['leak_any_bad']}**。墙钟 {report['wall_s']}s。",
        "",
        "## 相对 R11",
        "",
        "| 池 | R11 @7 | R12 @7 | 差 | R12 非金标 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in report["summary"]:
        base = r11[row["pool"]]
        lines.append(f"| {row['pool']} | {base} | {row['sum7']} | {row['sum7'] - base:+d} | {row['n_nongold']} |")
    lines += ["", "| qid | 金标 | R11 池20 | R12 池7 | R12 池15 | R12 池20 |", "|---|---:|---:|---:|---:|---:|"]
    by_pool = {row["pool"]: {q["qid"]: q for q in row["questions"]} for row in report["by_pool"]}
    meta = {m["qid"]: m for m in report["questions_meta"]}
    r11q = report["r11_by_qid_pool20"]
    for qid in ("q_001", "q_002", "q_003"):
        cells = [str(by_pool[p][qid]["n7"]) for p in POOLS]
        lines.append(f"| {qid} | {meta[qid]['n_l2']} | {r11q[qid]} | " + " | ".join(cells) + " |")
    q20 = by_pool[20]["q_002"]
    lines += ["", "## q_002 池 20：原先挡着 doc_009#p5 的 9 条", ""]
    lines.append("| R12 命运 | id | 原因 |")
    lines.append("|---|---|---|")
    watch = {w["id"]: w for w in q20["watch"]}
    for pid in BLOCKERS:
        w = watch[pid]
        tail = f"第 {w['inbox_rank']}" if w.get("inbox_rank") else ""
        if w.get("replaced_by"):
            tail = (tail + "，" if tail else "") + f"留下 `{w['replaced_by']}`"
        lines.append(f"| {_zh(w['fate'])} {tail} | `{pid}` | {w['why']} |")
    lines += ["", "## 三条漏标", ""]
    lines.append("| id | 题 | R11 池20 | R12 池15 | R12 池20 |")
    lines.append("|---|---|---|---|---|")
    q_of = {"doc_009#p5": "q_002", "doc_029#p7": "q_002", "doc_033#p6": "q_003"}
    r11_focus = report["r11_focus_pool20"]
    for pid in MISSES:
        cells = []
        for pool in (15, 20):
            w = next(x for x in by_pool[pool][q_of[pid]]["watch"] if x["id"] == pid)
            tail = f"第 {w['inbox_rank']}" if w.get("inbox_rank") else ""
            if w.get("replaced_by"):
                tail = (tail + "，" if tail else "") + f"留下 `{w['replaced_by']}`"
            cells.append(_zh(w["fate"]) + (" " + tail if tail else ""))
        lines.append(f"| `{pid}` | {q_of[pid]} | {r11_focus.get(pid, '—')} | " + " | ".join(cells) + " |")
    lines += ["", "池 20 的 @7：", ""]
    for qid in ("q_001", "q_002", "q_003"):
        q = by_pool[20][qid]
        lines.append(f"- {qid}（{q['n7']}/{meta[qid]['n_l2']}）：" + "、".join(f"`{x}`" for x in q["top7"]))
    if report["gold_hurt"]:
        lines += ["", "## 被并掉或拼掉的严格金标", ""]
        for row in report["gold_hurt"]:
            repl = f"，留下 `{row['replaced_by']}`" if row.get("replaced_by") else ""
            lines.append(f"- 池 {row['pool']} {row['qid']} `{row['id']}`：{_zh(row['fate'])}{repl}")
    lines += ["", "## 读法", "", report["reading"], "", "## 路径", f"- `{OUT / 'R12_claim_align_kick.json'}`", f"- `{OUT / 'R12_claim_align_kick.md'}`", ""]
    return "\n".join(lines)


def _reading(report: dict[str, Any]) -> str:
    p20 = next(r for r in report["summary"] if r["pool"] == 20)
    r11 = next(r for r in report["r11_summary"] if r["pool"] == 20)["sum7"]
    q = next(q for q in next(r for r in report["by_pool"] if r["pool"] == 20)["questions"] if q["qid"] == "q_002")
    w009 = next(w for w in q["watch"] if w["id"] == "doc_009#p5")
    w029 = next(w for w in q["watch"] if w["id"] == "doc_029#p7")
    q3 = next(q for q in next(r for r in report["by_pool"] if r["pool"] == 20)["questions"] if q["qid"] == "q_003")
    w033 = next(w for w in q3["watch"] if w["id"] == "doc_033#p6")

    def _one(w: dict[str, Any]) -> str:
        if w["fate"] == "in_top7":
            return f"进了前 7（第 {w['inbox_rank']}）"
        if w.get("inbox_rank"):
            return f"仍在前 7 外（第 {w['inbox_rank']}）"
        if w["fate"] == "near_dup_replaced":
            return f"近同文让给了 `{w['replaced_by']}`"
        return _zh(w["fate"])

    return (
        f"R11 池 20 严格 @7 是 {r11}，R12 是 {p20['sum7']}（{p20['sum7'] - r11:+d}）。"
        f"`doc_009#p5` {_one(w009)}。"
        f"`doc_029#p7` {_one(w029)}。"
        f"`doc_033#p6` {_one(w033)}。"
    )


def _r11_baseline() -> tuple[list[dict[str, Any]], dict[str, int], dict[str, str]]:
    doc = json.loads((OUT / "R11_title_bait.json").read_text(encoding="utf-8"))
    summary = [{"pool": row["pool"], "sum7": row["sum7"]} for row in doc["summary"]]
    pool20 = next(r for r in doc["by_pool"] if r["pool"] == 20)
    by_qid = {q["qid"]: q["n7"] for q in pool20["questions"]}
    labels = {"outside_pool": "池外", "kept_outside_top7": "在池内、未进前7", "in_top7": "进前7"}
    focus = {}
    q_of = {"doc_009#p5": "q_002", "doc_029#p7": "q_002", "doc_033#p6": "q_003"}
    by_q = {q["qid"]: q for q in pool20["questions"]}
    for pid, qid in q_of.items():
        for f in by_q[qid].get("watch") or []:
            if f["id"] == pid and f.get("stage1_rank") and f["stage1_rank"] <= 20:
                extra = f" 第 {f['inbox_rank']}" if f.get("inbox_rank") else ""
                focus[pid] = labels.get(f["fate"], f["fate"]) + extra
    return summary, by_qid, focus


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
    r9_doc = json.loads((OUT / "R9_refine_buckets.json").read_text(encoding="utf-8"))
    coeff = {k: float(v) for k, v in r9_doc["coeff"].items()}
    names = R9_ADDED + tuple(n for n in r9_names(FEATURE_NAMES) if n not in R9_ADDED)
    for name in names:
        coeff.setdefault(name, 0.0)
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
        bundle = build_bundle(sub_rows, fused, question, frames=True, prefer_ids=set(l2))
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question)
        bundle["qid"] = qid
        bundle["question"] = question
        bundle["l2"] = l2
        bundles.append(bundle)
        questions_meta.append({"qid": qid, "n_l2": len(l2), "question": question})
    stage1 = evaluate(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K, names=names)
    print(f"  replay {stage1['sum7']}/{stage1['sum15']}", flush=True)
    by_qid = {b["qid"]: b for b in bundles}
    by_pool = []
    for pool in POOLS:
        qs = []
        for q in stage1["questions"]:
            arm = _arm(by_qid[q["qid"]], stage1["ranked"][q["qid"]], pool)
            arm["qid"] = q["qid"]
            qs.append(arm)
            print(f"  pool {pool} {q['qid']} @7 {arm['n7']}", flush=True)
        by_pool.append({"pool": pool, "questions": qs, "sum7": sum(a["n7"] for a in qs)})
    summary = [{
        "pool": row["pool"],
        "sum7": row["sum7"],
        "n_nongold": sum(q["n_nongold"] for q in row["questions"]),
    } for row in by_pool]
    gold_hurt = []
    for row in by_pool:
        for q in row["questions"]:
            for g in q["gold_removed"]:
                gold_hurt.append({"pool": row["pool"], "qid": q["qid"], **g})
    r11_summary, r11_by_qid, r11_focus = _r11_baseline()
    report: dict[str, Any] = {
        "ticket": "R12-claim-align-kick",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "causal_expand": False,
            "pools": list(POOLS),
            "k": DEFAULT_K,
            "on_topic_boost": ON_TOPIC_BOOST,
            "off_topic_penalty": OFF_TOPIC_PENALTY,
            "section_bait_penalty": SECTION_BAIT_PENALTY,
            "fake_gloss_penalty": FAKE_GLOSS_PENALTY,
            "stage2_uses_gold_ids": False,
        },
        "leak_any_bad": leak_any,
        "questions_meta": questions_meta,
        "r11_summary": r11_summary,
        "r11_by_qid_pool20": r11_by_qid,
        "r11_focus_pool20": r11_focus,
        "by_pool": by_pool,
        "summary": summary,
        "gold_hurt": gold_hurt,
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    report["reading"] = _reading(report)
    (OUT / "R12_claim_align_kick.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "R12_claim_align_kick.md").write_text(_markdown(report), encoding="utf-8")
    print(report["reading"], flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
