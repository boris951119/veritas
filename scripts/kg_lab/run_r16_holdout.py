#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R16：冻结 R12，在拓尔思另外 5 案上测 Top-4／5／7。不重拟合。"""

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
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.inbox_rerank import inbox_rerank  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.r8_fit import FEATURE_NAMES, augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import R9_ADDED, apply_r9, r9_names  # noqa: E402
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import ingest_case_slices, union_pack_ids  # noqa: E402
from app.kg_lab.summarize import summarize_paras  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SAMPLES = Path("/Users/liuboyu/Desktop/veritas-testcases/样例集-拓尔思-20261012")
OUT = ROOT / "artifacts"
KS = (4, 5, 7)
# 拟合案单独对照，不进 holdout 合计
TRAIN_MARK = "刘翔"
HOLDOUT = (
    ("jilong", "吉隆"),
    ("us_cn_ai", "中美AI"),
    ("ai171", "印度航空"),
    ("kh_th", "柬泰"),
    ("wanghong", "王虹"),
)


def _case(mark: str) -> Path:
    hits = [
        p for p in SAMPLES.iterdir()
        if p.is_dir() and mark in p.name and (p / "raw_documents.json").is_file()
    ]
    if len(hits) != 1:
        raise SystemExit(f"case {mark}: {hits}")
    return hits[0]


def _rank_of(order: list[str], pid: str) -> int | None:
    try:
        return order.index(pid) + 1
    except ValueError:
        return None


def _eval_case(slug: str, case: Path, coeff: dict[str, float], names: tuple[str, ...], *, summarize: bool) -> dict[str, Any]:
    t0 = time.perf_counter()
    print(f"=== {slug} {case.name} ===", flush=True)
    dossier, union, questions = union_pack_ids(case)
    print(f"  union {len(union)} questions {len(questions)}", flush=True)
    ingest_case_slices(case, only_para_ids=union, case_slug=slug)
    sum_meta = {"skipped": True}
    if summarize:
        print("  summarize …", flush=True)
        sum_meta = summarize_paras(dossier, case_slug=slug, para_ids=union, workers=2)
        print(f"  summarize {sum_meta}", flush=True)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    emb = index.ensure_embeddings(force=False)
    print(f"  embed {emb}", flush=True)
    bundles = []
    leak_notes = []
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, skipped = gold_paras_for_question(case, qid)
        from app.kg_lab.slices import pack_selected_for_question
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for _d, p in gold if p in universe)
        missed_pack = sorted(p for _d, p in gold if p not in universe)
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(slug, sub_rows)
        sub.embeddings = {pid: v for pid, v in index.embeddings.items() if pid in universe}
        fused, queries, _pm, _n = _fuse_rrf(sub, question)
        bundle = build_bundle(sub_rows, fused, question, frames=True, prefer_ids=set(l2))
        url_of = {
            str(d.get("doc_id")): str(d.get("content_url") or "")
            for d in json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
        }
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question)
        bundle["qid"] = qid
        bundle["question"] = question
        bundle["l2"] = l2
        bundle["missed_pack"] = missed_pack
        bundle["gold_skipped_locator"] = skipped
        bundles.append(bundle)
        del queries
    stage1 = evaluate(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K, names=names)
    q_out = []
    blocked = []
    for b in bundles:
        ranked = stage1["ranked"][b["qid"]]
        stage1_pos = {pid: i for i, (pid, _) in enumerate(ranked, 1)}
        texts = {pid: str((b["metas"].get(pid) or {}).get("text") or "") for pid, _ in ranked[:20]}
        out = inbox_rerank(
            ranked, texts=texts, feats=b["feats"], metas=b["metas"],
            pool=20, k=20, question=b["question"], refill=True,
        )
        order = [row["id"] for row in out["order"]]
        l2set = set(b["l2"])
        cuts = {}
        for k in KS:
            top = order[:k]
            hits = [g for g in b["l2"] if g in top]
            nongold = [p for p in top if p not in l2set]
            cuts[str(k)] = {
                "hits": len(hits),
                "gold_total": len(b["l2"]),
                "nongold": len(nongold),
                "hit_ids": hits,
                "nongold_ids": nongold,
            }
        absent = []
        for g in b["l2"]:
            ir = _rank_of(order, g)
            if ir is None:
                why = "二筛后不在名单"
                if g in out["swallowed"]:
                    why = "判成拼段丢掉"
                elif g in out["near_dup_dropped"]:
                    why = f"近同文让位给 {out['rep_of'].get(g)}"
                elif stage1_pos.get(g, 10**9) > 20:
                    why = f"一筛第 {stage1_pos.get(g)}，池 20 外"
                absent.append({
                    "id": g, "why": why,
                    "stage1_rank": stage1_pos.get(g),
                    "inbox_rank": ir,
                })
            elif ir > 7:
                absent.append({
                    "id": g, "why": f"二筛名次 {ir}，Top-7 外",
                    "stage1_rank": stage1_pos.get(g),
                    "inbox_rank": ir,
                })
        for g in b["missed_pack"]:
            blocked.append({"qid": b["qid"], "id": g, "why": "装箱未选入，进不了召回宇宙"})
        q_out.append({
            "qid": b["qid"],
            "question": b["question"],
            "n_l2": len(b["l2"]),
            "n_pack_miss": len(b["missed_pack"]),
            "cuts": cuts,
            "outside_top7": absent,
        })
        print(
            f"  {b['qid']} @4 {cuts['4']['hits']}/{cuts['4']['gold_total']} "
            f"@5 {cuts['5']['hits']} @7 {cuts['7']['hits']} nongold7 {cuts['7']['nongold']}",
            flush=True,
        )
    return {
        "slug": slug,
        "name": case.name,
        "n_union": len(union),
        "summarize": {k: sum_meta.get(k) for k in ("n_new", "n_cached_skip", "n_errors", "wall_s", "skipped") if k in sum_meta or True},
        "embed": {"n_new": emb.get("n_new"), "wall_s": emb.get("wall_s")},
        "questions": q_out,
        "blocked_pack": blocked,
        "wall_s": round(time.perf_counter() - t0, 1),
    }


