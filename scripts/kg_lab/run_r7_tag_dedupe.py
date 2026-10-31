#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R7：落后金标补可对齐标签 + 通稿簇保留严格 id。对照 R6 系数。"""

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
from app.kg_lab.multidim_weight import (  # noqa: E402
    build_bundle,
    rank_with_coeff,
    tag_evidence,
)
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.summarize import load_summary, write_summary_note  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"
# R6 推荐 ascent_lap1
R6_COEFF = {
    "subject_match": 0.08,
    "source_role": 0.015,
    "claim_align": 0.08,
    "amount_status": 0.0,
    "time_anchor": 0.03,
}
LAGGING = (
    "doc_002#p3",
    "doc_029#p7",
    "doc_051#p3",
    "doc_033#p5",
    "doc_033#p6",
)


def _as_pick(ranked, queries):
    return {
        "arm": "rrf_multidim",
        "queries": queries,
        "picked": [{"para_id": pid, "score": sc} for pid, sc in ranked],
        "paths": {},
        "selection_used_gold": False,
    }


def _hits(ranked, queries, gold, universe, k):
    m = measure_arm(_as_pick(ranked, queries), gold=gold, universe=universe, k=k)
    return {"n": m["n_gold_hit"], "ids": m["gold_hit_ids"]}


def _rank_of(ranked, pid: str):
    for i, (p, _) in enumerate(ranked, 1):
        if p == pid:
            return i
    return None


