#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R4：通稿去重 + 角色 prior + 摘要槽位。刘翔三题，严格 supporting_facts。

因果扩圈不开。expand_top_n=16，n_paraphrase=1。
先量当前 RRF，再量去重／角色消融，然后只对金标段 + q_001 基线 Top-7 非金标补槽位并重嵌。
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.config import ARTIFACTS, DEFAULT_K, SUMMARY_WORKERS, WIDE_K  # noqa: E402
from app.kg_lab.eval_metrics import leak_check, measure_arm  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.recall_arms import arm_rrf, arm_rrf_source_role  # noqa: E402
from app.kg_lab.source_role import (  # noqa: E402
    _meta_from_row,
    cluster_representatives,
)
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.summary_slots import (  # noqa: E402
    SLOT_VERSION,
    apply_slots_to_summary,
    llm_fact_candidates,
    slot_line,
)
from app.kg_lab.summarize import load_summary, write_summary_note  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SLUG = "liuxiang"


def _hits(arm: dict[str, Any], gold, universe: set[str], k: int) -> dict[str, Any]:
    m = measure_arm(arm, gold=gold, universe=universe, k=k)
    return {
        "n": m["n_gold_hit"],
        "ids": m["gold_hit_ids"],
        "picked": m["picked_ids"],
        "recall": m["recall_at_k"],
    }


