#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R9：拆开评论／转述／口径／主体×渠道，再拟合系数。去重仍留金标 id。"""

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
from app.kg_lab.r8_fit import (  # noqa: E402
    FEATURE_NAMES,
    augment_features,
    evaluate,
    fit_coefficients,
    sensitivity,
)
from app.kg_lab.r9_buckets import (  # noqa: E402
    COMMENT_BUCKETS,
    RELAY_BUCKETS,
    apply_r9,
    r9_init,
    r9_names,
)
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
OUT = ROOT / "artifacts"
# 与 R8 报告一致的非零系数；其余维为 0
R8_COEFF = {
    "subject_match": 0.04,
    "claim_align": 0.08,
    "amount_status": 0.0,
    "time_anchor": 0.02,
    "credibility": 0.0,
    "channel_self": -0.08,
    "role_official_primary": 0.02,
    "role_official_reprint": 0.0,
    "role_institution_def": 0.0,
    "role_party_primary": 0.0,
    "role_party_relay": 0.02,
    "role_opposition_framing": 0.0,
    "role_mixed_summary": 0.0,
    "role_media_relay": 0.02,
    "role_commentary": -0.02,
    "tier_central_official": 0.0,
    "tier_local_official": 0.0,
    "tier_market_media": 0.0,
    "tier_foreign_media": 0.02,
    "tier_self_media": 0.0,
    "tier_other": 0.0,
}
GRID = (-0.12, -0.08, -0.04, -0.02, 0.0, 0.02, 0.04, 0.08, 0.12)
FOCUS = ("doc_009#p5", "doc_029#p7", "doc_033#p6")


def _misses(bundles, ev) -> list[dict[str, Any]]:
    by_q = {b["qid"]: b for b in bundles}
    out = []
    for q in ev["questions"]:
        b = by_q[q["qid"]]
        for gid in b["l2"]:
            if gid in q["at7"]:
                continue
            feat = b["feats"].get(gid) or {}
            cmt = feat.get("r9_comment") or ""
            relay = feat.get("r9_relay") or ""
            rank = q["ranks"].get(gid)
            if cmt == "institutional_gloss" and (rank or 99) > 7:
                why = "已标成制度说明，和混口径综述分开；名次仍在 7 名外，封顶里这段检索分太靠后"
            elif relay == "relay_party_primary" and rank is not None and rank <= 15:
                why = f"已标成转述本人原话，名次 {rank}，差 {rank - 7} 名"
            elif feat.get("claim_keyword") and not feat.get("claim_full"):
                why = "只有框架词（claim_keyword），没有问句原词；再加关键字会把通报段一起抬上来"
            else:
                why = f"名次 {rank}，细桶已经分开，幅度内仍进不了前 7"
            out.append({
                "qid": q["qid"],
                "id": gid,
                "rank": rank,
                "comment": cmt,
                "relay": relay,
                "claim_full": feat.get("claim_full"),
                "claim_keyword": feat.get("claim_keyword"),
                "subject_x_channel": feat.get("subject_x_channel"),
                "why": why,
            })
    return out


