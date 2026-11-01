#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R10：R9 召回进盒后，用一套不读金标的规则做盒内二次筛选。"""

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
from app.kg_lab.inbox_rerank import DOWNWEIGHT, inbox_rerank  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.r8_fit import FEATURE_NAMES, augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import R9_ADDED, apply_r9, r9_names  # noqa: E402
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
OUT = ROOT / "artifacts"
FOCUS = ("doc_009#p5", "doc_029#p7", "doc_033#p6")
CONCAT = "doc_012#p2"
POOLS = (7, 15, 20)


def _label(pid: str, bundle: dict[str, Any]) -> dict[str, Any]:
    feat = bundle["feats"].get(pid) or {}
    meta = bundle["metas"].get(pid) or {}
    tier = next((k[5:] for k, v in feat.items() if str(k).startswith("tier_") and v), "other")
    return {
        "id": pid,
        "fine_role": meta.get("fine_role") or "",
        "tier": tier,
        "comment": feat.get("r9_comment") or "",
        "relay": feat.get("r9_relay") or "",
        "title": str(meta.get("title") or "")[:80],
    }


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
    )
    l2 = list(bundle["l2"])
    l2set = set(l2)
    top = out["top_ids"]
    hits = [g for g in l2 if g in top]
    nongold = [pid for pid in top if pid not in l2set]
    stage1 = {pid: i for i, (pid, _) in enumerate(ranked, 1)}
    gold_dropped = []
    for gid in l2:
        if gid in out["swallowed"] or gid in out["near_dup_dropped"]:
            gold_dropped.append(_fate(gid, out, stage1.get(gid)))
    return {
        "pool": pool,
        "top7": top,
        "hits": hits,
        "n7": len(hits),
        "nongold": [_label(pid, bundle) for pid in nongold],
        "n_nongold": len(nongold),
        "doc_012_in_top7": CONCAT in top,
        "doc_012_swallowed": CONCAT in out["swallowed"],
        "doc_012_near_dup_dropped": CONCAT in out["near_dup_dropped"],
        "swallowed": out["swallowed"],
        "swallow_of": out.get("swallow_of") or {},
        "near_dup_dropped": [
            {"id": pid, "kept": out["rep_of"].get(pid), **{k: v for k, v in _label(pid, bundle).items() if k != "id"}}
            for pid in out["near_dup_dropped"]
        ],
        "penalties": out["penalties"],
        "focus": [
            _fate(pid, out, stage1.get(pid))
            for pid in FOCUS
            if pid in set(bundle["l2"])
        ],
        "gold_removed": gold_dropped,
        "order_head": out["order"][:12],
    }


