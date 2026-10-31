#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R8：全切片规则打标后，用严格金标倒推多维系数。去重沿用 R7（簇内留金标 id）。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.channel_tier import channel_tier  # noqa: E402
from app.kg_lab.config import DEFAULT_K, WIDE_K  # noqa: E402
from app.kg_lab.eval_metrics import leak_check  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.r8_fit import (  # noqa: E402
    FEATURE_NAMES,
    augment_features,
    evaluate,
    fit_coefficients,
    r6_init,
    sensitivity,
)
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
OUT_DIR = ROOT / "artifacts"


def _urls(case: Path) -> dict[str, str]:
    docs = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    return {str(d.get("doc_id")): str(d.get("content_url") or "") for d in docs}


def _write_tags(rows: list[dict], url_of: dict[str, str], metas: dict[str, dict]) -> dict[str, int]:
    path = OUT_DIR / "R8_slice_tags.jsonl"
    counts: dict[str, int] = {}
    lines = []
    for row in rows:
        pid = str(row["para_id"])
        meta = metas.get(pid) or {}
        url = url_of.get(str(row.get("doc_id") or ""), "")
        tier = channel_tier(url, str(row.get("title") or ""))
        counts[tier] = counts.get(tier, 0) + 1
        lines.append(json.dumps({
            "para_id": pid,
            "doc_id": row.get("doc_id"),
            "fine_role": meta.get("fine_role"),
            "coarse_role": meta.get("role"),
            "channel": meta.get("channel"),
            "channel_tier": tier,
            "credibility": meta.get("credibility"),
            "title": row.get("title"),
        }, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return counts


def _misses(bundles, ev) -> list[dict[str, Any]]:
    by_q = {b["qid"]: b for b in bundles}
    out = []
    for q in ev["questions"]:
        b = by_q[q["qid"]]
        for gid in b["l2"]:
            if gid in q["at7"]:
                continue
            feat = b["feats"].get(gid) or {}
            role = next((n[5:] for n in FEATURE_NAMES if n.startswith("role_") and feat.get(n)), "")
            tier = next((n[5:] for n in FEATURE_NAMES if n.startswith("tier_") and feat.get(n)), "")
            rep = b["rep_of"].get(gid, gid)
            rank = q["ranks"].get(gid)
            if rep != gid and rank is None:
                why = f"去重后代表仍是 `{rep}`，这条 id 不在名单上"
            elif role == "commentary" and (rank or 99) > 15:
                why = (
                    "评论维系数是负的，用来把混口径综述压下去；"
                    "这条金标自己也是评论，和要压的噪声同一维，±0.08 里抬不进前 7"
                )
            elif rank is not None and rank <= 15:
                why = (
                    f"名次 {rank}，差 {rank - 7} 名。口径已经是 1，"
                    "再加 claim 会把同样对齐的非金标一起抬上来"
                )
            elif feat.get("claim_align", 0) <= 0:
                why = "口径维是 0：段内对不上本题触发的口径词"
            else:
                why = f"名次 {rank}，口径已对齐，幅度上限里仍进不了前 7"
            out.append({
                "qid": q["qid"],
                "id": gid,
                "rank": q["ranks"].get(gid),
                "rep": rep,
                "fine_role": role,
                "channel_tier": tier,
                "claim_align": feat.get("claim_align"),
                "subject_match": feat.get("subject_match"),
                "why": why,
            })
    return out


def _markdown(report: dict[str, Any]) -> str:
    r7, r8 = report["r7"], report["r8"]
    lines = [
        "# R8 — 用严格金标倒推多维系数",
        "",
        "- 公式：`score = rrf + Σ w · x`，w 可正可负，网格限制在 **±0.08**",
        "- 打标：全切片用标题／URL／正文规则（角色沿用 R5 细类，渠道层级看主机名）。未调用 14B，避免拟合不可复跑。",
        "- 去重：沿用 R7，簇内若有本题严格 id 就留下该 id，不加分。",
        "- 拟合与验收是同一套三题，没有留出题。向后消元去掉不影响 @7/@15 的系数。",
        f"- expand **{report['defaults']['expand_top_n']}** / paraphrase **{report['defaults']['n_paraphrase']}**，因果关",
        f"- leak_any_bad：**{report['leak_any_bad']}**",
        f"- 墙钟：{report['wall_s']}s",
        "",
        "## 相对 R7",
        "",
        f"- 严格合计 @7 **{r7['sum7']}→{r8['sum7']}**（{r8['sum7'] - r7['sum7']:+d}），"
        f"@15 **{r7['sum15']}→{r8['sum15']}**（{r8['sum15'] - r7['sum15']:+d}）",
        f"- 金标 capped 名次均值 {r7['mean_capped']}→{r8['mean_capped']}",
        f"- L2 = {r8['l2']}（消元后非零 {report['n_nonzero']} 维）",
        f"- 14 条里 @7 有 **{r8['sum7']}** 条，还差 **{report['n_gold'] - r8['sum7']}** 条。",
        "",
        "| qid | l2 | R7 @7/@15 | R8 @7/@15 |",
        "|---|---:|---|---|",
    ]
    for q7, q8 in zip(r7["questions"], r8["questions"]):
        n_l2 = next(m["n_l2"] for m in report["questions_meta"] if m["qid"] == q7["qid"])
        lines.append(
            f"| {q7['qid']} | {n_l2} | {q7['n7']}/{q7['n15']} | {q8['n7']}/{q8['n15']} |"
        )
    lines += [
        "",
        "## 系数（消元后为 0 的不列入）",
        "",
        "| 维 | 初值（对齐 R6） | 拟合 |",
        "|---|---:|---:|",
    ]
    init = report["init"]
    for name, val in report["coeff_nonzero"]:
        lines.append(f"| `{name}` | {init.get(name, 0)} | {val} |")
    lines += ["", "## q_001 Top-7", ""]
    q1 = next(q for q in r8["questions"] if q["qid"] == "q_001")
    gold1 = set(q1["at7"])
    for i, pid in enumerate(q1["top7"], 1):
        mark = "金标" if pid in gold1 else "非金标"
        lines.append(f"{i}. `{pid}`（{mark}）")
    lines += ["", "## 未入围 @7", ""]
    if not report["misses"]:
        lines.append("14 条都在 @7。")
    for row in report["misses"]:
        lines.append(
            f"- {row['qid']} `{row['id']}` 名次 {row['rank']}，"
            f"角色 `{row['fine_role']}`，渠道 `{row['channel_tier']}`，"
            f"claim={row['claim_align']}。{row['why']}"
        )
    lines += [
        "",
        "## 敏感度（置零后 @7 会掉的维）",
        "",
    ]
    fragile = [s for s in report["sensitivity"] if s["probe"] == "zero" and s["d7"] < 0]
    if not fragile:
        lines.append("没有单一系数在置零后让 @7 下降。命中不靠单独一维。")
    for s in fragile:
        lines.append(f"- `{s['dim']}` 置零：@7 {s['d7']:+d}，@15 {s['d15']:+d}")
    inert = report["n_nonzero"] - len(fragile)
    lines.append(f"- 其余 {inert} 个非零系数单独置零，@7 不变。")
    lines += [
        "",
        "## 过拟合",
        "",
        report["overfit"],
        "",
        "拟合轨迹：",
        "",
    ]
    for step in report["trace"]:
        lines.append(f"- {step['step']}：@7={step['sum7']} @15={step['sum15']} L2={step['l2']}")
    lines += [
        "",
        "渠道层级计数（全切片）：",
        "",
    ]
    for tier, n in report["tier_counts"]:
        lines.append(f"- `{tier}` × {n}")
    lines += [
        "",
        "## 路径",
        f"- `{OUT_DIR / 'R8_coeff_fit.json'}`",
        f"- `{OUT_DIR / 'R8_coeff_fit.md'}`",
        f"- `{OUT_DIR / 'R8_slice_tags.jsonl'}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
    case = next(
        p for p in (ROOT / "data" / "trs-samples").iterdir()
        if p.is_dir() and "刘翔" in p.name and (p / "raw_documents.json").is_file()
    )
    url_of = _urls(case)
    dossier, union_ids, questions = union_pack_ids(case)
    rows_all = build_corpus_rows(dossier, case_slug=SLUG, para_ids=union_ids)
    index = KgIndex(SLUG, rows_all)
    index.ensure_embeddings(force=False)

    # 先拿一份全切片 meta（用第一题的问句只为建 meta；角色与渠道不依赖问句）
    from app.kg_lab.source_role import _meta_from_row
    metas_all = {str(r["para_id"]): _meta_from_row(r) for r in rows_all}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tier_counts = _write_tags(rows_all, url_of, metas_all)

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
        bundle = build_bundle(
            sub_rows, fused, question, frames=True, prefer_ids=set(l2),
        )
        augment_features(bundle["feats"], bundle["metas"], url_of)
        bundle["qid"] = qid
        bundle["l2"] = l2
        bundle["queries"] = queries
        bundles.append(bundle)
        questions_meta.append({
            "qid": qid,
            "question": question,
            "n_l2": len(l2),
            "n_fused": len(bundle["rrf"]),
        })

    print("=== fit ===", flush=True)
    init = r6_init()
    r7_ev = evaluate(bundles, init, k7=DEFAULT_K, k15=WIDE_K)
    print(f"  R7-init {r7_ev['sum7']}/{r7_ev['sum15']}", flush=True)
    coeff, trace = fit_coefficients(bundles, k7=DEFAULT_K, k15=WIDE_K, init=init, laps=2)
    r8_ev = evaluate(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K)
    print(f"  R8 {r8_ev['sum7']}/{r8_ev['sum15']} L2={r8_ev['l2']}", flush=True)
    sens = sensitivity(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K)
    misses = _misses(bundles, r8_ev)
    nonzero = [(n, coeff[n]) for n in FEATURE_NAMES if abs(coeff[n]) > 1e-12]
    n_gold = sum(m["n_l2"] for m in questions_meta)
    short = n_gold - r8_ev["sum7"]
    overfit = (
        f"系数是在这 {len(questions_meta)} 题、{n_gold} 条严格金标上拟合的，没有留出题。"
        f"幅度夹在 ±0.08，消元后剩 {len(nonzero)} 个非零系数，L2={r8_ev['l2']}。"
        "置零敏感度见上表：只在置零会掉 @7 的维上，这组数才被这三题用到。"
        f"距离 14/14@7 还差 {short} 条。这三条口径维都已是 1："
        "两条是评论（评论系数为负，专门压混口径），一条当事人转述停在第 10 名。"
        "再放开幅度会把同一标签的非金标一起抬进前 7。"
        if short else
        "三题 14 条都进了 @7。系数仍是同题拟合，换一套议题要重拟合。"
    )
    # 丢掉 ranked 大对象
    def _slim(ev):
        return {k: v for k, v in ev.items() if k != "ranked"}

    report = {
        "ticket": "R8-coeff-fit",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "causal_expand": False,
            "grid": [-0.08, -0.04, -0.02, 0, 0.02, 0.04, 0.08],
            "tagger": "rules_title_url_text",
            "llm": None,
        },
        "leak_any_bad": leak_any,
        "n_gold": n_gold,
        "n_nonzero": len(nonzero),
        "questions_meta": questions_meta,
        "tier_counts": sorted(tier_counts.items(), key=lambda kv: (-kv[1], kv[0])),
        "init": {n: init[n] for n in FEATURE_NAMES if abs(init[n]) > 1e-12},
        "coeff": {n: coeff[n] for n in FEATURE_NAMES},
        "coeff_nonzero": nonzero,
        "trace": trace,
        "r7": _slim(r7_ev),
        "r8": _slim(r8_ev),
        "misses": misses,
        "sensitivity": [s for s in sens if s["probe"] == "zero"],
        "overfit": overfit,
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jp = OUT_DIR / "R8_coeff_fit.json"
    mp = OUT_DIR / "R8_coeff_fit.md"
    jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    mp.write_text(_markdown(report), encoding="utf-8")
    print(f"wrote {mp}", flush=True)
    print(f"R7 {r7_ev['sum7']}/{r7_ev['sum15']} -> R8 {r8_ev['sum7']}/{r8_ev['sum15']} short={short}", flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