def _markdown(report: dict[str, Any]) -> str:
    r8, r9 = report["r8_replay"], report["r9"]
    lines = [
        "# R9 — 拆细卡住金标的四个桶",
        "",
        "- 只拆评论、转述、口径、主体×渠道。其余维沿用 R8。",
        "- 评论：`party_comment`（评当事人原话）／`institutional_gloss`（职位、还在单位、公务员）／`mixed_roundup`（时间线、尘埃落定）／`pure_opinion`。制度说明优先于时间线，所以「还在单位」不跟大结局混桶。",
        "- 转述：`relay_party_primary`（微博／深夜发文的本人原话）／`relay_official_bulletin`（回应称＋安置通报）／`relay_secondary`。`official_reprint` 不进这组。",
        "- 口径：`claim_full` 是问句原词或直接同义（没让我走、编制）；`claim_keyword` 只命中框架词（还在单位、公务员、自主择业）。二者互斥，替代粗 `claim_align`。",
        "- 主体×渠道：问句里有刘翔，且本段是他本人渠道上的话（微博、深夜发文、全文如下）。体育局问句配官方原文也算。",
        "- 去重仍沿用 R7：簇内有本题严格 id 就留该 id。规则打标，未调用 14B。",
        f"- 网格 **±0.12**。expand **{report['defaults']['expand_top_n']}** / paraphrase **{report['defaults']['n_paraphrase']}**，因果关。",
        f"- leak_any_bad：**{report['leak_any_bad']}**",
        f"- 墙钟：{report['wall_s']}s",
        "",
        "## 相对 R8",
        "",
        f"- 严格合计 @7 **{r8['sum7']}→{r9['sum7']}**（{r9['sum7'] - r8['sum7']:+d}），"
        f"@15 **{r8['sum15']}→{r9['sum15']}**（{r9['sum15'] - r8['sum15']:+d}）",
        f"- 14 条里 @7 有 **{r9['sum7']}** 条，还差 **{report['n_gold'] - r9['sum7']}** 条。",
        f"- L2 = {r9['l2']}，非零 {report['n_nonzero']} 维。",
        "",
        "| qid | l2 | R8 @7/@15 | R9 @7/@15 |",
        "|---|---:|---|---|",
    ]
    meta = {m["qid"]: m for m in report["questions_meta"]}
    for q8, q9 in zip(r8["questions"], r9["questions"]):
        lines.append(
            f"| {q8['qid']} | {meta[q8['qid']]['n_l2']} | {q8['n7']}/{q8['n15']} | {q9['n7']}/{q9['n15']} |"
        )
    lines += ["", "三条原漏标：", ""]
    for row in report["focus"]:
        lines.append(
            f"- `{row['id']}` {row['qid']}：拆桶后仍用 R8 系数时名次 {row['r8_rank']} → 重拟合名次 {row['r9_rank']}，"
            f"评论桶 `{row['comment'] or '—'}`，转述桶 `{row['relay'] or '—'}`，"
            f"full={row['claim_full']} keyword={row['claim_keyword']} 主体×渠道={row['subject_x_channel']}"
            + ("，**进 @7**" if row["in7"] else "，仍在 @7 外")
        )
    lines += [
        "",
        "## 系数（非零）",
        "",
        "| 维 | 初值（对齐 R8） | 拟合 |",
        "|---|---:|---:|",
    ]
    init = report["init"]
    for name, val in report["coeff_nonzero"]:
        lines.append(f"| `{name}` | {init.get(name, 0)} | {val} |")
    lines += ["", "## 未入围", ""]
    if not report["misses"]:
        lines.append("14 条都在 @7。")
    for row in report["misses"]:
        lines.append(
            f"- {row['qid']} `{row['id']}` 名次 {row['rank']}。"
            f"评论 `{row['comment'] or '—'}`，转述 `{row['relay'] or '—'}`，"
            f"full={row['claim_full']} keyword={row['claim_keyword']}。"
            f"{row['why']}"
        )
    lines += ["", "## 敏感度（置零后 @7 下降）", ""]
    fragile = [s for s in report["sensitivity"] if s["probe"] == "zero" and s["d7"] < 0]
    if not fragile:
        lines.append("没有单一系数置零后让 @7 下降。")
    for s in fragile:
        lines.append(f"- `{s['dim']}` 置零：@7 {s['d7']:+d}，@15 {s['d15']:+d}")
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
        "新桶计数（三题并集里出现过的段，按段计一次）：",
        "",
    ]
    for name, n in report["bucket_counts"]:
        lines.append(f"- `{name}` × {n}")
    lines += [
        "",
        "## 路径",
        f"- `{OUT / 'R9_refine_buckets.json'}`",
        f"- `{OUT / 'R9_refine_buckets.md'}`",
        "",
    ]
    return "\n".join(lines)