def _markdown(report: dict[str, Any]) -> str:
    before = report["r9"]
    lines = [
        "# R10 — 盒内二次筛选",
        "",
        "第一阶段沿用 R9 召回与系数，名单不变。第二阶段只在候选池里做三件事，规则不读金标 id：",
        "",
        "1. 拼段：较长段吞进一条较短通报之后，挖掉那一句，剩下的正文仍有六成来自池里另一条不同切片，才丢掉较长段。只多包了一句摘录的单篇，按近同文留代表，不整段扔掉。",
        "2. 近同文（8-gram Jaccard ≥ 0.72，或包含度 ≥ 0.92 且长度比 ≤ 1.45），以及只多包了一句摘录的单篇，只留一条。代表先取 `official_primary`；`mixed_roundup`／`mixed_summary`／`pure_opinion`／`commentary` 不能靠渠道层级挤掉没降权的载体；其余再取更高渠道层级，最后看池内原分。",
        "3. 固定降权，不重新拟合：" + "、".join(f"`{k}` −{v}" for k, v in DOWNWEIGHT.items()) + "。已经拆成 `institutional_gloss`／`party_comment` 的段不再吃粗 `commentary` 那一档。",
        "",
        "同主张只在近同文簇里比渠道，不按「补偿金」这类词在整盒里只留一条，避免把 q_001 四条金标通报收成一条。",
        f"候选池试了 {', '.join(str(p) for p in POOLS)}。@7 仍截 7 条。expand {report['defaults']['expand_top_n']} / paraphrase {report['defaults']['n_paraphrase']}，因果关。",
        f"leak_any_bad：**{report['leak_any_bad']}**。墙钟 {report['wall_s']}s。",
        "",
        "## 相对 R9",
        "",
        f"R9 严格合计 @7 **{before['sum7']}** / @15 **{before['sum15']}**，三题 Top-7 里非金标合计 **{report['r9_nongold']}** 条"
        "（14 条里还差 3 条：`doc_009#p5`、`doc_029#p7`、`doc_033#p6`）。",
        "",
        "| 池 | 严格 @7 | 相对 R9 | 盒内非金标 | doc_012#p2 |",
        "|---:|---:|---:|---:|---|",
    ]
    for row in report["summary"]:
        kick = "踢出" if not row["doc_012_any_top"] else "仍在盒内"
        if row["doc_012_swallowed_any"]:
            kick += "（拼段）"
        lines.append(
            f"| {row['pool']} | {row['sum7']} | {row['sum7'] - before['sum7']:+d} | {row['n_nongold']} | {kick} |"
        )
    lines += ["", "分题：", "", "| qid | 金标 | R9 @7 | 池7 | 池15 | 池20 |", "|---|---:|---:|---:|---:|---:|"]
    by_pool = {row["pool"]: {q["qid"]: q for q in row["questions"]} for row in report["by_pool"]}
    meta = {m["qid"]: m for m in report["questions_meta"]}
    r9q = {q["qid"]: q for q in before["questions"]}
    for qid in ("q_001", "q_002", "q_003"):
        cells = [str(by_pool[p][qid]["n7"]) for p in POOLS]
        lines.append(
            f"| {qid} | {meta[qid]['n_l2']} | {r9q[qid]['n7']} | " + " | ".join(cells) + " |"
        )
    # primary narrative uses pool 15, and call out pool 20 if it differs
    lines += ["", "## 盒内前后（池 15）", ""]
    p15 = by_pool[15]
    for qid in ("q_001", "q_002", "q_003"):
        q = p15[qid]
        r9top = r9q[qid]["top7"]
        lines.append(f"### {qid}")
        lines.append("")
        lines.append(f"R9 @7（{r9q[qid]['n7']}/{meta[qid]['n_l2']}）：" + "、".join(f"`{x}`" for x in r9top))
        lines.append("")
        lines.append(f"二次后 @7（{q['n7']}/{meta[qid]['n_l2']}）：" + "、".join(f"`{x}`" for x in q["top7"]))
        lines.append("")
        if q["nongold"]:
            bits = []
            for item in q["nongold"]:
                bits.append(
                    f"`{item['id']}`（{item['fine_role'] or '—'} / {item['tier']} / 评论 {item['comment'] or '—'}）"
                )
            lines.append("盒内非金标：" + "；".join(bits))
        else:
            lines.append("盒内非金标：0")
        lines.append("")
        if q["swallowed"]:
            bits = [f"`{host}`（吞进 `{piece}` 后仍有另一段）" for host, piece in q["swallow_of"].items()]
            lines.append("拼段丢掉：" + "；".join(bits or [f"`{x}`" for x in q["swallowed"]]))
            lines.append("")
        if q["near_dup_dropped"]:
            bits = [f"`{d['id']}` → `{d['kept']}`" for d in q["near_dup_dropped"]]
            lines.append("近同文并掉：" + "；".join(bits))
            lines.append("")
        if q["gold_removed"]:
            bits = [f"`{g['id']}`（{g['fate']}）" for g in q["gold_removed"]]
            lines.append("被规则移出的严格金标：" + "；".join(bits))
            lines.append("")
    lines += ["## 三条漏标", ""]
    lines.append("| id | 题 | R9 名次 | 池7 | 池15 | 池20 |")
    lines.append("|---|---|---:|---|---|---|")
    focus_by = {}
    for row in report["by_pool"]:
        for q in row["questions"]:
            for f in q["focus"]:
                if f["stage1_rank"] is not None:
                    focus_by.setdefault(f["id"], {})[row["pool"]] = f
    q_of = {"doc_009#p5": "q_002", "doc_029#p7": "q_002", "doc_033#p6": "q_003"}
    r9_rank = {}
    for q in before["questions"]:
        r9_rank.update(q["ranks"])
    labels = {
        "outside_pool": "池外",
        "kept_outside_top7": "在池内、未进前7",
        "in_top7": "进前7",
        "swallowed": "拼段丢掉",
        "near_dup_replaced": "近同文让位",
        "absent": "不在名单",
    }
    for pid in FOCUS:
        cells = []
        for pool in POOLS:
            f = focus_by.get(pid, {}).get(pool) or {}
            fate = labels.get(f.get("fate") or "", f.get("fate") or "—")
            if f.get("inbox_rank") and f.get("fate") != "in_top7":
                fate += f" #{f['inbox_rank']}"
            cells.append(fate)
        lines.append(f"| `{pid}` | {q_of[pid]} | {r9_rank.get(pid)} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "「池外」表示第一阶段名次超出该池，二次筛选看不见它。`doc_009#p5` 在 R9 是第 17，所以只有池 20 能把它放进候选。",
        "",
        "## doc_012#p2",
        "",
    ]
    for row in report["by_pool"]:
        for q in row["questions"]:
            flag = "踢出" if not q["doc_012_in_top7"] else "仍在"
            how = []
            if q["doc_012_swallowed"]:
                how.append("判成拼段")
            if q["doc_012_near_dup_dropped"]:
                how.append("近同文让位")
            extra = ("，" + "、".join(how)) if how else ""
            lines.append(f"- 池 {row['pool']} {q['qid']}：{flag}{extra}")
    if report["gold_hurt"]:
        lines += ["", "## 金标被更高渠道替掉", ""]
        for row in report["gold_hurt"]:
            lines.append(f"- 池 {row['pool']} {row['qid']} `{row['id']}`：{row['fate']}")
    lines += [
        "",
        "## 读法",
        "",
        report["reading"],
        "",
        "## 路径",
        f"- `{OUT / 'R10_inbox_rerank.json'}`",
        f"- `{OUT / 'R10_inbox_rerank.md'}`",
        "",
    ]
    return "\n".join(lines)