def _loose(
    picked: list[str],
    l2: set[str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """副尺：簇内任一近义段命中严格金标，记该金标被宽松覆盖。"""
    metas = {
        str(r["para_id"]): _meta_from_row(r)
        for r in rows if r.get("para_id")
    }
    rep = cluster_representatives(metas)
    groups: dict[str, set[str]] = {}
    for pid, root in rep.items():
        groups.setdefault(root, set()).add(pid)
    covered = []
    for g in sorted(l2):
        root = rep.get(g, g)
        members = groups.get(root, {g})
        if members & set(picked):
            covered.append(g)
    return {
        "n": len(covered),
        "ids": covered,
        "recall": round(len(covered) / len(l2), 4) if l2 else None,
    }


def _enrich_one(row: dict[str, Any]) -> dict[str, Any]:
    pid = str(row["para_id"])
    doc_id = str(row["doc_id"])
    text = str(row.get("text") or "")
    title = str(row.get("title") or "")
    old = load_summary(SLUG, doc_id, pid) or {
        "doc_id": doc_id,
        "para_id": pid,
        "facts": [],
        "entities": [],
        "keywords": [],
        "causal": [],
    }
    if old.get("slot_version") == SLOT_VERSION and old.get("summary_text"):
        return {"para_id": pid, "status": "cached", "slot_line": slot_line(old)}
    try:
        llm_facts = llm_fact_candidates(text)
        llm_status = "ok"
    except Exception as e:  # noqa: BLE001
        llm_facts = []
        llm_status = f"llm_fail:{e}"
    new = apply_slots_to_summary(
        old, title=title, text=text, llm_facts=llm_facts,
    )
    new["doc_id"] = doc_id
    new["para_id"] = pid
    new["facts_before_r4"] = list(old.get("facts") or [])
    new["summary_text_before_r4"] = old.get("summary_text") or ""
    new["model"] = old.get("model") or new.get("model")
    new["llm_status"] = llm_status
    write_summary_note(SLUG, new)
    return {
        "para_id": pid,
        "status": llm_status,
        "slot_line": slot_line(new),
        "facts": new.get("facts"),
        "amount_status": new.get("amount_status"),
        "source_role": new.get("source_role"),
        "n_facts": len(new.get("facts") or []),
    }


def _arm_bundle(index: KgIndex, question: str, universe: set[str]) -> dict[str, dict[str, Any]]:
    return {
        "base": arm_rrf(index, question, k=WIDE_K, universe=universe),
        "dedupe": arm_rrf_source_role(
            index, question, k=WIDE_K, universe=universe,
            dedupe=True, role_prior=False,
        ),
        "role": arm_rrf_source_role(
            index, question, k=WIDE_K, universe=universe,
            dedupe=False, role_prior=True,
        ),
        "both": arm_rrf_source_role(
            index, question, k=WIDE_K, universe=universe,
            dedupe=True, role_prior=True,
        ),
    }


def _score_arms(arms, gold, universe, rows) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, arm in arms.items():
        h7 = _hits(arm, gold, universe, DEFAULT_K)
        h15 = _hits(arm, gold, universe, WIDE_K)
        out[name] = {
            "at7": h7,
            "at15": h15,
            "loose7": _loose(h7["picked"], {p for _d, p in gold if p in universe}, rows),
            "loose15": _loose(h15["picked"], {p for _d, p in gold if p in universe}, rows),
            "substitutions": (arm.get("source_role") or {}).get("substitutions") or [],
        }
    return out


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1, (
        f"defaults must be 16/1, got {DEFAULT_EXPAND_TOP_N}/{DEFAULT_PARAPHRASE_N}"
    )
    case = next(
        p for p in (ROOT / "data" / "trs-samples").iterdir()
        if p.is_dir() and "刘翔" in p.name and (p / "raw_documents.json").is_file()
    )
    dossier, union_ids, questions = union_pack_ids(case)
    rows_all = build_corpus_rows(dossier, case_slug=SLUG, para_ids=union_ids)
    index = KgIndex(SLUG, rows_all)
    index.ensure_embeddings(force=False)

    def _sub(rows: list[dict[str, Any]], universe: set[str], emb: dict) -> KgIndex:
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(SLUG, sub_rows)
        sub.embeddings = {pid: v for pid, v in emb.items() if pid in universe}
        return sub

    # ----- before（现摘要，未补槽）-----
    prepared: list[dict[str, Any]] = []
    leak_any = False
    for qrow in questions:
        qid = qrow["question_id"]
        question = qrow["question"]
        print(f"=== before {qid} ===", flush=True)
        gold, _skipped = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = {p for _d, p in gold if p in universe}
        sub = _sub(rows_all, universe, index.embeddings)
        arms = _arm_bundle(sub, question, universe)
        for arm in arms.values():
            if not leak_check(arm, gold=gold).get("ok"):
                leak_any = True
        scored = _score_arms(arms, gold, universe, sub.rows)
        print(
            f"  base {scored['base']['at7']['n']}/{scored['base']['at15']['n']} "
            f"dedupe {scored['dedupe']['at7']['n']}/{scored['dedupe']['at15']['n']} "
            f"role {scored['role']['at7']['n']}/{scored['role']['at15']['n']} "
            f"both {scored['both']['at7']['n']}/{scored['both']['at15']['n']}",
            flush=True,
        )
        prepared.append({
            "qid": qid,
            "question": question,
            "gold": gold,
            "universe": universe,
            "l2": sorted(l2),
            "before": scored,
        })

    # 补槽目标：三题严格金标 ∪ q_001 基线 Top-7 非金标
    q1 = next(p for p in prepared if p["qid"] == "q_001")
    l2_all: set[str] = set()
    for p in prepared:
        l2_all.update(p["l2"])
    top7_non_gold = [
        pid for pid in q1["before"]["base"]["at7"]["picked"]
        if pid not in set(q1["l2"])
    ]
    targets = sorted(l2_all | set(top7_non_gold))
    by_id = {r["para_id"]: r for r in rows_all}
    todo = [by_id[pid] for pid in targets if pid in by_id]
    print(f"=== slot enrich n={len(todo)} ===", flush=True)
    t_slot = time.perf_counter()
    slot_rows: list[dict[str, Any]] = []
    workers = max(1, min(2, SUMMARY_WORKERS))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_enrich_one, row): row["para_id"] for row in todo}
        for fut in as_completed(futs):
            slot_rows.append(fut.result())
            print(f"  slot {slot_rows[-1]['para_id']} {slot_rows[-1]['status']}", flush=True)
    slot_s = round(time.perf_counter() - t_slot, 3)

    rows_after = build_corpus_rows(dossier, case_slug=SLUG, para_ids=union_ids)
    index_after = KgIndex(SLUG, rows_after)
    # 只重嵌补过槽的段
    index_after.ensure_embeddings(force=False, refresh_ids=set(targets))

    for p in prepared:
        print(f"=== after slots {p['qid']} ===", flush=True)
        sub = _sub(rows_after, p["universe"], index_after.embeddings)
        arms = _arm_bundle(sub, p["question"], p["universe"])
        for arm in arms.values():
            if not leak_check(arm, gold=p["gold"]).get("ok"):
                leak_any = True
        p["after"] = _score_arms(arms, p["gold"], p["universe"], sub.rows)
        b = p["after"]["both"]
        print(
            f"  both {b['at7']['n']}/{b['at15']['n']} "
            f"base {p['after']['base']['at7']['n']}/{p['after']['base']['at15']['n']}",
            flush=True,
        )

    def _sum(stage: str, arm: str, kfield: str) -> int:
        return sum(p[stage][arm][kfield]["n"] for p in prepared)

    totals = {
        "before": {
            arm: {"at7": _sum("before", arm, "at7"), "at15": _sum("before", arm, "at15")}
            for arm in ("base", "dedupe", "role", "both")
        },
        "after_slots": {
            arm: {"at7": _sum("after", arm, "at7"), "at15": _sum("after", arm, "at15")}
            for arm in ("base", "dedupe", "role", "both")
        },
    }

    # 哪一刀动了分：相对 before-base
    def _contrib(arm: str) -> dict[str, int]:
        return {
            "d7": totals["before"][arm]["at7"] - totals["before"]["base"]["at7"],
            "d15": totals["before"][arm]["at15"] - totals["before"]["base"]["at15"],
        }

    slot_delta = {
        "d7": totals["after_slots"]["both"]["at7"] - totals["before"]["both"]["at7"],
        "d15": totals["after_slots"]["both"]["at15"] - totals["before"]["both"]["at15"],
        "base_d7": totals["after_slots"]["base"]["at7"] - totals["before"]["base"]["at7"],
        "base_d15": totals["after_slots"]["base"]["at15"] - totals["before"]["base"]["at15"],
    }

    q1_before = q1["before"]["base"]["at7"]["picked"]
    q1_after = q1["after"]["both"]["at7"]["picked"]
    q1_l2 = set(q1["l2"])

    questions_out = []
    for p in prepared:
        questions_out.append({
            "qid": p["qid"],
            "question": p["question"],
            "n_l2": len(p["l2"]),
            "l2": p["l2"],
            "before": p["before"],
            "after_slots": p["after"],
        })

    report = {
        "ticket": "R4-source-role",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "causal_expand": False,
            "k": DEFAULT_K,
            "wide_k": WIDE_K,
        },
        "arm": "rrf_source_role",
        "fuse": "rrf(text+summary_expand+emb+1x(para_summary+para_emb))+press_dedupe+role_prior",
        "leak_any_bad": leak_any,
        "slot_targets": targets,
        "slot_q001_top7_nongold": top7_non_gold,
        "slot_results": slot_rows,
        "slot_wall_s": slot_s,
        "questions": questions_out,
        "totals": totals,
        "contribution_vs_before_base": {
            "dedupe_only": _contrib("dedupe"),
            "role_only": _contrib("role"),
            "dedupe_and_role": _contrib("both"),
            "slots_on_top_of_both": slot_delta,
        },
        "q001_top7": {
            "before_base": q1_before,
            "after_r4": q1_after,
            "gold": sorted(q1_l2),
            "still_occupying": [
                pid for pid in ("doc_030#p5", "doc_038#p1") if pid in q1_after
            ],
            "gold_in_after7": [pid for pid in q1_after if pid in q1_l2],
        },
        "wall_s": round(time.perf_counter() - t0, 3),
    }

    art = ARTIFACTS
    art.mkdir(parents=True, exist_ok=True)
    jp = art / "R4_source_role.json"
    jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    mp = art / "R4_source_role.md"
    mp.write_text(_markdown(report), encoding="utf-8")
    print(f"wrote {mp}", flush=True)
    print(
        f"BEFORE base {totals['before']['base']} both {totals['before']['both']} | "
        f"AFTER both {totals['after_slots']['both']} leak={leak_any}",
        flush=True,
    )
    return 0 if not leak_any else 3