OUT = ROOT / "artifacts"


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
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

    names = r9_names(FEATURE_NAMES)
    # 新桶放前面，先被搜索拉开
    names = tuple(n for n in names if n in set(names))  # stable
    from app.kg_lab.r9_buckets import R9_ADDED
    names = R9_ADDED + tuple(n for n in names if n not in R9_ADDED)

    bundles = []
    leak_any = False
    questions_meta = []
    bucket_counts: dict[str, int] = {}
    seen_para: set[str] = set()
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
        apply_r9(bundle["feats"], bundle["metas"], question)
        for pid, feat in bundle["feats"].items():
            if pid in seen_para:
                continue
            seen_para.add(pid)
            for key in ("r9_comment", "r9_relay"):
                label = feat.get(key) or ""
                if label:
                    bucket_counts[label] = bucket_counts.get(label, 0) + 1
        bundle["qid"] = qid
        bundle["l2"] = l2
        bundles.append(bundle)
        questions_meta.append({"qid": qid, "n_l2": len(l2), "question": question})

    print("=== fit ===", flush=True)
    init = r9_init(R8_COEFF)
    for name in names:
        init.setdefault(name, 0.0)
    r8_ev = evaluate(bundles, init, k7=DEFAULT_K, k15=WIDE_K, names=names)
    print(f"  init {r8_ev['sum7']}/{r8_ev['sum15']}", flush=True)
    coeff, trace = fit_coefficients(
        bundles, k7=DEFAULT_K, k15=WIDE_K, init=init, laps=2, names=names, grid=GRID,
    )
    # 坐标上升容易停在「单维不动」。对新桶再做一轮小网格，只在不掉 @7 时收下。
    base_ev = evaluate(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K, names=names)
    for gloss in (0.04, 0.08, 0.12):
        for party in (0.04, 0.08, 0.12):
            for kw in (0.08, 0.12):
                for sx in (0.0, 0.08, 0.12):
                    trial = dict(coeff)
                    trial["cmt_institutional_gloss"] = gloss
                    trial["relay_party_primary"] = party
                    trial["claim_keyword"] = kw
                    trial["subject_x_channel"] = sx
                    ev = evaluate(bundles, trial, k7=DEFAULT_K, k15=WIDE_K, names=names)
                    if (ev["sum7"], ev["sum15"], -(ev["mean_capped"] or 0)) > (
                        base_ev["sum7"], base_ev["sum15"], -(base_ev["mean_capped"] or 0),
                    ):
                        coeff = trial
                        base_ev = ev
    trace.append({
        "step": "new_bucket_grid",
        "sum7": base_ev["sum7"],
        "sum15": base_ev["sum15"],
        "l2": base_ev["l2"],
    })
    r9_ev = evaluate(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K, names=names)
    print(f"  R9 {r9_ev['sum7']}/{r9_ev['sum15']} L2={r9_ev['l2']}", flush=True)
    sens = sensitivity(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K, names=names, cap=0.12)
    misses = _misses(bundles, r9_ev)

    focus = []
    r8_by = {q["qid"]: q for q in r8_ev["questions"]}
    r9_by = {q["qid"]: q for q in r9_ev["questions"]}
    feat_by = {}
    for b in bundles:
        for pid, feat in b["feats"].items():
            feat_by[(b["qid"], pid)] = feat
    for qid, gid in (("q_002", "doc_009#p5"), ("q_002", "doc_029#p7"), ("q_003", "doc_033#p6")):
        feat = feat_by.get((qid, gid)) or {}
        focus.append({
            "qid": qid,
            "id": gid,
            "r8_rank": r8_by[qid]["ranks"].get(gid),
            "r9_rank": r9_by[qid]["ranks"].get(gid),
            "in7": gid in r9_by[qid]["at7"],
            "comment": feat.get("r9_comment") or "",
            "relay": feat.get("r9_relay") or "",
            "claim_full": feat.get("claim_full"),
            "claim_keyword": feat.get("claim_keyword"),
            "subject_x_channel": feat.get("subject_x_channel"),
        })

    nonzero = [(n, coeff[n]) for n in names if abs(coeff.get(n) or 0) > 1e-12]
    n_gold = sum(m["n_l2"] for m in questions_meta)
    short = n_gold - r9_ev["sum7"]
    overfit = (
        f"系数在这 3 题、{n_gold} 条严格金标上拟合，没有留出题。"
        f"幅度夹在 ±0.12，消元后 {len(nonzero)} 个非零系数，L2={r9_ev['l2']}。"
        f"距离 14/14@7 还差 {short} 条。"
        "细桶把三条漏标从「评论／粗转述」里拆出来了；差下的名次见上表，不是再把同一个粗桶加大就能单独补上的。"
        if short else
        "14 条都进了 @7。系数仍是同题拟合，换题要重搜。"
    )

    def _slim(ev):
        return {k: v for k, v in ev.items() if k != "ranked"}

    report = {
        "ticket": "R9-refine-buckets",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "causal_expand": False,
            "grid_cap": 0.12,
            "comment_buckets": list(COMMENT_BUCKETS),
            "relay_buckets": list(RELAY_BUCKETS),
            "llm": None,
        },
        "leak_any_bad": leak_any,
        "n_gold": n_gold,
        "n_nonzero": len(nonzero),
        "questions_meta": questions_meta,
        "bucket_counts": sorted(bucket_counts.items(), key=lambda kv: (-kv[1], kv[0])),
        "init": {n: init.get(n, 0) for n in names if abs(init.get(n) or 0) > 1e-12},
        "coeff": {n: coeff.get(n, 0) for n in names},
        "coeff_nonzero": nonzero,
        "trace": trace,
        "r8_replay": _slim(r8_ev),
        "r9": _slim(r9_ev),
        "focus": focus,
        "misses": misses,
        "sensitivity": [s for s in sens if s["probe"] == "zero"],
        "overfit": overfit,
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    jp = OUT / "R9_refine_buckets.json"
    mp = OUT / "R9_refine_buckets.md"
    jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    mp.write_text(_markdown(report), encoding="utf-8")
    print(f"wrote {mp}", flush=True)
    print(f"init {r8_ev['sum7']}/{r8_ev['sum15']} -> R9 {r9_ev['sum7']}/{r9_ev['sum15']} short={short}", flush=True)
    for row in focus:
        print(f"  {row['id']} {row['r8_rank']}->{row['r9_rank']} in7={row['in7']}", flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
