#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R11：盒内在 R10 规则上再减标题党。不读金标 id。"""

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
    DOWNWEIGHT,
    TITLE_BAIT_PENALTY,
    inbox_rerank,
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
WATCH = ("doc_041#p6", "doc_009#p5", "doc_029#p7", "doc_033#p6")
MISSES = ("doc_009#p5", "doc_029#p7", "doc_033#p6")


def _fate(pid: str, out: dict[str, Any], stage1_rank: int | None) -> dict[str, Any]:
    order = {row["id"]: i for i, row in enumerate(out["order"], 1)}
    if pid in out["swallowed"]:
        where = "swallowed"
    elif pid in out["near_dup_dropped"]:
        where = "near_dup_replaced"
    elif pid in out["top_ids"]:
        where = "in_top7"
    elif pid in order:
        where = "kept_outside_top7"
    elif stage1_rank is None or stage1_rank > out["pool"]:
        where = "outside_pool"
    else:
        where = "absent"
    return {
        "id": pid,
        "stage1_rank": stage1_rank,
        "fate": where,
        "inbox_rank": order.get(pid),
        "title_bait": pid in out.get("title_bait", []),
        "replaced_by": out["rep_of"].get(pid) if where == "near_dup_replaced" else None,
    }


def _arm(bundle: dict[str, Any], ranked: list[tuple[str, float]], pool: int) -> dict[str, Any]:
    texts = {pid: str((bundle["metas"].get(pid) or {}).get("text") or "") for pid, _ in ranked[:pool]}
    out = inbox_rerank(
        ranked,
        texts=texts,
        feats=bundle["feats"],
        metas=bundle["metas"],
        pool=pool,
        k=DEFAULT_K,
        question=str(bundle.get("question") or ""),
    )
    l2 = list(bundle["l2"])
    l2set = set(l2)
    top = out["top_ids"]
    stage1 = {pid: i for i, (pid, _) in enumerate(ranked, 1)}
    return {
        "pool": pool,
        "top7": top,
        "hits": [g for g in l2 if g in top],
        "n7": sum(1 for g in l2 if g in top),
        "n_nongold": sum(1 for pid in top if pid not in l2set),
        "title_bait": [
            {
                "id": pid,
                "title": str((bundle["metas"].get(pid) or {}).get("title") or "")[:80],
                "stage1_rank": stage1.get(pid),
                "inbox_rank": next((i for i, row in enumerate(out["order"], 1) if row["id"] == pid), None),
                "in_top7": pid in top,
            }
            for pid in out.get("title_bait") or []
        ],
        "watch": [_fate(pid, out, stage1.get(pid)) for pid in WATCH],
        "gold_removed": [
            _fate(gid, out, stage1.get(gid))
            for gid in l2
            if gid in out["swallowed"] or gid in out["near_dup_dropped"]
        ],
    }


def _zh(fate: str) -> str:
    return {
        "outside_pool": "池外",
        "kept_outside_top7": "在池内、未进前7",
        "in_top7": "进前7",
        "swallowed": "拼段丢掉",
        "near_dup_replaced": "近同文让位",
        "absent": "不在名单",
    }.get(fate, fate or "—")