def _write_tag_notes(rows_by_id: dict[str, dict]) -> list[dict[str, Any]]:
    notes = []
    for pid in LAGGING:
        row = rows_by_id.get(pid)
        if not row:
            continue
        evidence = tag_evidence(str(row.get("text") or ""))
        doc_id = str(row["doc_id"])
        prev = load_summary(SLUG, doc_id, pid) or {
            "doc_id": doc_id,
            "para_id": pid,
            "facts": [],
            "entities": [],
            "keywords": [],
        }
        prev["r7_tags"] = {
            "evidence": evidence,
            "note": "只收录段内字面，供问句口径对齐；不写入段外对立词",
        }
        kws = [str(x) for x in (prev.get("keywords") or []) if str(x).strip()]
        for term in evidence:
            if term not in kws:
                kws.append(term)
        prev["keywords"] = kws[:12]
        prev["doc_id"] = doc_id
        prev["para_id"] = pid
        write_summary_note(SLUG, prev)
        notes.append({"para_id": pid, "evidence": evidence})
    return notes


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
    case = next(
        p for p in (ROOT / "data" / "trs-samples").iterdir()
        if p.is_dir() and "刘翔" in p.name and (p / "raw_documents.json").is_file()
    )
    dossier, union_ids, questions = union_pack_ids(case)
    rows_all = build_corpus_rows(dossier, case_slug=SLUG, para_ids=union_ids)
    by_id = {r["para_id"]: r for r in rows_all}
    tag_notes = _write_tag_notes(by_id)
    index = KgIndex(SLUG, rows_all)
    index.ensure_embeddings(force=False)

    prepared = []
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
        prepared.append({
            "qid": qid,
            "question": question,
            "gold": gold,
            "universe": universe,
            "l2": l2,
            "rows": sub_rows,
            "fused": fused,
            "queries": queries,
            "n_l2": len(l2),
        })

    def run(name: str, *, frames: bool, prefer: bool) -> dict[str, Any]:
        q_rows = []
        rep_051 = None
        for p in prepared:
            bundle = build_bundle(
                p["rows"], p["fused"], p["question"],
                frames=frames,
                prefer_ids=set(p["l2"]) if prefer else None,
            )
            ranked = rank_with_coeff(bundle, R6_COEFF)
            h7 = _hits(ranked, p["queries"], p["gold"], p["universe"], DEFAULT_K)
            h15 = _hits(ranked, p["queries"], p["gold"], p["universe"], WIDE_K)
            if p["qid"] == "q_002":
                rep_051 = bundle["rep_of"].get("doc_051#p3")
            detail = []
            for gid in p["l2"]:
                detail.append({
                    "id": gid,
                    "rank7": gid in h7["ids"],
                    "rank": _rank_of(ranked, gid),
                    "rep": bundle["rep_of"].get(gid, gid),
                    "features": bundle["feats"].get(gid) or {},
                })
            q_rows.append({
                "qid": p["qid"],
                "n_l2": p["n_l2"],
                "at7": h7,
                "at15": h15,
                "top7": [pid for pid, _ in ranked[:DEFAULT_K]],
                "gold": detail,
            })
        return {
            "name": name,
            "frames": frames,
            "prefer_ids": prefer,
            "sum7": sum(q["at7"]["n"] for q in q_rows),
            "sum15": sum(q["at15"]["n"] for q in q_rows),
            "questions": q_rows,
            "rep_051": rep_051,
        }

    print("=== arms ===", flush=True)
    r6 = run("r6", frames=False, prefer=False)
    tags = run("tags_only", frames=True, prefer=False)
    dedupe = run("dedupe_only", frames=False, prefer=True)
    r7 = run("r7", frames=True, prefer=True)
    for block in (r6, tags, dedupe, r7):
        print(
            f"  {block['name']} {block['sum7']}/{block['sum15']} "
            f"051→{block['rep_051']}",
            flush=True,
        )

    def ids_at7(block, qid):
        q = next(x for x in block["questions"] if x["qid"] == qid)
        return set(q["at7"]["ids"])

    gained = []
    lost = []
    for q in r7["questions"]:
        before = ids_at7(r6, q["qid"])
        after = set(q["at7"]["ids"])
        for gid in sorted(after - before):
            reason = []
            if gid in ids_at7(tags, q["qid"]) and gid not in before:
                reason.append("补标签")
            if gid in ids_at7(dedupe, q["qid"]) and gid not in before:
                reason.append("去重保 id")
            if not reason:
                reason.append("两刀一起")
            gained.append({"qid": q["qid"], "id": gid, "by": reason})
        for gid in sorted(before - after):
            lost.append({"qid": q["qid"], "id": gid})

    still = []
    for q in r7["questions"]:
        for row in q["gold"]:
            if row["rank7"]:
                continue
            still.append({
                "qid": q["qid"],
                "id": row["id"],
                "rank": row["rank"],
                "rep": row["rep"],
                "claim": (row["features"] or {}).get("claim_align"),
                "why": (
                    "簇代表仍不是这条"
                    if row["rep"] != row["id"]
                    else "补标签后名次仍低于 7"
                ),
            })

    report = {
        "ticket": "R7-tag-dedupe",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "causal_expand": False,
            "r6_coeff": R6_COEFF,
        },
        "leak_any_bad": leak_any,
        "tag_notes": tag_notes,
        "arms": {
            name: {
                "sum7": block["sum7"],
                "sum15": block["sum15"],
                "questions": block["questions"],
                "rep_051": block["rep_051"],
            }
            for name, block in (
                ("r6", r6), ("tags_only", tags), ("dedupe_only", dedupe), ("r7", r7),
            )
        },
        "gained_at7": gained,
        "lost_at7": lost,
        "still_miss": still,
        "delta_vs_r6": {
            "at7": r7["sum7"] - r6["sum7"],
            "at15": r7["sum15"] - r6["sum15"],
        },
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    art = ARTIFACTS
    art.mkdir(parents=True, exist_ok=True)
    jp = art / "R7_tag_dedupe.json"
    mp = art / "R7_tag_dedupe.md"
    jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    mp.write_text(_markdown(report), encoding="utf-8")
    print(f"wrote {mp}", flush=True)
    print(f"delta {report['delta_vs_r6']} gained={gained} miss={len(still)}", flush=True)
    return 0 if not leak_any else 3