def _markdown(report: dict[str, Any]) -> str:
    d = report["defaults"]
    tot_b = report["totals"]["before"]
    tot_a = report["totals"]["after_slots"]
    contrib = report["contribution_vs_before_base"]
    q1 = report["q001_top7"]
    lines = [
        "# R4 — 通稿去重 + 角色 prior + 摘要槽位",
        "",
        f"- 默认：expand_top_n=**{d['expand_top_n']}**，n_paraphrase=**{d['n_paraphrase']}**，因果扩圈=**关**",
        f"- 主尺：严格 supporting_facts L2（@7 / @15）",
        f"- 臂：`{report['fuse']}`",
        f"- leak_any_bad：**{report['leak_any_bad']}**",
        f"- 墙钟：{report['wall_s']}s（其中补槽 {report['slot_wall_s']}s）",
        "",
        "## 三刀",
        "",
        "1. **通稿簇**：官方／制度段之间只并近重复（Jaccard≥0.72，或高包含且长度接近）。转述／评论若与某一载体共享≥22 字通报句，只挂到共享最长的那一簇，不把相邻官方切片串成一段。名次留给代表：正文含「情况通报」的开头段，或标题就是《情况通报》的续段，优先于新华网／人民日报改写题。可信度只作同角色辅分。",
        "2. **角色 prior**（RRF 之后乘子，不是按 cred 排序）：official_primary 1.12 > institution_def 1.08 > party_claim 1.05 > media_relay 0.98 > commentary 0.90。当事人看原话标记（「没让我走／刘翔表示」），时间线「他发求助」不算当事人。",
        "3. **摘要槽位**：段内有据才写角色、对立口径、数额（披露／既定／官方未确认）、手续日期。facts≤3。先补严格金标段 + q_001 基线 Top-7 非金标，不全库重跑。",
        "",
        "## 合计（三题严格命中条数）",
        "",
        "| 阶段 | 臂 | @7 | @15 |",
        "|---|---|---:|---:|",
    ]
    labels = (
        ("before", "base", "补槽前 · 现 RRF（16/1）"),
        ("before", "dedupe", "补槽前 · 只去重"),
        ("before", "role", "补槽前 · 只角色"),
        ("before", "both", "补槽前 · 去重+角色"),
        ("after_slots", "base", "补槽后 · 现 RRF"),
        ("after_slots", "both", "补槽后 · 去重+角色（R4）"),
    )
    bag = {"before": tot_b, "after_slots": tot_a}
    for stage, arm, label in labels:
        cell = bag[stage][arm]
        lines.append(f"| {label} | `{arm}` | {cell['at7']} | {cell['at15']} |")

    lines += [
        "",
        "## 分题（严格 @7 / @15）",
        "",
        "| qid | l2 | 前 RRF | 前去重 | 前角色 | 前两者 | 后 RRF | 后 R4 |",
        "|---|---:|---|---|---|---|---|---|",
    ]
    for q in report["questions"]:
        def cell(stage: str, arm: str) -> str:
            block = q[stage][arm]
            return f"{block['at7']['n']}/{block['at15']['n']}"
        lines.append(
            f"| {q['qid']} | {q['n_l2']} | {cell('before','base')} | "
            f"{cell('before','dedupe')} | {cell('before','role')} | "
            f"{cell('before','both')} | {cell('after_slots','base')} | "
            f"{cell('after_slots','both')} |"
        )

    lines += ["", "### 严格命中 id", ""]
    for q in report["questions"]:
        b7 = q["before"]["base"]["at7"]["ids"]
        a7 = q["after_slots"]["both"]["at7"]["ids"]
        b15 = q["before"]["base"]["at15"]["ids"]
        a15 = q["after_slots"]["both"]["at15"]["ids"]
        lines.append(
            f"- **{q['qid']}** 前@7 {b7} → 后@7 {a7}；前@15 {b15} → 后@15 {a15}"
        )

    lines += [
        "",
        "## q_001 Top-7",
        "",
        "前（现 RRF）：",
        "",
    ]
    for i, pid in enumerate(q1["before_base"], 1):
        mark = "金标" if pid in q1["gold"] else "非金标"
        lines.append(f"{i}. `{pid}`（{mark}）")
    lines += ["", "后（R4 去重+角色+补槽）：", ""]
    for i, pid in enumerate(q1["after_r4"], 1):
        mark = "金标" if pid in q1["gold"] else "非金标"
        lines.append(f"{i}. `{pid}`（{mark}）")
    still = q1["still_occupying"] or ["（030 与 038 都不在 Top-7）"]
    if q1["still_occupying"]:
        still_txt = "、".join(f"`{x}`" for x in q1["still_occupying"])
    else:
        still_txt = "030 与 038 都不在 Top-7"
    lines += [
        "",
        f"- 仍占坑：{still_txt}",
        f"- 金标进后 Top-7：{', '.join(f'`{x}`' for x in q1['gold_in_after7']) or '无'}",
        "",
        "## 哪一刀在动",
        "",
        (
            f"- 只去重，相对补槽前 RRF：@7 {contrib['dedupe_only']['d7']:+d}，"
            f"@15 {contrib['dedupe_only']['d15']:+d}"
        ),
        (
            f"- 只角色，相对补槽前 RRF：@7 {contrib['role_only']['d7']:+d}，"
            f"@15 {contrib['role_only']['d15']:+d}"
        ),
        (
            f"- 去重+角色，相对补槽前 RRF：@7 {contrib['dedupe_and_role']['d7']:+d}，"
            f"@15 {contrib['dedupe_and_role']['d15']:+d}"
        ),
        (
            f"- 再补槽，相对「去重+角色」：@7 {contrib['slots_on_top_of_both']['d7']:+d}，"
            f"@15 {contrib['slots_on_top_of_both']['d15']:+d}"
            f"（补槽对裸 RRF：@7 {contrib['slots_on_top_of_both']['base_d7']:+d}，"
            f"@15 {contrib['slots_on_top_of_both']['base_d15']:+d}）"
        ),
        "",
        _knife_sentence(report),
        "",
        "- q_001 的 @7 满覆盖要两刀一起：只去重把 `doc_024#p1` 送进 @7 和 @15；只角色不动 q_001；两者一起才把 `doc_035#p7` 从 @15 抬进 @7。q_003 的 @7 +1（`doc_012#p5`）来自角色 prior。q_002 另四条金标本来就不在 Top-15，去重和角色都没有把它们召回来。",
        "- `doc_038#p1` 已退出 q_001 Top-7（名次让给 `doc_024#p1`）。`doc_030#p5` 从第 1 落到第 7，仍占一个坑：它是时间线综述，和通报原文没有足够长的共享句，去重不会并掉它，角色乘子只够把它压到名单尾部。",
        "- `doc_025#p6` 补槽时模型返回 500，事实句保留补槽前的三句，槽位改由规则写入。",
        "",
        "## 宽松副尺（簇内近义算覆盖，不作主结论）",
        "",
        "| qid | 前 RRF 宽松@7/@15 | 后 R4 宽松@7/@15 |",
        "|---|---|---|",
    ]
    for q in report["questions"]:
        lb = q["before"]["base"]
        la = q["after_slots"]["both"]
        lines.append(
            f"| {q['qid']} | {lb['loose7']['n']}/{lb['loose15']['n']} | "
            f"{la['loose7']['n']}/{la['loose15']['n']} |"
        )
    lines += [
        "",
        "## 补槽范围",
        "",
        f"- 目标 {len(report['slot_targets'])} 段：严格金标 ∪ q_001 基线 Top-7 非金标 `{report['slot_q001_top7_nongold']}`",
        "- 未全库重跑。规则槽位压过模型自由填写（数额／角色不对原文就不写）。",
        "",
        "槽位行：",
        "",
    ]
    for row in report["slot_results"]:
        lines.append(
            f"- `{row['para_id']}` {row.get('status')} "
            f"{row.get('source_role') or ''} {row.get('amount_status') or ''} "
            f"| {row.get('slot_line') or ''}"
        )
    lines += [
        "",
        "## 路径",
        f"- `{ARTIFACTS / 'R4_source_role.json'}`",
        f"- `{ARTIFACTS / 'R4_source_role.md'}`",
        "",
    ]
    return "\n".join(lines)