def _markdown(report: dict[str, Any]) -> str:
    r10 = {row["pool"]: row for row in report["r10_summary"]}
    lines = [
        "# R11 — 盒内标题党降权",
        "",
        "第一阶段仍是 R9 召回。第二阶段保留 R10：拼段才丢长文，近同文先留官方原文，综述／纯评论／没拆开的 commentary 降权。新增一档，不读金标 id。",
        "",
        "## 规则",
        "",
        "标题党：问句点到的主张词（如「没让我走／不愿走」，以及问句打开的框架词）出现在标题或正文里的「原标题」行；把这些行、与标题相同的回声、以及「阅读原文」剥掉之后，剩下的正文不含这些词，并且短于 48 字。这样的段固定减 **"
        f"{TITLE_BAIT_PENALTY}**。正文里真有主张词的不减，标题再怎么重复这句也不减。",
        "既有降权仍是：" + "、".join(f"`{k}` −{v}" for k, v in DOWNWEIGHT.items()) + "。",
        f"候选池 {', '.join(str(p) for p in POOLS)}，@7 仍截 7 条。expand {report['defaults']['expand_top_n']} / paraphrase {report['defaults']['n_paraphrase']}，因果关。",
        f"leak_any_bad：**{report['leak_any_bad']}**。墙钟 {report['wall_s']}s。",
        "",
        "## 相对 R10",
        "",
        "| 池 | R10 @7 | R11 @7 | 差 | R11 盒内非金标 | 标题党条数 |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["summary"]:
        base = r10[row["pool"]]["sum7"]
        lines.append(
            f"| {row['pool']} | {base} | {row['sum7']} | {row['sum7'] - base:+d} | {row['n_nongold']} | {row['n_bait']} |"
        )
    lines += ["", "分题 @7：", "", "| qid | 金标 | R10 池15 | R11 池7 | R11 池15 | R11 池20 |", "|---|---:|---:|---:|---:|---:|"]
    by_pool = {row["pool"]: {q["qid"]: q for q in row["questions"]} for row in report["by_pool"]}
    r10q = report["r10_by_qid_pool15"]
    meta = {m["qid"]: m for m in report["questions_meta"]}
    for qid in ("q_001", "q_002", "q_003"):
        cells = [str(by_pool[p][qid]["n7"]) for p in POOLS]
        lines.append(
            f"| {qid} | {meta[qid]['n_l2']} | {r10q[qid]} | " + " | ".join(cells) + " |"
        )
    lines += ["", "## doc_041#p6 与 doc_009#p5", ""]
    for pid in ("doc_041#p6", "doc_009#p5"):
        lines.append(f"### `{pid}`")
        lines.append("")
        lines.append("| 池 | R9 名次 | R11 命运 | 判成标题党 |")
        lines.append("|---:|---:|---|---|")
        for pool in POOLS:
            # 这两段都在 q_002 上比较。别题里的同名 id 名次不能盖掉。
            watch = by_pool[pool]["q_002"]["watch"]
            hit = next((w for w in watch if w["id"] == pid), None)
            if not hit or hit.get("stage1_rank") is None:
                lines.append(f"| {pool} | — | 不在 q_002 排序里 | — |")
                continue
            rank = f"盒内第 {hit['inbox_rank']}" if hit.get("inbox_rank") else ""
            lines.append(
                f"| {pool} | {hit['stage1_rank']} | {_zh(hit['fate'])} {rank} | {'是' if hit['title_bait'] else '否'} |"
            )
        lines.append("")
    lines += ["## 三条漏标", ""]
    lines.append("| id | 题 | R9 名次 | R10 池20 | R11 池15 | R11 池20 |")
    lines.append("|---|---|---:|---|---|---|")
    q_of = {"doc_009#p5": "q_002", "doc_029#p7": "q_002", "doc_033#p6": "q_003"}
    r10_focus = report["r10_focus_pool20"]
    for pid in MISSES:
        cells = []
        for pool in (15, 20):
            w = next(x for x in by_pool[pool][q_of[pid]]["watch"] if x["id"] == pid)
            extra = f" #{w['inbox_rank']}" if w.get("inbox_rank") else ""
            cells.append(_zh(w["fate"]) + extra)
        lines.append(
            f"| `{pid}` | {q_of[pid]} | {by_pool[20][q_of[pid]]['watch'][0] and next(x['stage1_rank'] for x in by_pool[20][q_of[pid]]['watch'] if x['id']==pid)} | {r10_focus.get(pid, '—')} | "
            + " | ".join(cells) + " |"
        )
    lines += ["", "## 被判成标题党的段（池 20）", ""]
    any_bait = False
    for qid in ("q_001", "q_002", "q_003"):
        baits = by_pool[20][qid]["title_bait"]
        if not baits:
            continue
        any_bait = True
        lines.append(f"### {qid}")
        lines.append("")
        for b in baits:
            where = "进了前 7" if b["in_top7"] else (f"盒内第 {b['inbox_rank']}" if b["inbox_rank"] else "被拼段或近同文拿掉")
            lines.append(f"- `{b['id']}` R9 第 {b['stage1_rank']}，{where}。{b['title']}")
        lines.append("")
    if not any_bait:
        lines.append("池 20 里没有。")
        lines.append("")
    if report["gold_hurt"]:
        lines += ["## 被规则换掉的严格金标", ""]
        for row in report["gold_hurt"]:
            lines.append(f"- 池 {row['pool']} {row['qid']} `{row['id']}`：{_zh(row['fate'])}")
        lines.append("")
    lines += ["## 读法", "", report["reading"], "", "## 路径", f"- `{OUT / 'R11_title_bait.json'}`", f"- `{OUT / 'R11_title_bait.md'}`", ""]
    return "\n".join(lines)


def _reading(report: dict[str, Any]) -> str:
    p20 = next(r for r in report["summary"] if r["pool"] == 20)
    r10 = next(r for r in report["r10_summary"] if r["pool"] == 20)
    q = next(q for q in next(r for r in report["by_pool"] if r["pool"] == 20)["questions"] if q["qid"] == "q_002")
    a041 = next(w for w in q["watch"] if w["id"] == "doc_041#p6")
    a009 = next(w for w in q["watch"] if w["id"] == "doc_009#p5")
    def _one(w: dict[str, Any]) -> str:
        if w["fate"] == "in_top7":
            return f"进了前 7（盒内第 {w['inbox_rank']}）"
        if w.get("inbox_rank"):
            return f"仍在前 7 外（盒内第 {w['inbox_rank']}）"
        return _zh(w["fate"])
    return (
        f"R10 池 20 的严格 @7 是 {r10['sum7']}，R11 是 {p20['sum7']}（{p20['sum7'] - r10['sum7']:+d}）。"
        f"`doc_041#p6` {'被判成标题党，' if a041['title_bait'] else ''}"
        f"{_one(a041)}。"
        f"`doc_009#p5` {'没有被判成标题党，' if not a009['title_bait'] else ''}"
        f"{_one(a009)}。"
        "减分只压壳段落；它和真引语之间如果还隔着别的正文，空出来的位子不会自动落到这条金标上。"
    )


def _r10_baseline() -> tuple[list[dict[str, Any]], dict[str, int], dict[str, str]]:
    doc = json.loads((OUT / "R10_inbox_rerank.json").read_text(encoding="utf-8"))
    summary = doc["summary"]
    pool15 = next(r for r in doc["by_pool"] if r["pool"] == 15)
    by_qid = {q["qid"]: q["n7"] for q in pool15["questions"]}
    focus = {}
    pool20 = next(r for r in doc["by_pool"] if r["pool"] == 20)
    labels = {
        "outside_pool": "池外",
        "kept_outside_top7": "在池内、未进前7",
        "in_top7": "进前7",
    }
    for q in pool20["questions"]:
        for f in q.get("focus") or []:
            if f["id"] in MISSES and f.get("stage1_rank") is not None:
                extra = f" #{f['inbox_rank']}" if f.get("inbox_rank") else ""
                focus[f["id"]] = labels.get(f["fate"], f["fate"]) + extra
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
            print(
                f"  pool {pool} {q['qid']} @7 {arm['n7']} bait {len(arm['title_bait'])}",
                flush=True,
            )
        by_pool.append({"pool": pool, "questions": qs, "sum7": sum(a["n7"] for a in qs)})
    summary = []
    for row in by_pool:
        summary.append({
            "pool": row["pool"],
            "sum7": row["sum7"],
            "n_nongold": sum(q["n_nongold"] for q in row["questions"]),
            "n_bait": sum(len(q["title_bait"]) for q in row["questions"]),
        })
    gold_hurt = []
    for row in by_pool:
        for q in row["questions"]:
            for g in q["gold_removed"]:
                gold_hurt.append({"pool": row["pool"], "qid": q["qid"], **g})
    r10_summary, r10_by_qid, r10_focus = _r10_baseline()
    report: dict[str, Any] = {
        "ticket": "R11-title-bait",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "causal_expand": False,
            "pools": list(POOLS),
            "k": DEFAULT_K,
            "title_bait_penalty": TITLE_BAIT_PENALTY,
            "downweight": DOWNWEIGHT,
            "stage2_uses_gold_ids": False,
        },
        "rule": (
            "主张词在标题或原标题行，剥掉原标题回声和阅读原文之后，"
            "正文不含这些词且短于 48 字，则减 0.08。正文里有主张词则不减。"
        ),
        "leak_any_bad": leak_any,
        "questions_meta": questions_meta,
        "r10_summary": r10_summary,
        "r10_by_qid_pool15": r10_by_qid,
        "r10_focus_pool20": r10_focus,
        "by_pool": by_pool,
        "summary": summary,
        "gold_hurt": gold_hurt,
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    report["reading"] = _reading(report)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R11_title_bait.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "R11_title_bait.md").write_text(_markdown(report), encoding="utf-8")
    print(report["reading"], flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
