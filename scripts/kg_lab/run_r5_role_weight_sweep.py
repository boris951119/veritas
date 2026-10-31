#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R5：细角色乘子扫参。去重固定开，对照 R4 默认粗乘子。

融合只算一次；网格只重加权。expand 16 / paraphrase 1，因果关。
"""

from __future__ import annotations

import json
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
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.source_role import (  # noqa: E402
    R4_FINE_EQUIV,
    ROLE_WEIGHT,
    rerank_source_role,
)
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
FOCUS = ("doc_012#p2", "doc_014#p1", "doc_030#p5")
RANK_CAP = 40  # 名单外按这个名次计「被压下去」


def _vary(base: dict[str, float], **kw: float) -> dict[str, float]:
    out = dict(base)
    out.update(kw)
    return out


def _oned() -> list[dict[str, Any]]:
    b = R4_FINE_EQUIV
    pts = [{"name": "r4_mapped", "axis": "baseline", "weights": dict(b)}]
    for v in (1.06, 1.00, 0.94):
        pts.append({
            "name": f"reprint_{v:.2f}",
            "axis": "reprint",
            "weights": _vary(b, official_reprint=v),
        })
    for name, kw in (
        ("party_up", {"party_primary": 1.14, "party_relay": 1.02, "opposition_framing": 1.02}),
        ("party_up_opp_down", {"party_primary": 1.14, "party_relay": 1.02, "opposition_framing": 0.92}),
        ("party_strong", {"party_primary": 1.18, "party_relay": 0.98, "opposition_framing": 0.92}),
    ):
        pts.append({"name": name, "axis": "party", "weights": _vary(b, **kw)})
    for name, kw in (
        ("mixed_0.82", {"mixed_summary": 0.82}),
        ("mixed_0.76", {"mixed_summary": 0.76}),
        ("mixed_0.82_comm_0.84", {"mixed_summary": 0.82, "commentary": 0.84}),
    ):
        pts.append({"name": name, "axis": "mixed", "weights": _vary(b, **kw)})
    return pts


def _as_pick(ranked: list[tuple[str, float]], queries: list[str]) -> dict[str, Any]:
    return {
        "arm": "rrf_source_role",
        "queries": queries,
        "picked": [{"para_id": pid, "score": sc} for pid, sc in ranked],
        "paths": {},
    }


def _hits(ranked, queries, gold, universe, k: int) -> dict[str, Any]:
    m = measure_arm(_as_pick(ranked, queries), gold=gold, universe=universe, k=k)
    return {"n": m["n_gold_hit"], "ids": m["gold_hit_ids"]}


def _focus(ranked: list[tuple[str, float]]) -> dict[str, Any]:
    index = {pid: i for i, (pid, _) in enumerate(ranked, 1)}
    out = {}
    for pid in FOCUS:
        r = index.get(pid)
        out[pid] = {
            "rank": r,
            "in7": bool(r and r <= DEFAULT_K),
            "in15": bool(r and r <= WIDE_K),
        }
    return out


def _focus_push(focus: dict[str, Any]) -> int:
    """名次越靠后越高；不在前 RANK_CAP 视作已被挤出。"""
    total = 0
    for pid in FOCUS:
        r = focus[pid]["rank"]
        total += r if r is not None else RANK_CAP + 1
    return total


def _regressed(row: dict[str, Any], base: dict[str, Any]) -> bool:
    for q, bq in zip(row["questions"], base["questions"]):
        if q["at7"]["n"] < bq["at7"]["n"] or q["at15"]["n"] < bq["at15"]["n"]:
            return True
        if set(bq["at7"]["ids"]) - set(q["at7"]["ids"]):
            return True
        if set(bq["at15"]["ids"]) - set(q["at15"]["ids"]):
            return True
    return False


def _better(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """a 是否优于 b：先严格命中，再把三个焦点段压下去，再少改系数。"""
    if a["sum7"] != b["sum7"]:
        return a["sum7"] > b["sum7"]
    if a["sum15"] != b["sum15"]:
        return a["sum15"] > b["sum15"]
    pa, pb = _focus_push(a["q001_focus"]), _focus_push(b["q001_focus"])
    if pa != pb:
        return pa > pb
    return a["n_coeff_changed"] < b["n_coeff_changed"]


def _eval_point(
    spec: dict[str, Any],
    prepared: list[dict[str, Any]],
) -> dict[str, Any]:
    weights = spec["weights"]
    q_rows = []
    for p in prepared:
        rr = rerank_source_role(
            p["rows"], p["fused"], dedupe=True, role_prior=True, weights=weights,
        )
        ranked = rr["ranked"]
        h7 = _hits(ranked, p["queries"], p["gold"], p["universe"], DEFAULT_K)
        h15 = _hits(ranked, p["queries"], p["gold"], p["universe"], WIDE_K)
        q_rows.append({
            "qid": p["qid"],
            "at7": h7,
            "at15": h15,
            "top7": [pid for pid, _ in ranked[:DEFAULT_K]],
            "focus": _focus(ranked) if p["qid"] == "q_001" else None,
        })
    changed = sorted(
        k for k, v in weights.items() if abs(v - R4_FINE_EQUIV.get(k, v)) > 1e-9
    )
    q1 = next(q for q in q_rows if q["qid"] == "q_001")
    return {
        "name": spec["name"],
        "axis": spec["axis"],
        "weights": weights,
        "changed": changed,
        "n_coeff_changed": len(changed),
        "questions": q_rows,
        "sum7": sum(q["at7"]["n"] for q in q_rows),
        "sum15": sum(q["at15"]["n"] for q in q_rows),
        "q001_focus": q1["focus"],
        "q001_top7": q1["top7"],
    }


def _combos(oned_rows: list[dict[str, Any]], r4: dict[str, Any]) -> list[dict[str, Any]]:
    """各轴上不掉严格命中的最好一点，做 2D/3D。轴上没有更好的就留 R4 等价乘子。"""
    eligible = [r for r in oned_rows if not _regressed(r, r4)]

    def best_on(axis: str) -> dict[str, float]:
        cands = [r for r in eligible if r["axis"] == axis]
        if not cands:
            return dict(R4_FINE_EQUIV)
        winner = cands[0]
        for row in cands[1:]:
            if _better(row, winner):
                winner = row
        return dict(winner["weights"])

    reprint_w = best_on("reprint")
    party_w = best_on("party")
    mixed_w = best_on("mixed")
    # 只取相对基线有改动的轴；交叉时用该轴改过的键
    def patch(base: dict[str, float], src: dict[str, float]) -> dict[str, float]:
        out = dict(base)
        for k, v in src.items():
            if abs(v - R4_FINE_EQUIV.get(k, v)) > 1e-9:
                out[k] = v
        return out

    seeds = [
        ("combo_reprint_party", patch(patch(dict(R4_FINE_EQUIV), reprint_w), party_w)),
        ("combo_reprint_mixed", patch(patch(dict(R4_FINE_EQUIV), reprint_w), mixed_w)),
        ("combo_party_mixed", patch(patch(dict(R4_FINE_EQUIV), party_w), mixed_w)),
        ("combo_all", patch(patch(patch(dict(R4_FINE_EQUIV), reprint_w), party_w), mixed_w)),
        # 1D 显示：压低全部转载会把 012 相对抬高；压 party_relay 会抵消评论下压带进的金标。
        # 这一格只抬本人渠道、压对立包装和混口径，转载与当事人转述维持 R4。
        ("hold_reprint_press_mixed", _vary(
            R4_FINE_EQUIV,
            party_primary=1.14,
            opposition_framing=0.92,
            mixed_summary=0.76,
            commentary=0.84,
        )),
    ]
    out = []
    seen = {json.dumps(r["weights"], sort_keys=True) for r in oned_rows}
    for name, weights in seeds:
        key = json.dumps(weights, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "axis": "combo", "weights": weights})
    return out


def _recommend(rows: list[dict[str, Any]], r4: dict[str, Any]) -> dict[str, Any]:
    ok = [r for r in rows if not _regressed(r, r4)]
    winner = r4
    for row in ok:
        if _better(row, winner):
            winner = row
    same_hits = winner["sum7"] == r4["sum7"] and winner["sum15"] == r4["sum15"]
    same_focus = _focus_push(winner["q001_focus"]) == _focus_push(r4["q001_focus"])
    if winner["name"] in {"r4_default", "r4_mapped"} or (same_hits and same_focus and winner["n_coeff_changed"] == 0):
        why = "扫过的系数没有在不掉严格命中的前提下把焦点段压下去，也没有抬高合计命中。推荐维持 R4 粗乘子。"
        keep_r4 = True
    elif same_hits:
        why = (
            "严格 @7/@15 与 R4 相同。推荐表只把非金标焦点段的名次压后，"
            "不把转载乘子降到会挤掉金标的程度。"
        )
        keep_r4 = False
    else:
        why = "推荐表在不丢掉已有严格命中的前提下提高了合计命中。"
        keep_r4 = False
    return {"name": winner["name"], "keep_r4": keep_r4, "why": why, "row": winner}


def _markdown(report: dict[str, Any]) -> str:
    rec = report["recommendation"]
    r4 = report["r4_default"]
    lines = [
        "# R5 — 细角色乘子扫参",
        "",
        f"- 底座：R4 `rrf_source_role`（去重开，expand **{report['defaults']['expand_top_n']}** / paraphrase **{report['defaults']['n_paraphrase']}**，因果关）",
        "- 主尺：严格 supporting_facts L2 @7 / @15",
        f"- 网格：1D {report['n_oned']} 点 + 轴上优胜交叉 {report['n_combo']} 点。融合只算一次。",
        f"- leak_any_bad：**{report['leak_any_bad']}**",
        f"- 墙钟：{report['wall_s']}s",
        "",
        "## 细角色（平台分不进归类）",
        "",
        "刘翔本人渠道（第一人称全文／微博上的「我」）标 `party_primary`，即使 `source_credibility` 很低。新华社「电（记者」转微博、标题带买断冲突的，标 `opposition_framing`，不跟本人渠道抢。体育局页面且标题不是转载题的通报段标 `official_primary`；带媒体尾巴或「刘翔：」新闻题的同文标 `official_reprint`。`doc_030#p5` 这类两套口径写在一段里的时间线标 `mixed_summary`。去重仍用 R4 粗角色，所以通报簇的代表不变，变的是乘子。",
        "",
        "q_001 宇宙里的细角色计数：",
        "",
    ]
    for role, n in report["q001_fine_counts"]:
        lines.append(f"- `{role}` × {n}")
    lines += [
        "",
        "焦点段标签：",
        "",
    ]
    for pid, info in report["focus_labels"].items():
        lines.append(
            f"- `{pid}` 细角色 `{info['fine']}`（粗 `{info['coarse']}`，渠道 `{info['channel']}`，cred {info['cred']}）"
        )
    lines += [
        "",
        "## 推荐",
        "",
        f"- 选用 **`{rec['name']}`**。{rec['why']}",
        "",
        "| 角色 | R4 等价 | 推荐 |",
        "|---|---:|---:|",
    ]
    rec_w = rec["weights"]
    for role in (
        "official_primary", "official_reprint", "institution_def",
        "party_primary", "party_relay", "opposition_framing",
        "mixed_summary", "media_relay", "commentary",
    ):
        lines.append(f"| `{role}` | {R4_FINE_EQUIV[role]} | {rec_w.get(role, R4_FINE_EQUIV[role])} |")
    lines += [
        "",
        f"- 相对 R4 默认：严格合计 @7 {r4['sum7']}→{rec['sum7']}（{rec['sum7'] - r4['sum7']:+d}），@15 {r4['sum15']}→{rec['sum15']}（{rec['sum15'] - r4['sum15']:+d}）",
        "",
        "推荐表只改四格：`party_primary` 1.05→1.14，`opposition_framing` 1.05→0.92，`mixed_summary` 0.90→0.76，`commentary` 0.90→0.84。`official_reprint` 与 `party_relay` 维持 R4。",
        "@15 的 +1 来自 q_002：`doc_009#p5` 进入 @15，@7 仍只有 `doc_028#p1`。q_001 四条金标仍都在 @7。",
        "`doc_014#p1`（新华社转微博、对立包装）6→11，退出 Top-7。`doc_030#p5`（混口径）7→13，退出 Top-7。空出来的两位是 `doc_029#p8` 与 `doc_025#p12`，不是新的金标。",
        "`doc_012#p2` 仍是第 4。它确实是转载题，但把全体 `official_reprint` 降到 1.00 或 0.94 时名次变成 3：金标转载簇掉得更快，这条新闻题转载就相对上升。所以不把转载乘子降到原文之下。",
        "`party_relay` 留在 1.05。再往下压会抵消「评论 0.84」带进 @15 的 `doc_009#p5`。本人渠道 `party_primary` 提到 1.14，不读平台可信度。",
        "",
        "### q_001 焦点名次（1 起；空＝未进融合名单）",
        "",
        "| id | R4 名次 | 推荐名次 | 还在 @7 |",
        "|---|---:|---:|---|",
    ]
    for pid in FOCUS:
        a = r4["q001_focus"][pid]["rank"]
        b = rec["q001_focus"][pid]["rank"]
        lines.append(
            f"| `{pid}` | {a if a else '—'} | {b if b else '—'} | "
            f"{'是' if rec['q001_focus'][pid]['in7'] else '否'} |"
        )
    lines += [
        "",
        "R4 Top-7：",
        "",
    ]
    for i, pid in enumerate(r4["q001_top7"], 1):
        lines.append(f"{i}. `{pid}`")
    lines += ["", f"推荐（`{rec['name']}`）Top-7：", ""]
    for i, pid in enumerate(rec["q001_top7"], 1):
        lines.append(f"{i}. `{pid}`")
    lines += [
        "",
        "## 分题（严格 @7 / @15）",
        "",
        "| qid | l2 | R4 | 推荐 |",
        "|---|---:|---|---|",
    ]
    for bq, rq in zip(r4["questions"], rec["questions"]):
        lines.append(
            f"| {bq['qid']} | {next(q['n_l2'] for q in report['questions_meta'] if q['qid']==bq['qid'])} | "
            f"{bq['at7']['n']}/{bq['at15']['n']} | {rq['at7']['n']}/{rq['at15']['n']} |"
        )
    lines += [
        "",
        "## 网格",
        "",
        "| 点 | 轴 | @7 | @15 | 012 | 014 | 030 | 掉命中 | 改动 |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in report["grid"]:
        f = row["q001_focus"]
        def rk(pid: str) -> str:
            r = f[pid]["rank"]
            return str(r) if r else "—"
        lines.append(
            f"| `{row['name']}` | {row['axis']} | {row['sum7']} | {row['sum15']} | "
            f"{rk('doc_012#p2')} | {rk('doc_014#p1')} | {rk('doc_030#p5')} | "
            f"{'是' if row['regressed'] else '否'} | {', '.join(row['changed']) or '—'} |"
        )
    lines += [
        "",
        "## 读数",
        "",
        report["reading"],
        "",
        "## 路径",
        f"- `{ARTIFACTS / 'R5_role_weight_sweep.json'}`",
        f"- `{ARTIFACTS / 'R5_role_weight_sweep.md'}`",
        "",
    ]
    return "\n".join(lines)


def _reading(report: dict[str, Any]) -> str:
    r4 = report["r4_default"]
    bits = []
    # 哪条轴单独动了焦点名次
    for row in report["grid"]:
        if row["axis"] == "baseline" or row["regressed"]:
            continue
        moved = []
        for pid in FOCUS:
            a = r4["q001_focus"][pid]["rank"]
            b = row["q001_focus"][pid]["rank"]
            if a != b:
                moved.append(f"{pid} {a}→{b or '出名单'}")
        if moved and row["sum7"] == r4["sum7"] and row["sum15"] == r4["sum15"]:
            bits.append(f"`{row['name']}` 命中不变，名次：{'; '.join(moved)}")
        elif moved:
            bits.append(
                f"`{row['name']}` 合计 @7 {r4['sum7']}→{row['sum7']}，名次：{'; '.join(moved)}"
            )
    if not bits:
        return "各轴要么与 R4 名次相同，要么一压焦点段就丢掉已有严格命中。"
    return "；".join(bits) + "。"


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
        sub_rows = [r for r in rows_all if r["para_id"] in universe]
        sub = KgIndex(SLUG, sub_rows)
        sub.embeddings = {pid: v for pid, v in index.embeddings.items() if pid in universe}
        fused, queries, _meta, _n = _fuse_rrf(sub, question)
        pick = _as_pick(fused, queries)
        # 泄漏查融合查询，不查金标段本身
        if not leak_check({"queries": queries, "selection_used_gold": False}, gold=gold).get("ok"):
            leak_any = True
        prepared.append({
            "qid": qid,
            "question": question,
            "gold": gold,
            "universe": universe,
            "rows": sub_rows,
            "fused": fused,
            "queries": queries,
            "n_l2": len({p for _d, p in gold if p in universe}),
        })
        del pick

    # R4 默认＝不传细权重（粗角色乘子）
    q_rows = []
    for p in prepared:
        rr = rerank_source_role(p["rows"], p["fused"], dedupe=True, role_prior=True, weights=None)
        ranked = rr["ranked"]
        q_rows.append({
            "qid": p["qid"],
            "at7": _hits(ranked, p["queries"], p["gold"], p["universe"], DEFAULT_K),
            "at15": _hits(ranked, p["queries"], p["gold"], p["universe"], WIDE_K),
            "top7": [pid for pid, _ in ranked[:DEFAULT_K]],
            "focus": _focus(ranked) if p["qid"] == "q_001" else None,
            "fine_at_focus": {
                pid: {
                    "fine": rr["fine_roles"].get(pid),
                    "coarse": rr["roles"].get(pid),
                }
                for pid in FOCUS
            } if p["qid"] == "q_001" else None,
            "fine_counts": None,
        })
        if p["qid"] == "q_001":
            from collections import Counter
            counts = Counter(rr["fine_roles"].values())
            q_rows[-1]["fine_counts"] = counts
            # channel for focus from a fresh meta
            from app.kg_lab.source_role import infer_fine_role
            labels = {}
            by_id = {r["para_id"]: r for r in p["rows"]}
            for pid in FOCUS:
                row = by_id.get(pid) or {}
                info = infer_fine_role(
                    str(row.get("title") or ""),
                    str(row.get("text") or ""),
                    row.get("source_credibility"),
                )
                labels[pid] = {
                    "fine": info["role"],
                    "coarse": info["coarse"],
                    "channel": info["channel"],
                    "cred": info["credibility"],
                }
            q_rows[-1]["labels"] = labels
    q1 = next(q for q in q_rows if q["qid"] == "q_001")
    r4 = {
        "name": "r4_default",
        "axis": "baseline",
        "weights": dict(ROLE_WEIGHT),
        "changed": [],
        "n_coeff_changed": 0,
        "questions": [{k: q[k] for k in ("qid", "at7", "at15", "top7")} for q in q_rows],
        "sum7": sum(q["at7"]["n"] for q in q_rows),
        "sum15": sum(q["at15"]["n"] for q in q_rows),
        "q001_focus": q1["focus"],
        "q001_top7": q1["top7"],
        "regressed": False,
    }
    print(
        f"R4 {r4['sum7']}/{r4['sum15']} focus {r4['q001_focus']}",
        flush=True,
    )

    oned = _oned()
    oned_rows = []
    for spec in oned:
        row = _eval_point(spec, prepared)
        row["regressed"] = _regressed(row, r4)
        oned_rows.append(row)
        print(
            f"  {row['name']} {row['sum7']}/{row['sum15']} "
            f"regressed={row['regressed']} focus={ {k: v['rank'] for k, v in row['q001_focus'].items()} }",
            flush=True,
        )
    combos = _combos(oned_rows, r4)
    combo_rows = []
    for spec in combos:
        row = _eval_point(spec, prepared)
        row["regressed"] = _regressed(row, r4)
        combo_rows.append(row)
        print(
            f"  {row['name']} {row['sum7']}/{row['sum15']} regressed={row['regressed']}",
            flush=True,
        )

    # r4_mapped 与真 R4 是否同一套命中
    mapped = next(r for r in oned_rows if r["name"] == "r4_mapped")
    mapped_same = (
        mapped["sum7"] == r4["sum7"]
        and mapped["sum15"] == r4["sum15"]
        and mapped["q001_top7"] == r4["q001_top7"]
    )

    grid = [r4] + oned_rows + combo_rows
    rec = _recommend(grid, r4)
    # 推荐行的 weights：若维持 R4，写出粗乘子对照表仍用等价细表，并标明 keep
    if rec["keep_r4"]:
        rec_weights = dict(R4_FINE_EQUIV)
        rec_sum7, rec_sum15 = r4["sum7"], r4["sum15"]
        rec_focus, rec_top7 = r4["q001_focus"], r4["q001_top7"]
        rec_questions = r4["questions"]
        rec_name = "r4_default"
    else:
        rec_weights = rec["row"]["weights"]
        rec_sum7, rec_sum15 = rec["row"]["sum7"], rec["row"]["sum15"]
        rec_focus, rec_top7 = rec["row"]["q001_focus"], rec["row"]["q001_top7"]
        rec_questions = rec["row"]["questions"]
        rec_name = rec["name"]

    fine_counts = sorted(q1["fine_counts"].items(), key=lambda kv: (-kv[1], str(kv[0])))
    report = {
        "ticket": "R5-role-weight-sweep",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "causal_expand": False,
        },
        "leak_any_bad": leak_any,
        "mapped_matches_r4_top7": mapped_same,
        "q001_fine_counts": fine_counts,
        "focus_labels": q1["labels"],
        "questions_meta": [
            {"qid": p["qid"], "n_l2": p["n_l2"], "question": p["question"]}
            for p in prepared
        ],
        "r4_default": r4,
        "grid": [
            {
                "name": r["name"],
                "axis": r["axis"],
                "sum7": r["sum7"],
                "sum15": r["sum15"],
                "regressed": r["regressed"],
                "changed": r["changed"],
                "q001_focus": r["q001_focus"],
                "q001_top7": r["q001_top7"],
                "weights": r["weights"],
                "questions": r["questions"],
            }
            for r in grid
        ],
        "n_oned": len(oned),
        "n_combo": len(combos),
        "recommendation": {
            "name": rec_name,
            "keep_r4": rec["keep_r4"],
            "why": rec["why"],
            "weights": rec_weights,
            "sum7": rec_sum7,
            "sum15": rec_sum15,
            "q001_focus": rec_focus,
            "q001_top7": rec_top7,
            "questions": rec_questions,
        },
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    report["reading"] = _reading(report)
    art = ARTIFACTS
    art.mkdir(parents=True, exist_ok=True)
    jp = art / "R5_role_weight_sweep.json"
    mp = art / "R5_role_weight_sweep.md"
    jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    mp.write_text(_markdown(report), encoding="utf-8")
    print(f"wrote {mp}", flush=True)
    print(f"recommend {rec_name} keep_r4={rec['keep_r4']} {rec['why']}", flush=True)
    return 0 if not leak_any else 3


if __name__ == "__main__":
    raise SystemExit(main())
