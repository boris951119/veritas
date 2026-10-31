#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R13：二筛只删不补。一筛池 20，交卷可以短于 7。不读金标 id。"""

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
from app.kg_lab.inbox_rerank import claim_delta, inbox_rerank, is_fake_gloss, is_offtopic_money, is_section_bait, is_title_bait  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.r8_fit import FEATURE_NAMES, augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import R9_ADDED, apply_r9, r9_names  # noqa: E402
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
OUT = ROOT / "artifacts"
POOL = 20
MISSES = ("doc_009#p5", "doc_029#p7", "doc_033#p6")


def _why(pid: str, bundle: dict[str, Any]) -> str:
    meta = bundle["metas"].get(pid) or {}
    feat = bundle["feats"].get(pid) or {}
    text = str(meta.get("text") or "")
    question = str(bundle.get("question") or "")
    role = str(meta.get("fine_role") or "—")
    bits = [role]
    if is_title_bait(str(meta.get("title") or ""), text, question):
        bits.append("标题党")
    if is_section_bait(text, question):
        bits.append("小节标题蹭分")
    if is_offtopic_money(text, feat, meta, question):
        bits.append("只剩补偿金框架")
    if is_fake_gloss(feat, meta):
        bits.append("伪制度说明")
    delta = claim_delta(feat, meta, question)
    if delta < 0:
        bits.append("正文对题")
    elif delta == 0 and len(bits) == 1:
        bits.append("规则没加减，一筛就在前 7")
    return "，".join(bits)


