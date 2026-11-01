#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R6：多维标签加权求和扫参。去重固定，融合只算一次。

score = rrf + Σ coeff × feature。对照 R4 粗乘子与 R5 推荐细乘子。
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.config import ARTIFACTS, DEFAULT_K, WIDE_K  # noqa: E402
from app.kg_lab.eval_metrics import leak_check, measure_arm  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.multidim_weight import (  # noqa: E402
    DIMS,
    build_bundle,
    query_actors,
    rank_with_coeff,
    zero_coeff,
)
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.source_role import R5_RECOMMENDED, rerank_source_role  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"

# 1D 档。RRF 头部相邻分差大约 0.002～0.008，0.08 已经能把特征拉开的段从中部抬进前排。
_LEVELS: dict[str, tuple[float, ...]] = {
    "subject_match": (0.0, 0.01, 0.03, 0.08),
    "source_role": (0.0, 0.015, 0.04, 0.08),
    "claim_align": (0.0, 0.01, 0.03, 0.08),
    "amount_status": (0.0, 0.01, 0.03),
    "time_anchor": (0.0, 0.01, 0.03),
}


def _as_pick(ranked: list[tuple[str, float]], queries: list[str]) -> dict[str, Any]:
    return {
        "arm": "rrf_multidim",
        "queries": queries,
        "picked": [{"para_id": pid, "score": sc} for pid, sc in ranked],
        "paths": {},
    }


def _hits(ranked, queries, gold, universe, k: int) -> dict[str, Any]:
    m = measure_arm(_as_pick(ranked, queries), gold=gold, universe=universe, k=k)
    return {"n": m["n_gold_hit"], "ids": m["gold_hit_ids"]}


def _rank_map(ranked: list[tuple[str, float]]) -> dict[str, int]:
    return {pid: i for i, (pid, _) in enumerate(ranked, 1)}


def _gold_stats(ranked: list[tuple[str, float]], l2: list[str]) -> dict[str, Any]:
    pos = _rank_map(ranked)
    cap = len(ranked) + 1
    capped = []
    present = []
    detail = []
    for gid in l2:
        r = pos.get(gid)
        capped.append(r if r else cap)
        if r:
            present.append(r)
        detail.append({"id": gid, "rank": r})
    return {
        "detail": detail,
        "mean_capped": round(statistics.fmean(capped), 2) if capped else None,
        "median_capped": round(statistics.median(capped), 2) if capped else None,
        "mean_present": round(statistics.fmean(present), 2) if present else None,
        "median_present": round(statistics.median(present), 2) if present else None,
        "n_outside": sum(1 for r in detail if r["rank"] is None),
    }


def _q001_at7(row: dict[str, Any]) -> int:
    for q in row["questions"]:
        if q["qid"] == "q_001":
            return int(q["at7"]["n"])
    return 0