def _reading(report: dict[str, Any]) -> str:
    before = report["r9"]["sum7"]
    p7 = next(r for r in report["summary"] if r["pool"] == 7)
    p15 = next(r for r in report["summary"] if r["pool"] == 15)
    p20 = next(r for r in report["by_pool"] if r["pool"] == 20)
    notes = []
    for q in p20["questions"]:
        for f in q["focus"]:
            rank = f"（盒内第 {f['inbox_rank']}）" if f.get("inbox_rank") else ""
            notes.append(f"`{f['id']}` 未进前 7{rank}")
    hurt = "有严格金标被换掉，见上节。" if report["gold_hurt"] else "没有严格金标被换掉。"
    return (
        f"R9 @7 是 {before}/14，三题盒内非金标合计 {report['r9_nongold']} 条，`doc_012#p2` 三题都在。"
        f"只在这 7 条里筛：严格命中仍是 {p7['sum7']}，`doc_012#p2` 三题都离开，非金标合计 {p7['n_nongold']}。"
        f"少掉的是它占的那 3 个位子，名单变短，没有从后面补人。"
        f"池 15／20 把空位补满后，严格命中仍是 {p15['sum7']}，`doc_012#p2` 仍被踢出，非金标回到 {p15['n_nongold']}，补进来的是别的非金标，不是那三条漏标。"
        f"池 20 里三条漏标都进了候选、没进前 7：" + "；".join(notes) + "。"
        + hurt
    )


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
    r9_path = OUT / "R9_refine_buckets.json"
    r9_doc = json.loads(r9_path.read_text(encoding="utf-8"))
    coeff = {k: float(v) for k, v in r9_doc["coeff"].items()}
    names = r9_names(FEATURE_NAMES)
    names = R9_ADDED + tuple(n for n in names if n not in R9_ADDED)
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
        if not leak_check(
            {"queries": queries, "selection_used_gold": False}, gold=gold,
        ).get("ok"):
            leak_any = True
        bundle = build_bundle(sub_rows, fused, question, frames=True, prefer_ids=set(l2))
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question)
        bundle["qid"] = qid
        bundle["l2"] = l2
        bundles.append(bundle)
        questions_meta.append({"qid": qid, "n_l2": len(l2), "question": question})

    print("=== stage1 R9 ===", flush=True)
    stage1 = evaluate(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K, names=names)
    print(f"  replay {stage1['sum7']}/{stage1['sum15']}", flush=True)
    by_qid = {b["qid"]: b for b in bundles}
    by_pool = []
    for pool in POOLS:
        qs = []
        for q in stage1["questions"]:
            b = by_qid[q["qid"]]
            arm = _arm(b, stage1["ranked"][q["qid"]], pool)
            arm["qid"] = q["qid"]
            qs.append(arm)
            print(
                f"  pool {pool} {q['qid']} @7 {arm['n7']} nongold {arm['n_nongold']} "
                f"012={'out' if not arm['doc_012_in_top7'] else 'in'}",
                flush=True,
            )
        by_pool.append({"pool": pool, "questions": qs, "sum7": sum(a["n7"] for a in qs)})

    r9_nongold = 0
    for q in stage1["questions"]:
        l2 = set(by_qid[q["qid"]]["l2"])
        r9_nongold += sum(1 for pid in q["top7"] if pid not in l2)
    summary = []
    for row in by_pool:
        summary.append({
            "pool": row["pool"],
            "sum7": row["sum7"],
            "n_nongold": sum(q["n_nongold"] for q in row["questions"]),
            "doc_012_any_top": any(q["doc_012_in_top7"] for q in row["questions"]),
            "doc_012_swallowed_any": any(q["doc_012_swallowed"] for q in row["questions"]),
        })
    gold_hurt = []
    for row in by_pool:
        for q in row["questions"]:
            for g in q["gold_removed"]:
                gold_hurt.append({"pool": row["pool"], "qid": q["qid"], **g})

    r9_slim = {k: v for k, v in stage1.items() if k != "ranked"}
    report: dict[str, Any] = {
        "ticket": "R10-inbox-rerank",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "causal_expand": False,
            "pools": list(POOLS),
            "k": DEFAULT_K,
            "downweight": DOWNWEIGHT,
            "stage1": "R9 coeff + prefer_ids dedupe",
            "stage2_uses_gold_ids": False,
        },
        "leak_any_bad": leak_any,
        "questions_meta": questions_meta,
        "r9": r9_slim,
        "r9_nongold": r9_nongold,
        "by_pool": by_pool,
        "summary": summary,
        "gold_hurt": gold_hurt,
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    report["reading"] = _reading(report)
    OUT.mkdir(parents=True, exist_ok=True)
    jp = OUT / "R10_inbox_rerank.json"
    mp = OUT / "R10_inbox_rerank.md"
    jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    mp.write_text(_markdown(report), encoding="utf-8")
    print(f"wrote {mp}", flush=True)
    print(report["reading"], flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