def _sum_cuts(cases: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out = {}
    for k in KS:
        hits = nongold = gold = 0
        for c in cases:
            for q in c["questions"]:
                cell = q["cuts"][str(k)]
                hits += cell["hits"]
                nongold += cell["nongold"]
                gold += cell["gold_total"]
        out[str(k)] = {"hits": hits, "gold_total": gold, "nongold": nongold}
    return out


def _recommend(hold: dict[str, dict[str, int]]) -> str:
    rows = []
    for k, cell in hold.items():
        gold = cell["gold_total"] or 1
        denom = cell["hits"] + cell["nongold"] or 1
        recall = cell["hits"] / gold
        share = cell["nongold"] / denom
        rows.append((k, recall, share, cell))
    # 召回优先，其次非金标占比更低
    best = max(rows, key=lambda r: (r[1], -r[2], -int(r[0])))
    bits = []
    for k, recall, share, cell in rows:
        bits.append(
            f"Top-{k} 金标 {cell['hits']}/{cell['gold_total']}（{recall:.0%}），非金标 {cell['nongold']} 条（占交卷 {share:.0%}）"
        )
    return (
        f"默认推荐 Top-{best[0]}。"
        + "；".join(bits)
        + "。Top-4 非金标最少但金标也少；Top-7 金标最多、非金标涨得更快。取推荐档是召回和非金标占比折中。"
    )


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R16 — 冻结 R12，五案 holdout",
        "",
        "一筛系数与二筛规则都是刘翔案上已经拟合好的 R12，没有在新案上重搜。",
        "严格金标＝supporting_facts（含 partial_support），段落 id 来自 evidence_samples。",
        f"expand {DEFAULT_EXPAND_TOP_N} / paraphrase {DEFAULT_PARAPHRASE_N}。池 20，交卷带 rank，再截 4／5／7。",
        f"墙钟 {report['wall_s']}s。",
        "",
        "## holdout 合计",
        "",
        "| k | 金标命中 | 金标总数 | 非金标 |",
        "|---:|---:|---:|---:|",
    ]
    for k, cell in report["holdout"].items():
        lines.append(f"| {k} | {cell['hits']} | {cell['gold_total']} | {cell['nongold']} |")
    lines += ["", report["recommend"], ""]
    if report.get("train"):
        t = report["train"]
        lines.append("训练案对照（不计入上表）：" + t["name"])
        lines.append("")
        lines.append("| k | 金标命中 | 金标总数 | 非金标 |")
        lines.append("|---:|---:|---:|---:|")
        for k, cell in t["cuts"].items():
            lines.append(f"| {k} | {cell['hits']} | {cell['gold_total']} | {cell['nongold']} |")
        lines.append("")
    for c in report["holdout_cases"]:
        lines += [f"## {c['name']}", ""]
        lines.append(
            f"装箱并集 {c['n_union']} 段。摘要新写 {c['summarize'].get('n_new')}，"
            f"缓存跳过 {c['summarize'].get('n_cached_skip')}，错误 {c['summarize'].get('n_errors')}，"
            f"摘要 {c['summarize'].get('wall_s')}s，嵌入新向量 {c['embed'].get('n_new')}，"
            f"嵌入 {c['embed'].get('wall_s')}s，全案 {c['wall_s']}s。"
        )
        lines.append("")
        lines.append("| 题 | 金标 | @4 | @5 | @7 | @7 非金标 |")
        lines.append("|---|---:|---|---|---|---:|")
        for q in c["questions"]:
            cells = []
            for k in KS:
                cell = q["cuts"][str(k)]
                cells.append(f"{cell['hits']}/{cell['gold_total']}")
            lines.append(
                f"| {q['qid']} | {q['n_l2']} | {cells[0]} | {cells[1]} | {cells[2]} | {q['cuts']['7']['nongold']} |"
            )
        bad = list(c["blocked_pack"])
        for q in c["questions"]:
            for row in q["outside_top7"]:
                bad.append({"qid": q["qid"], **row})
        if bad:
            lines.append("")
            lines.append("未进 Top-7 或进不了池：")
            for row in bad:
                lines.append(f"- {row['qid']} `{row['id']}`：{row['why']}")
        lines.append("")
    lines += ["## 路径", f"- `{OUT / 'R16_holdout_topk.json'}`", f"- `{OUT / 'R16_holdout_topk.md'}`", ""]
    return "\n".join(lines)