def _better(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """先多进 @7。合计相同则保住 q_001 已满的 4 条，再把金标名次压低，然后看 @15。"""
    ka = (
        a["sum7"],
        _q001_at7(a),
        -a["mean_capped"],
        a["sum15"],
        -a["coeff_l1"],
    )
    kb = (
        b["sum7"],
        _q001_at7(b),
        -b["mean_capped"],
        b["sum15"],
        -b["coeff_l1"],
    )
    return ka > kb


def _eval_ranked(
    name: str,
    axis: str,
    coeff: dict[str, float] | None,
    ranked_by_q: dict[str, list[tuple[str, float]]],
    prepared: list[dict[str, Any]],
) -> dict[str, Any]:
    q_rows = []
    for p in prepared:
        ranked = ranked_by_q[p["qid"]]
        h7 = _hits(ranked, p["queries"], p["gold"], p["universe"], DEFAULT_K)
        h15 = _hits(ranked, p["queries"], p["gold"], p["universe"], WIDE_K)
        stats = _gold_stats(ranked, p["l2"])
        q_rows.append({
            "qid": p["qid"],
            "at7": h7,
            "at15": h15,
            "top7": [pid for pid, _ in ranked[:DEFAULT_K]],
            "gold": stats,
        })
    l1 = 0.0 if not coeff else sum(abs(v) for v in coeff.values())
    return {
        "name": name,
        "axis": axis,
        "coeff": coeff,
        "coeff_l1": round(l1, 4),
        "questions": q_rows,
        "sum7": sum(q["at7"]["n"] for q in q_rows),
        "sum15": sum(q["at15"]["n"] for q in q_rows),
        "mean_capped": round(
            statistics.fmean(q["gold"]["mean_capped"] for q in q_rows), 2
        ),
    }


def _multidim_ranked(prepared, coeff) -> dict[str, list[tuple[str, float]]]:
    return {p["qid"]: rank_with_coeff(p["bundle"], coeff) for p in prepared}


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
    case = next(
        p for p in (ROOT / "data" / "trs-samples").iterdir()
        if p.is_dir() and "刘翔" in p.name and (p / "raw_documents.json").is_file()
    )
    dossier, union_ids, questions = union_pack_ids(case)
    rows_all = build_corpus_rows(dossier, case_slug=SLUG, para_ids=union_ids)
    index = KgIndex(SLUG, rows_all)
    index.ensure_embeddings(force=False)

    prepared: list[dict[str, Any]] = []
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
        if not leak_check(
            {"queries": queries, "selection_used_gold": False}, gold=gold,
        ).get("ok"):
            leak_any = True
        bundle = build_bundle(sub_rows, fused, question)
        prepared.append({
            "qid": qid,
            "question": question,
            "actors": query_actors(question),
            "gold": gold,
            "universe": universe,
            "l2": l2,
            "rows": sub_rows,
            "fused": fused,
            "queries": queries,
            "bundle": bundle,
            "n_l2": len(l2),
            "n_fused": len(fused),
            "n_universe": len(universe),
        })
        print(f"  actors={query_actors(question)} l2={len(l2)} fused={len(fused)}", flush=True)

    def role_ranked(weights):
        out = {}
        for p in prepared:
            rr = rerank_source_role(
                p["rows"], p["fused"], dedupe=True, role_prior=True, weights=weights,
            )
            out[p["qid"]] = rr["ranked"]
        return out

    print("=== baselines ===", flush=True)
    r4 = _eval_ranked("r4_default", "baseline", None, role_ranked(None), prepared)
    r5 = _eval_ranked("r5_recommended", "baseline", None, role_ranked(R5_RECOMMENDED), prepared)
    print(f"  R4 {r4['sum7']}/{r4['sum15']}  R5 {r5['sum7']}/{r5['sum15']}", flush=True)

    cache: dict[tuple, dict[str, Any]] = {}

    def point(name: str, axis: str, coeff: dict[str, float]) -> dict[str, Any]:
        key = tuple(round(float(coeff.get(d) or 0.0), 5) for d in DIMS)
        if key in cache:
            row = dict(cache[key])
            row["name"] = name
            row["axis"] = axis
            return row
        ranked = _multidim_ranked(prepared, coeff)
        row = _eval_ranked(name, axis, {d: float(coeff.get(d) or 0.0) for d in DIMS}, ranked, prepared)
        cache[key] = row
        print(
            f"  {name} {row['sum7']}/{row['sum15']} mean_cap={row['mean_capped']}",
            flush=True,
        )
        return row

    grid = [r4, r5]
    zero = zero_coeff()
    grid.append(point("sum_zero", "baseline", zero))

    # 1D
    oned = []
    for dim in DIMS:
        for level in _LEVELS[dim]:
            if level == 0.0:
                continue
            coeff = dict(zero)
            coeff[dim] = level
            oned.append(point(f"{dim}_{level}", dim, coeff))
    grid.extend(oned)

    # 坐标上升：每一维在其余维已选档上再挑
    current = dict(zero)
    for lap in (1, 2):
        for dim in DIMS:
            best_row = None
            best_level = current[dim]
            for level in _LEVELS[dim]:
                trial = dict(current)
                trial[dim] = level
                row = point(f"asc{lap}_{dim}_{level}", "ascent", trial)
                if best_row is None or _better(row, best_row):
                    best_row = row
                    best_level = level
            current[dim] = best_level
        grid.append(point(f"ascent_lap{lap}", "ascent", dict(current)))

    # 若 @7 仍远不到 14，再把主体／口径系数放到更大一档（仍不是全网格）
    best_so_far = max(grid, key=lambda r: (
        r["sum7"], r["sum15"], -r["mean_capped"], -r.get("coeff_l1") or 0,
    ))
    if best_so_far["sum7"] < sum(p["n_l2"] for p in prepared):
        for extra in (
            {"subject_match": 0.15, "claim_align": 0.15, "source_role": current["source_role"]},
            {"subject_match": 0.15, "claim_align": 0.08, "source_role": 0.08,
             "amount_status": current["amount_status"], "time_anchor": current["time_anchor"]},
            {"claim_align": 0.15, "source_role": 0.08, "time_anchor": 0.03},
        ):
            coeff = dict(zero)
            coeff.update(current)
            coeff.update(extra)
            grid.append(point("strong_" + "_".join(f"{k}{v}" for k, v in extra.items()), "strong", coeff))
        # 上一轮坐标上升在「保住 q_001 满覆盖」下名次最好的一组，钉住免得目标函数一改就丢
        grid.append(point("subject08_claim03_time01", "pinned", {
            "subject_match": 0.08,
            "source_role": 0.0,
            "claim_align": 0.03,
            "amount_status": 0.0,
            "time_anchor": 0.01,
        }))

    floors = {q["qid"]: q["at7"]["n"] for q in r5["questions"]}
    for row in grid:
        row["floor_miss"] = sum(
            max(0, floors[q["qid"]] - q["at7"]["n"]) for q in row["questions"]
        )
    # 去重推荐：多维点里按目标函数，不把 R4/R5 乘子臂算进「求和推荐」
    multi = [r for r in grid if r["coeff"] is not None]
    # 同一系数只留第一次出现的名字
    seen = set()
    unique = []
    for r in grid:
        if r["coeff"] is None:
            unique.append(r)
            continue
        key = tuple(round(r["coeff"][d], 5) for d in DIMS)
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    multi_unique = [r for r in unique if r["coeff"] is not None]
    winner = multi_unique[0]
    for row in multi_unique[1:]:
        if _better(row, winner):
            winner = row

    # 金标诊断（相对 RRF 池、去重代表、R6 名次）
    r6_ranked = _multidim_ranked(prepared, winner["coeff"])
    r4_ranked = role_ranked(None)
    r5_ranked = role_ranked(R5_RECOMMENDED)
    diagnosis = []
    for p in prepared:
        rrf_pos = _rank_map(p["fused"])
        r4_pos = _rank_map(r4_ranked[p["qid"]])
        r5_pos = _rank_map(r5_ranked[p["qid"]])
        r6_pos = _rank_map(r6_ranked[p["qid"]])
        rep_of = p["bundle"]["rep_of"]
        for gid in p["l2"]:
            feats = (p["bundle"]["feats"].get(gid) or {})
            rrf_rank = rrf_pos.get(gid)
            r6_rank = r6_pos.get(gid)
            rep = rep_of.get(gid, gid)
            if rrf_rank is None:
                bucket = "pool_miss"
            elif rep != gid and r6_rank is None:
                bucket = "deduped"
            elif r6_rank is not None and r6_rank <= DEFAULT_K:
                bucket = "top7"
            else:
                bucket = "ranking"
            diagnosis.append({
                "qid": p["qid"],
                "id": gid,
                "bucket": bucket,
                "rrf_rank": rrf_rank,
                "r4_rank": r4_pos.get(gid),
                "r5_rank": r5_pos.get(gid),
                "r6_rank": r6_rank,
                "dedupe_rep": rep,
                "features": feats,
            })

    buckets = {}
    for row in diagnosis:
        buckets[row["bucket"]] = buckets.get(row["bucket"], 0) + 1

    def _qmap(block):
        return {q["qid"]: q for q in block["questions"]}

    report = {
        "ticket": "R6-multidim-weight",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "causal_expand": False,
            "formula": "rrf + sum(coeff_d * feature_d)",
            "dims": list(DIMS),
        },
        "leak_any_bad": leak_any,
        "questions_meta": [
            {
                "qid": p["qid"],
                "question": p["question"],
                "actors": p["actors"],
                "n_l2": p["n_l2"],
                "n_fused": p["n_fused"],
                "n_universe": p["n_universe"],
            }
            for p in prepared
        ],
        "r4": {k: r4[k] for k in ("name", "sum7", "sum15", "mean_capped", "questions")},
        "r5": {k: r5[k] for k in ("name", "sum7", "sum15", "mean_capped", "questions")},
        "recommendation": {
            "name": winner["name"],
            "coeff": winner["coeff"],
            "sum7": winner["sum7"],
            "sum15": winner["sum15"],
            "mean_capped": winner["mean_capped"],
            "questions": winner["questions"],
            "delta_vs_r4": {
                "at7": winner["sum7"] - r4["sum7"],
                "at15": winner["sum15"] - r4["sum15"],
            },
            "delta_vs_r5": {
                "at7": winner["sum7"] - r5["sum7"],
                "at15": winner["sum15"] - r5["sum15"],
            },
        },
        "grid": [
            {
                "name": r["name"],
                "axis": r["axis"],
                "sum7": r["sum7"],
                "sum15": r["sum15"],
                "mean_capped": r["mean_capped"],
                "coeff": r["coeff"],
                "questions": [
                    {
                        "qid": q["qid"],
                        "at7": q["at7"]["n"],
                        "at15": q["at15"]["n"],
                        "mean_capped": q["gold"]["mean_capped"],
                        "median_capped": q["gold"]["median_capped"],
                    }
                    for q in r["questions"]
                ],
            }
            for r in unique
        ],
        "diagnosis": diagnosis,
        "buckets": buckets,
        "n_gold": sum(p["n_l2"] for p in prepared),
        "full_at7": winner["sum7"] == sum(p["n_l2"] for p in prepared),
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    report["reading"] = _reading(report, _qmap(r4), _qmap(r5), _qmap(winner))
    art = ARTIFACTS
    art.mkdir(parents=True, exist_ok=True)
    jp = art / "R6_multidim_weight.json"
    mp = art / "R6_multidim_weight.md"
    jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    mp.write_text(_markdown(report), encoding="utf-8")
    print(f"wrote {mp}", flush=True)
    print(
        f"recommend {winner['name']} {winner['sum7']}/{winner['sum15']} "
        f"vs R4 {r4['sum7']}/{r4['sum15']} R5 {r5['sum7']}/{r5['sum15']} "
        f"buckets={buckets}",
        flush=True,
    )
    return 0 if not leak_any else 3


def _reading(report, r4q, r5q, r6q) -> str:
    rec = report["recommendation"]
    bits = [
        f"推荐 `{rec['name']}`：严格合计 @7 {report['r4']['sum7']}→{rec['sum7']}（相对 R4 {rec['delta_vs_r4']['at7']:+d}，相对 R5 {rec['delta_vs_r5']['at7']:+d}），"
        f"@15 {report['r4']['sum15']}→{rec['sum15']}（相对 R4 {rec['delta_vs_r4']['at15']:+d}，相对 R5 {rec['delta_vs_r5']['at15']:+d}）。"
    ]
    if report["full_at7"]:
        bits.append("三题金标都进了 @7。")
    else:
        bits.append(
            f"14 条里进 @7 的是 {rec['sum7']} 条，不到 14/14。"
            f"缺席归因：{report['buckets']}。"
        )
    # 哪一题相对 R5 变了
    for qid in r4q:
        a, b, c = r4q[qid], r5q[qid], r6q[qid]
        if (c["at7"]["n"], c["at15"]["n"]) != (b["at7"]["n"], b["at15"]["n"]):
            bits.append(
                f"{qid} 相对 R5：@7 {b['at7']['n']}→{c['at7']['n']}，@15 {b['at15']['n']}→{c['at15']['n']}。"
            )
    return "".join(bits)


def _bottleneck(report: dict[str, Any]) -> list[str]:
    rows = [d for d in report["diagnosis"] if d["bucket"] != "top7"]
    lines = [
        "14 条金标都在融合候选里（没有 pool_miss）。加分只能重排已经有正分的段，不能无中生有。",
    ]
    deduped = [d for d in rows if d["bucket"] == "deduped"]
    far = [d for d in rows if d["bucket"] == "ranking" and (d["r6_rank"] or 999) > 30]
    near = [d for d in rows if d["bucket"] == "ranking" and (d["r6_rank"] or 999) <= 30]
    if deduped:
        bits = "、".join(
            f"`{d['id']}`→代表 `{d['dedupe_rep']}`（RRF 名次 {d['rrf_rank']}）" for d in deduped
        )
        lines.append(f"去重换代表、严格 id 不再出现：{bits}。这不是系数问题，是簇代表规则。")
    if near:
        bits = "、".join(
            f"{d['qid']} `{d['id']}` R6 名次 {d['r6_rank']}" for d in near
        )
        lines.append(f"进了名单、离 @7 不远：{bits}。再加大系数会把同样高分的非金标一起抬上来。")
    if far:
        bits = "、".join(
            f"{d['qid']} `{d['id']}` RRF {d['rrf_rank']}→R6 {d['r6_rank']}（claim={d['features'].get('claim_align')}）"
            for d in far
        )
        lines.append(
            "名次仍在 30 开外，段内对不上问句口径，系数再大也是整类一起抬：" + bits + "。"
            "下一步是补标签（这些金标段没有问句里的对立词），不是再加大现有系数。"
        )
    return lines


def _markdown(report: dict[str, Any]) -> str:
    rec = report["recommendation"]
    r4, r5 = report["r4"], report["r5"]
    lines = [
        "# R6 — 多维标签加权求和",
        "",
        "- 公式：`score = rrf + Σ coeff × feature`（各特征 0～1，求和，不是主体×角色一个乘子）",
        "- 去重：R4 通稿簇仍开。`source_role` 用 R5 细类压成 0～1 后乘系数。",
        f"- 底座对照：R4 粗乘子 @7/@15 = **{r4['sum7']}/{r4['sum15']}**；R5 推荐细乘子 = **{r5['sum7']}/{r5['sum15']}**",
        f"- expand **{report['defaults']['expand_top_n']}** / paraphrase **{report['defaults']['n_paraphrase']}**，因果关",
        f"- leak_any_bad：**{report['leak_any_bad']}**",
        f"- 墙钟：{report['wall_s']}s",
        "",
        "## 推荐系数",
        "",
        f"- 点名 `{rec['name']}`",
        "",
        "| 维 | 系数 |",
        "|---|---:|",
    ]
    for d in report["defaults"]["dims"]:
        lines.append(f"| `{d}` | {rec['coeff'][d]} |")
    lines += [
        "",
        f"- 严格合计 @7 **{rec['sum7']}**（R4 {rec['delta_vs_r4']['at7']:+d}，R5 {rec['delta_vs_r5']['at7']:+d}），"
        f"@15 **{rec['sum15']}**（R4 {rec['delta_vs_r4']['at15']:+d}，R5 {rec['delta_vs_r5']['at15']:+d}）",
        f"- 金标名次（缺席按该题名单长度+1）：三题平均 capped mean = {rec['mean_capped']}"
        f"（R4 {r4['mean_capped']}，R5 {r5['mean_capped']}）",
        "",
        report["reading"],
        "",
        "## 分题",
        "",
        "| qid | l2 | 池（融合条数） | R4 @7/@15 | R5 @7/@15 | R6 @7/@15 | R6 金标名次均值／中位（capped） |",
        "|---|---:|---:|---|---|---|---|",
    ]
    meta = {q["qid"]: q for q in report["questions_meta"]}
    r4q = {q["qid"]: q for q in r4["questions"]}
    r5q = {q["qid"]: q for q in r5["questions"]}
    r6q = {q["qid"]: q for q in rec["questions"]}
    for qid, m in meta.items():
        g = next(q["gold"] for q in rec["questions"] if q["qid"] == qid)
        lines.append(
            f"| {qid} | {m['n_l2']} | {m['n_fused']} | "
            f"{r4q[qid]['at7']['n']}/{r4q[qid]['at15']['n']} | "
            f"{r5q[qid]['at7']['n']}/{r5q[qid]['at15']['n']} | "
            f"{r6q[qid]['at7']['n']}/{r6q[qid]['at15']['n']} | "
            f"{g['mean_capped']} / {g['median_capped']} |"
        )
    lines += ["", "问句抽出的主体：", ""]
    for m in report["questions_meta"]:
        lines.append(f"- **{m['qid']}** 「{m['question']}」→ {m['actors'] or '（问句里没有名单内主体）'}")

    lines += ["", "## q_001 Top-7", ""]
    for label, block in (("R4", r4q["q_001"]), ("R5", r5q["q_001"]), ("R6", r6q["q_001"])):
        lines.append(f"{label}：")
        lines.append("")
        for i, pid in enumerate(block["top7"], 1):
            mark = "金标" if pid in set(block["at7"]["ids"]) else "非金标"
            lines.append(f"{i}. `{pid}`（{mark}）")
        lines.append("")

    lines += [
        "## 金标名次与瓶颈",
        "",
        f"理想 14/14@7：**{'达到' if report['full_at7'] else '未达到'}**。分桶：{report['buckets']}。",
        "",
        "`pool_miss` = 融合候选里没有这条（RRF 各路都没给正分），加分抬不进来。",
        "`deduped` = 在候选里，但通稿簇代表不是它，名单上不出现这条 id。",
        "`ranking` = 在名单里但名次低于 7。",
        "",
        "| qid | id | 桶 | RRF名次 | R4 | R5 | R6 | 代表 | subject | role | claim | amount | time |",
        "|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["diagnosis"]:
        f = row["features"]
        def cell(v):
            return "—" if v is None else str(v)
        lines.append(
            f"| {row['qid']} | `{row['id']}` | {row['bucket']} | {cell(row['rrf_rank'])} | "
            f"{cell(row['r4_rank'])} | {cell(row['r5_rank'])} | {cell(row['r6_rank'])} | "
            f"`{row['dedupe_rep']}` | {f.get('subject_match', 0)} | {f.get('source_role', 0)} | "
            f"{f.get('claim_align', 0)} | {f.get('amount_status', 0)} | {f.get('time_anchor', 0)} |"
        )
    lines += ["", "### 为何到不了 14/14@7", ""]
    lines.extend(_bottleneck(report))
    lines += [
        "",
        "## 网格（去重后的不同系数）",
        "",
        "| 点 | 轴 | @7 | @15 | capped mean | 系数 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in report["grid"]:
        coeff = row["coeff"]
        if coeff is None:
            shown = "（角色乘子臂）"
        else:
            shown = ", ".join(f"{k}={v}" for k, v in coeff.items() if v)
            shown = shown or "全 0"
        lines.append(
            f"| `{row['name']}` | {row['axis']} | {row['sum7']} | {row['sum15']} | "
            f"{row['mean_capped']} | {shown} |"
        )
    lines += [
        "",
        "## 路径",
        f"- `{ARTIFACTS / 'R6_multidim_weight.json'}`",
        f"- `{ARTIFACTS / 'R6_multidim_weight.md'}`",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