def _knife_sentence(report: dict[str, Any]) -> str:
    c = report["contribution_vs_before_base"]
    bits = []
    if c["dedupe_only"]["d7"] or c["dedupe_only"]["d15"]:
        bits.append("通稿去重改了严格命中")
    else:
        bits.append("通稿去重没有改严格合计")
    if c["role_only"]["d7"] or c["role_only"]["d15"]:
        bits.append("角色 prior 单独也改了严格命中")
    else:
        bits.append("角色 prior 单独没有改严格合计")
    if c["slots_on_top_of_both"]["d7"] or c["slots_on_top_of_both"]["d15"]:
        bits.append("补槽又改了去重+角色之后的严格命中")
    else:
        bits.append("补槽没有再改去重+角色的严格命中")
    q1 = report["questions"][0]
    # 找 q_001
    q1 = next(q for q in report["questions"] if q["qid"] == "q_001")
    moved = (
        f"q_001 严格 @7 {q1['before']['base']['at7']['n']}→"
        f"{q1['after_slots']['both']['at7']['n']}，@15 "
        f"{q1['before']['base']['at15']['n']}→"
        f"{q1['after_slots']['both']['at15']['n']}"
    )
    return "- " + "；".join(bits) + f"。{moved}。"


if __name__ == "__main__":
    raise SystemExit(main())