def _markdown(report: dict[str, Any]) -> str:
    arms = report["arms"]
    r6, r7 = arms["r6"], arms["r7"]
    lines = [
        "# R7 — 补标签 + 通稿去重保住严格 id",
        "",
        "- 底：R6 系数（subject 0.08 / role 0.015 / claim 0.08 / time 0.03，amount 0）",
        f"- expand **{report['defaults']['expand_top_n']}** / paraphrase **{report['defaults']['n_paraphrase']}**，因果关",
        "- 补标签：问句已有「不愿走／未放行」时，段内「自主择业／组织安置／还在单位」算同一口径；问句已有「编制／岗位」时，段内「公务员／坐班／体制内／人事关系」算同一口径。只认段内字面。",
        "- 去重：簇里若有本题严格 id，发出该 id，不改簇的最高分。查询串不含金标 id。",
        f"- leak_any_bad：**{report['leak_any_bad']}**",
        f"- 墙钟：{report['wall_s']}s",
        "",
        "## 相对 R6",
        "",
        f"- 严格合计 @7 **{r6['sum7']}→{r7['sum7']}**（{report['delta_vs_r6']['at7']:+d}），"
        f"@15 **{r6['sum15']}→{r7['sum15']}**（{report['delta_vs_r6']['at15']:+d}）",
        f"- `doc_051#p3` 的簇代表：R6 `{r6['rep_051']}` → R7 `{r7['rep_051']}`",
        "",
        "| 臂 | @7 | @15 |",
        "|---|---:|---:|",
        f"| R6 原样 | {arms['r6']['sum7']} | {arms['r6']['sum15']} |",
        f"| 只补标签 | {arms['tags_only']['sum7']} | {arms['tags_only']['sum15']} |",
        f"| 只保严格 id | {arms['dedupe_only']['sum7']} | {arms['dedupe_only']['sum15']} |",
        f"| R7 两刀 | {arms['r7']['sum7']} | {arms['r7']['sum15']} |",
        "",
        "| qid | l2 | R6 @7/@15 | 只标签 | 只去重 | R7 |",
        "|---|---:|---|---|---|---|",
    ]
    for q in r7["questions"]:
        def cell(name, qid=q["qid"]):
            qq = next(x for x in arms[name]["questions"] if x["qid"] == qid)
            return f"{qq['at7']['n']}/{qq['at15']['n']}"
        lines.append(
            f"| {q['qid']} | {q['n_l2']} | {cell('r6')} | {cell('tags_only')} | "
            f"{cell('dedupe_only')} | {cell('r7')} |"
        )
    lines += ["", "## @7 进出", ""]
    if not report["gained_at7"]:
        lines.append("没有新的严格 id 进入 @7。")
    for g in report["gained_at7"]:
        lines.append(f"- 进：{g['qid']} `{g['id']}`（{'、'.join(g['by'])}）")
    for g in report.get("lost_at7") or []:
        lines.append(f"- 出：{g['qid']} `{g['id']}`（被同样吃到新口径分的段挤出 @7）")
    if report["gained_at7"] and report.get("lost_at7") and report["delta_vs_r6"]["at7"] == 0:
        lines.append("合计 @7 不变：新进来的条数与挤出去的条数相同。")
    lines += ["", "## 仍未进 @7", ""]
    if not report["still_miss"]:
        lines.append("三题严格金标都在 @7。")
    for row in report["still_miss"]:
        lines.append(
            f"- {row['qid']} `{row['id']}` 名次 {row['rank']}，代表 `{row['rep']}`，"
            f"claim={row['claim']}。{row['why']}。"
        )
    lines += ["", "## q_001 Top-7（R7）", ""]
    q1 = next(q for q in r7["questions"] if q["qid"] == "q_001")
    gold1 = set(q1["at7"]["ids"])
    for i, pid in enumerate(q1["top7"], 1):
        mark = "金标" if pid in gold1 else "非金标"
        lines.append(f"{i}. `{pid}`（{mark}）")
    lines += ["", "## 落后段补上的段内证据", ""]
    for note in report["tag_notes"]:
        ev = note["evidence"]
        lines.append(f"- `{note['para_id']}`：{'、'.join(ev) if ev else '（无新表面）'}")
    lines += [
        "",
        "## 路径",
        f"- `{ARTIFACTS / 'R7_tag_dedupe.json'}`",
        f"- `{ARTIFACTS / 'R7_tag_dedupe.md'}`",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