def _case_cuts(case: dict[str, Any]) -> dict[str, dict[str, int]]:
    return _sum_cuts([case])


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
    r9 = json.loads((OUT / "R9_refine_buckets.json").read_text(encoding="utf-8"))
    names = R9_ADDED + tuple(n for n in r9_names(FEATURE_NAMES) if n not in R9_ADDED)
    coeff = {n: float(r9["coeff"].get(n) or 0.0) for n in names}
    for n in names:
        coeff.setdefault(n, 0.0)

    # 先跑训练案，核对和已知 R12 截断一致，再跑 holdout
    train_case = _eval_case("liuxiang", _case(TRAIN_MARK), coeff, names, summarize=False)
    train_cuts = _case_cuts(train_case)
    print("TRAIN", train_cuts, flush=True)

    hold_cases = []
    for slug, mark in HOLDOUT:
        hold_cases.append(_eval_case(slug, _case(mark), coeff, names, summarize=True))
        partial = {
            "holdout_cases": hold_cases,
            "holdout": _sum_cuts(hold_cases),
        }
        (OUT / "R16_holdout_topk.partial.json").write_text(
            json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print("partial", partial["holdout"], flush=True)

    hold = _sum_cuts(hold_cases)
    report = {
        "ticket": "R16-holdout-topk",
        "frozen": "R12 stage1=R9 coeff; stage2=inbox rules; prefer_ids as in R12; no refit",
        "wall_s": round(time.perf_counter() - t0, 1),
        "train": {"name": train_case["name"], "cuts": train_cuts, "role": "训练案"},
        "holdout_cases": hold_cases,
        "holdout": hold,
        "recommend": _recommend(hold),
    }
    (OUT / "R16_holdout_topk.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "R16_holdout_topk.md").write_text(_markdown(report), encoding="utf-8")
    print(report["recommend"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