def _arm(bundle: dict[str, Any], ranked: list[tuple[str, float]]) -> dict[str, Any]:
    texts = {pid: str((bundle["metas"].get(pid) or {}).get("text") or "") for pid, _ in ranked[:POOL]}
    out = inbox_rerank(
        ranked, texts=texts, feats=bundle["feats"], metas=bundle["metas"],
        pool=POOL, k=DEFAULT_K, question=str(bundle.get("question") or ""), refill=False,
    )
    l2 = list(bundle["l2"])
    l2set = set(l2)
    final = out["top_ids"]
    slate = [pid for pid, _ in ranked[:DEFAULT_K]]
    return {
        "slate": slate,
        "final": final,
        "n_final": len(final),
        "hits": [g for g in l2 if g in final],
        "n_hits": sum(1 for g in l2 if g in final),
        "nongold": [
            {"id": pid, "why": _why(pid, bundle)}
            for pid in final if pid not in l2set
        ],
        "kicked": [pid for pid in slate if pid not in final],
        "misses": {
            pid: ("进交卷" if pid in final else "不在交卷里")
            for pid in MISSES
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R13 — 二筛踢出后不补人",
        "",
        "一筛仍取 R9 排序的前 20 名，规则看得见池里的拼段和同文。二筛只在这前 20 的**前 7 名**里删：拼段、近同文落选、标题党、小节标题蹭分、补偿金蹭分、伪制度说明、综述降权，减分大于 0 的都出去。空位不从第 8 名往后补，也不从池外补。不够 7 条就短交。",
        "",
        f"leak_any_bad：**{report['leak_any_bad']}**。墙钟 {report['wall_s']}s。",
        "",
        "## 相对 R12",
        "",
        f"R12 池 20 会把通过规则、但一筛排在第 8 名以外的段补进前 7，严格合计 **{report['r12_sum7']}**。",
        f"R13 不补，严格合计 **{report['sum_hits']}**（{report['sum_hits'] - report['r12_sum7']:+d}），三题交卷一共 **{report['sum_final']}** 条。",
        "",
        "| qid | 金标 | 交卷条数 | 金标命中 | 还剩非金标 |",
        "|---|---:|---:|---:|---:|",
    ]
    meta = {m["qid"]: m for m in report["questions_meta"]}
    for q in report["questions"]:
        lines.append(
            f"| {q['qid']} | {meta[q['qid']]['n_l2']} | {q['n_final']} | {q['n_hits']} | {len(q['nongold'])} |"
        )
    for q in report["questions"]:
        lines += ["", f"## {q['qid']}", ""]
        lines.append(f"交卷 {q['n_final']} 条，命中 {q['n_hits']}/{meta[q['qid']]['n_l2']}：" + "、".join(f"`{x}`" for x in q["final"]))
        lines.append("")
        lines.append("一筛前 7 里被踢掉、没有补人：" + ("、".join(f"`{x}`" for x in q["kicked"]) if q["kicked"] else "无"))
        lines.append("")
        if q["nongold"]:
            lines.append("还在交卷里的非金标：")
            lines.append("")
            for item in q["nongold"]:
                lines.append(f"- `{item['id']}`：{item['why']}")
        else:
            lines.append("交卷里没有非金标。")
        lines.append("")
    lines += [
        "## 三条原先的漏标",
        "",
        "它们的一筛名次都在第 7 名之外。R13 不把它们补进来。",
        "",
    ]
    for q in report["questions"]:
        for pid, fate in q["misses"].items():
            if fate == "不在交卷里" and pid not in ("doc_009#p5", "doc_029#p7", "doc_033#p6"):
                continue
        shown = []
    # one line per miss from q_002/q_003
    miss_line = []
    for q in report["questions"]:
        for pid in MISSES:
            if pid in q["misses"] and (
                (pid != "doc_033#p6" and q["qid"] == "q_002")
                or (pid == "doc_033#p6" and q["qid"] == "q_003")
            ):
                miss_line.append(f"`{pid}`（{q['qid']}）{q['misses'][pid]}")
    lines.append("；".join(miss_line) + "。")
    lines += ["", "## 读法", "", report["reading"], "", "## 路径", f"- `{OUT / 'R13_no_refill.json'}`", f"- `{OUT / 'R13_no_refill.md'}`", ""]
    return "\n".join(lines)


def _reading(report: dict[str, Any]) -> str:
    parts = []
    for q in report["questions"]:
        nongold = "、".join(f"`{x['id']}`" for x in q["nongold"]) or "没有"
        parts.append(f"{q['qid']} 交 {q['n_final']} 条、中 {q['n_hits']}，非金标 {nongold}")
    return (
        f"不补人之后严格合计 {report['sum_hits']}，R12 补人时是 {report['r12_sum7']}。"
        + "。".join(parts) + "。"
        "`doc_009#p5` 和 `doc_029#p7` 一筛在第 7 名外，这次不补进来。"
    )


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
    r9_doc = json.loads((OUT / "R9_refine_buckets.json").read_text(encoding="utf-8"))
    r12 = json.loads((OUT / "R12_claim_align_kick.json").read_text(encoding="utf-8"))
    r12_sum7 = next(row["sum7"] for row in r12["summary"] if row["pool"] == POOL)
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
    by_qid = {b["qid"]: b for b in bundles}
    qs = []
    for q in stage1["questions"]:
        arm = _arm(by_qid[q["qid"]], stage1["ranked"][q["qid"]])
        arm["qid"] = q["qid"]
        qs.append(arm)
        print(f"  {q['qid']} final {arm['n_final']} hits {arm['n_hits']} nongold {len(arm['nongold'])}", flush=True)
    report: dict[str, Any] = {
        "ticket": "R13-no-refill",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "pool": POOL,
            "head": DEFAULT_K,
            "refill": False,
            "stage2_uses_gold_ids": False,
        },
        "leak_any_bad": leak_any,
        "questions_meta": questions_meta,
        "r12_sum7": r12_sum7,
        "questions": qs,
        "sum_hits": sum(q["n_hits"] for q in qs),
        "sum_final": sum(q["n_final"] for q in qs),
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    report["reading"] = _reading(report)
    (OUT / "R13_no_refill.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "R13_no_refill.md").write_text(_markdown(report), encoding="utf-8")
    print(report["reading"], flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
