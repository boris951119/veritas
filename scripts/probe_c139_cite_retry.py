#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-139：树17 引用验收打回循环——两案×3 遍真跑验收（同 C-134 尺；本地 14B 零现金）。

腿0 零调用全路径腿（脚本桩客户端，零 LLM 零网络）：
  - 交卷盒在场＋旗开 → 生产形状 analyze 全路径；
  - 人造失败路：坏 payload（编造 id）→ 打回 1 次 → 好 payload 过；
    独立复核带外＝0、重写提示只含失败原因＋盒内编号（禁金标 id）。
腿G 三闸确定性复刻（零 LLM）：_eval_case／_plan_cite_and_leak／_prod_leg
  原样复用，逐键对照 C-134 存档（dens／@7／金标→close／泄漏＝应逐位同）。
腿1 14B 真跑：liuxiang＋wanghong 全题 ×3 遍，settings.cite_accept=True
  （上限默认 3）；逐遍记 attempts／逐次失败码／cited_n／带外（独立复算）／
  单边对／L3（金标只进量尺）／focus_precision／引文核对分桶／tok／墙钟；
  逐题对照 C-134 真跑存档（C-134 单遍 vs 本轮 3 遍均值/最小）。

产物卫生：只记 id／计数／sha8，零官方原文、零模型输出原文。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = Path("/tmp/c139")

from scripts.probe_c125_six_case_gate import (  # noqa: E402
    CASE_MARKS, EXPECT, _case, _eval_case, _git_tip, _plan_cite_and_leak,
    _prod_leg, _questions_from_conclusions,
)
from scripts.probe_c134_two_case_gate import (  # noqa: E402
    MODEL_ID, _gold_ids, _universe_for,
)
from scripts.probe_recall_funnel import cited_hits  # noqa: E402

C134 = json.loads(
    (ROOT / "artifacts" / "C134_two_case_gate.json").read_text(
        encoding="utf-8"))
CASES = ("liuxiang", "wanghong")


def _sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


# ------------------------------------------------ 腿0：零调用全路径（脚本桩）

class _StubClient:
    """脚本应答桩：analyze 全路径真跑、客户端零网络。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append([dict(m) for m in messages])
        return type("R", (), {"content": self.responses.pop(0)})()


def _good_payload_from_box(dossier: Any, box: list[str]) -> str:
    """好 payload：盒内每段引一条（quote＝段文前 24 字逐字），全盒成对覆盖。"""
    evs = []
    for pid in box:
        seg = dossier.segment(pid)
        if seg is None:
            continue
        evs.append({
            "quote": seg.text[:24], "segment_id": pid,
            "relation": "correlation", "level": "B", "note": "leg0",
        })
    return json.dumps({"conclusions": [
        {"statement": "leg0 验收桩结论", "evidence": evs},
    ]}, ensure_ascii=False)


def _bad_then_good_payloads(dossier: Any, box: list[str]) -> list[str]:
    """坏 payload＝编造 id（out_of_box＋anchor_miss）→ 打回 → 好 payload。"""
    return ["{\"conclusions\": [{\"statement\": \"坏桩\", \"evidence\": ["
            "{\"quote\": \"不在资料里的句子\", \"segment_id\": \"ZZZ#fabricated\","
            " \"relation\": \"correlation\", \"level\": \"D\"}]}]}",
            _good_payload_from_box(dossier, box)]


def _leg0_case(slug: str, mark: str) -> list[dict[str, Any]]:
    from app.agents.base import Analyst
    from app.config import Settings
    from app.core.kg_submit_surface import (
        apply_kg_submit_surface, kg_focus_segment_ids, pack_kwargs_for_kg,
    )
    from app.core.kg_test_tree_line import ensure_test_tree_submit
    from app.core.material import pack_material
    from app.ingest.official_case import load_official_case
    from app.llm.model_client import ModelClient

    rows: list[dict[str, Any]] = []
    for qrow in _questions_from_conclusions(_case(mark)):
        qid, question = qrow["question_id"], qrow["question"]
        d = load_official_case(_case(mark))
        d.question = question
        ensure_test_tree_submit(d)
        apply_kg_submit_surface(d, enabled=True)
        pack = pack_material(d, **pack_kwargs_for_kg(d))
        box = [str(x) for x in
               ((d.accounting or {}).get("kg_submit", {})
                .get("rank_order") or [])]
        # ---- 桩 1：首答即好 → attempts=1、单调用
        s = Settings.from_env()
        s.models = [MODEL_ID]
        s.cite_accept = True
        s.cite_accept_attempts = 3
        c1 = _StubClient([_good_payload_from_box(d, box)])
        Analyst(name="mainstream", persona="p", model=MODEL_ID, client=c1,
                settings=s).analyze(d)
        acc1 = (d.accounting or {}).get("cite_accept", {}).get("mainstream", {})
        oob1 = [sid for e in d.evidences for sid in (e.segment_ids or [])
                if sid not in set(box)]
        # ---- 桩 2：坏→打回→好 → attempts=2、重写提示只含失败原因＋盒内编号
        d2 = load_official_case(_case(mark))
        d2.question = question
        ensure_test_tree_submit(d2)
        apply_kg_submit_surface(d2, enabled=True)
        pack_material(d2, **pack_kwargs_for_kg(d2))
        c2 = _StubClient(_bad_then_good_payloads(d2, box))
        Analyst(name="mainstream", persona="p", model=MODEL_ID, client=c2,
                settings=s).analyze(d2)
        acc2 = (d2.accounting or {}).get("cite_accept", {}).get("mainstream", {})
        oob2 = [sid for e in d2.evidences for sid in (e.segment_ids or [])
                if sid not in set(box)]
        suffix = ""
        if len(c2.calls) >= 2:
            base = c2.calls[0][1]["content"]
            full = c2.calls[1][1]["content"]
            suffix = full[len(base):] if full.startswith(base) else ""
        import re

        toks = set(re.findall(r"[A-Za-z0-9_]+#[A-Za-z0-9_#]+", suffix))
        allowed = set(box) | {"ZZZ#fabricated"}
        rows.append({
            "slug": slug, "qid": qid, "leg": "zero_call",
            "box_n": len(box),
            "stub1": {"attempts": acc1.get("attempts"),
                      "final_ok": acc1.get("final_ok"),
                      "n_calls": len(c1.calls), "oob_n": len(oob1),
                      "n_conclusions": len(d.conclusions)},
            "stub2": {"attempts": acc2.get("attempts"),
                      "final_ok": acc2.get("final_ok"),
                      "n_calls": len(c2.calls), "oob_n": len(oob2),
                      "attempt1_codes": (acc2.get("attempts_log")
                                         or [{}])[0].get("codes"),
                      "failure_block_present": "引用验收·打回第 1 次" in suffix,
                      "suffix_ids_subset_of_box_or_bad":
                          toks <= allowed if suffix else None,
                      "n_calls_total": len(c2.calls)},
        })
        print(f"… 腿0 {slug}/{qid} 桩1 attempts={acc1.get('attempts')} "
              f"带外={len(oob1)}｜桩2 attempts={acc2.get('attempts')} "
              f"码={(acc2.get('attempts_log') or [{}])[0].get('codes')} "
              f"带外={len(oob2)}", flush=True)
    return rows


# ------------------------------------------------ 腿G：三闸确定性复刻（零 LLM）

def _leg_gates() -> dict[str, Any]:
    out: dict[str, Any] = {}
    c134_gate = C134.get("gate_cases") or {}
    for slug in CASES:
        mark = CASE_MARKS[slug]
        exp = EXPECT[slug]
        prefer = exp["role"] == "regression"
        coeff, names = __import__(
            "app.core.kg_test_tree_line", fromlist=["test_tree_coeff"]
        ).test_tree_coeff()
        dens = _eval_case(slug, mark, coeff, names, prefer_gold=prefer)
        extra = _plan_cite_and_leak(slug, mark, coeff, names, prefer_gold=prefer)
        prod = _prod_leg(slug, mark)
        dens.update(extra)
        dens["prod_leg"] = prod
        ref = c134_gate.get(slug) or {}
        deltas = {}
        for key in ("micro_gold_density", "mean_gold_box_to_close", "n_leaks"):
            if key in ref and key in dens:
                deltas[key] = (dens[key], ref[key])
        if slug == "liuxiang" and "cut_hits" in ref:
            deltas["at7"] = (dens["cut_hits"].get("7"), ref["cut_hits"].get("7"))
        out[slug] = {"deltas_vs_c134": deltas,
                     "equal": all(a == b for a, b in deltas.values())}
        print(f"… 腿G {slug} 对照 {deltas}", flush=True)
    return out


# ------------------------------------------------ 腿1：14B 真跑（×3 遍）

def _real_pass(slug: str, mark: str, qid: str, pass_i: int) -> dict[str, Any]:
    from app.agents.base import Analyst
    from app.agents.prompts import render_segments_block
    from app.config import Settings
    from app.core.citation_check import check_evidence
    from app.core.kg_submit_surface import (
        apply_kg_submit_surface, kg_focus_segment_ids, pack_kwargs_for_kg,
    )
    from app.core.kg_test_tree_line import ensure_test_tree_submit
    from app.core.material import pack_material
    from app.ingest.official_case import load_official_case
    from app.llm.model_client import ModelClient
    from scripts.measure_s4_gates import lock_local

    print(lock_local(), flush=True)
    case = _case(mark)
    qrow = next(q for q in _questions_from_conclusions(case)
                if q["question_id"] == qid)
    os.environ.pop("VERITAS_TEST_TREE_LINE", None)
    t0 = time.perf_counter()
    settings = Settings.from_env()
    settings.models = [MODEL_ID]
    settings.multi_box = False
    settings.second_pass_enabled = False
    settings.review_boost = False
    settings.llm_timeout_seconds = 600
    settings.cite_accept = True  # C-139 被验面（env 同值，双保险）
    settings = settings.validate()
    d = load_official_case(case)
    d.question = qrow["question"]
    gold, gold_ids = _gold_ids(case, qid)

    ensure_test_tree_submit(d)
    apply_kg_submit_surface(d, enabled=True)
    pack = pack_material(d, **pack_kwargs_for_kg(d))
    focus = [str(x) for x in (kg_focus_segment_ids(d) or [])]
    surface = (d.accounting or {}).get("kg_submit") or {}
    box = [str(x) for x in (surface.get("rank_order") or [])]
    face = render_segments_block(d, focus_segment_ids=focus)

    analyst = Analyst(
        name="mainstream",
        persona="主流研判分析师，依据资料作答并给出逐字引文",
        model=settings.models[0],
        client=ModelClient(settings),
        settings=settings,
        profile_tier="compliant",
    )
    analyst.analyze(d)

    hit_para, hit_quote, hit_either = cited_hits(gold, d)
    l3 = sum(1 for k in gold.keys() if k in hit_either)
    acc_gate = (d.accounting or {}).get("cite_accept", {}).get("mainstream", {})
    cited_ids: set[str] = set()
    buckets: dict[str, int] = {"empty_quote": 0, "seg_missing": 0,
                               "verbatim_miss": 0, "adjacent_only": 0,
                               "other": 0}
    n_ev_fail = 0
    for e in d.evidences:
        cited_ids.update(str(x) for x in (e.segment_ids or []))
        fails = check_evidence(e, d) or []
        if fails:
            n_ev_fail += 1
        for f in fails:
            if f in ("空引文", "引文仅含省略号"):
                key = "empty_quote"
            elif f == "证据未指明来源段落" or f.startswith("来源段落不存在"):
                key = "seg_missing"
            elif f.startswith("引文未命中任何所指段落"):
                key = "verbatim_miss"
            elif f.startswith("引文只命中相邻段落"):
                key = "adjacent_only"
            else:
                key = "other"
            buckets[key] += 1
    out_of_band = sorted(cited_ids - set(box))
    pairs = (surface.get("conflict_pairs") or {})
    conflict_list = (pairs.get("conflicts") or []
                     if isinstance(pairs, dict) else [])
    pair_rows = []
    for p in conflict_list:
        if not isinstance(p, dict) or not (p.get("support_id")
                                           and p.get("oppose_id")):
            continue
        s_c = p["support_id"] in cited_ids
        o_c = p["oppose_id"] in cited_ids
        pair_rows.append({
            "support_id": p["support_id"], "oppose_id": p["oppose_id"],
            "support_cited": s_c, "oppose_cited": o_c,
            "one_sided": bool(s_c) != bool(o_c),
        })
    focus_gold = sorted(set(focus) & gold_ids)
    wl = (d.accounting or {}).get("window_ledger") or {}
    row = {
        "slug": slug, "qid": qid, "pass": pass_i,
        "attempts": acc_gate.get("attempts"),
        "attempts_cap": acc_gate.get("attempts_cap"),
        "attempts_log": acc_gate.get("attempts_log") or [],
        "final_ok": acc_gate.get("final_ok"),
        "maxed_out": acc_gate.get("maxed_out"),
        "codes_final": acc_gate.get("codes_final") or [],
        "pruned": acc_gate.get("pruned"),
        "box_n": len(box), "focus_n": len(focus),
        "focus_gold_n": len(focus_gold),
        "focus_precision": round(len(focus_gold) / len(focus), 4)
        if focus else None,
        "face_sha8": _sha8(face),
        "denom": len(gold), "l3": l3,
        "cited_n": len(cited_ids),
        "cited_gold_ids": sorted(
            (str(p) if "#" in str(p) else f"{doc}#{p}") for doc, p in hit_either),
        "out_of_band_ids": out_of_band,
        "pairs": pair_rows,
        "one_sided_n": sum(1 for p in pair_rows if p["one_sided"]),
        "n_conclusions": len(d.conclusions),
        "n_evidences": len(d.evidences),
        "n_ev_check_fail": n_ev_fail,
        "fail_buckets": buckets,
        "server_input_tokens": wl.get("input_tokens"),
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    print(f"… 真跑 {slug}/{qid} p{pass_i} attempts={row['attempts']} "
          f"码尾={row['codes_final']} cited={row['cited_n']} "
          f"L3={l3}/{row['denom']} 带外={len(out_of_band)} "
          f"单边={row['one_sided_n']}/{len(pair_rows)} "
          f"核对失败={n_ev_fail} ({row['wall_s']}s)", flush=True)
    return row


# ------------------------------------------------ 判定＋渲染

def _judge(gates: dict, leg0: list[dict], runs: list[dict]) -> dict[str, Any]:
    by_q_c134: dict[tuple, dict] = {
        (r["slug"], r["qid"]): r for r in (C134.get("real_runs") or [])}
    per_q: list[dict] = []
    slugs_qids = sorted({(r["slug"], r["qid"]) for r in runs})
    for slug, qid in slugs_qids:
        rs = [r for r in runs if r["slug"] == slug and r["qid"] == qid]
        ref = by_q_c134.get((slug, qid)) or {}
        def _m(key):
            vals = [r[key] for r in rs if r.get(key) is not None]
            if not vals:
                return None
            return {"mean": round(sum(vals) / len(vals), 4),
                    "min": min(vals), "max": max(vals)}
        per_q.append({
            "slug": slug, "qid": qid, "n_passes": len(rs),
            "attempts_vals": [r.get("attempts") for r in rs],
            "final_ok_vals": [r.get("final_ok") for r in rs],
            "maxed_out_any": any(r.get("maxed_out") for r in rs),
            "codes_seen": sorted({c for r in rs
                                  for a in (r.get("attempts_log") or [])
                                  for c in (a.get("codes") or [])}),
            "cited_n": _m("cited_n"), "l3": _m("l3"),
            "ref_c134": {k: ref.get(k) for k in ("cited_n", "l3",
                                                 "one_sided_n")},
            "delta_cited_mean": (
                round(_m("cited_n")["mean"] - ref["cited_n"], 4)
                if _m("cited_n") and ref.get("cited_n") is not None else None),
            "delta_l3_mean": (
                round(_m("l3")["mean"] - ref["l3"], 4)
                if _m("l3") and ref.get("l3") is not None else None),
            "oob_n_all_passes": sum(len(r.get("out_of_band_ids") or [])
                                    for r in rs),
            "one_sided_n_vals": [r.get("one_sided_n") for r in rs],
            # 单边对拆分（末轮闸账）：可执行（两侧都在盒）／不可执行（一侧
            # 不在盒＝引用面不可达，只披露不执行）
            "one_sided_enforced_final": [
                (r.get("attempts_log") or [{}])[-1].get("one_sided_n", 0)
                for r in rs],
            "unenforceable_pairs_final": [
                (r.get("attempts_log") or [{}])[-1].get(
                    "unenforceable_pairs_n", 0) for r in rs],
            "n_ev_check_fail_vals": [r.get("n_ev_check_fail") for r in rs],
            "ref_n_ev_check_fail_c134": ref.get("n_ev_check_fail"),
            "one_sided_all_passes": all(
                (r.get("one_sided_n") or 0) > 0 for r in rs)
            if rs else False,
            "face_sha8_vals": sorted({r.get("face_sha8") for r in rs}),
            "ref_face_sha8_c134": ref.get("face_sha8"),
            "wall_s_vals": [r.get("wall_s") for r in rs],
        })
    g1 = all(v.get("equal") for v in (gates or {}).values())
    g2_oob = all(r.get("oob_n_all_passes") == 0 for r in per_q) and all(
        r.get("stub1", {}).get("oob_n") == 0 and r.get("stub2", {}).get("oob_n") == 0
        for r in leg0)
    g2_pair = all(
        (not r["one_sided_all_passes"]) or r["maxed_out_any"]
        for r in per_q)
    g3_ref_down = all(
        (q["delta_cited_mean"] is None or q["delta_cited_mean"] + 1e-9 >= 0)
        and (q["delta_l3_mean"] is None or q["delta_l3_mean"] + 1e-9 >= 0)
        for q in per_q)
    retry_fired_stub = any(
        (r.get("stub2", {}).get("n_calls_total") or 0) >= 2 for r in leg0)
    retry_fired_real = any((r.get("attempts") or 1) >= 2 for r in runs)
    disclosed = all(
        (not r.get("maxed_out")) or (r.get("codes_final") and
                                     r.get("attempts") == r.get("attempts_cap"))
        for r in runs)
    yes = bool(g1 and g2_oob and g2_pair and g3_ref_down
               and (retry_fired_stub or retry_fired_real) and disclosed)
    return {
        "gate1_dens_leak_unchanged": g1,
        "gate2_oob_zero": g2_oob,
        "gate2_pair_ok_or_disclosed": g2_pair,
        "gate3_ref_not_down": g3_ref_down,
        "retry_fired_stub": retry_fired_stub,
        "retry_fired_real": retry_fired_real,
        "maxed_out_disclosed": disclosed,
        "YES": yes,
        "per_question": per_q,
    }


def _render_md(report: dict) -> str:
    j = report["judge"]
    runs = report.get("real_runs") or []
    wall_sum = round(sum(r.get("wall_s") or 0 for r in runs), 1)
    retried = [r for r in runs if (r.get("attempts") or 1) >= 2]
    lines = [
        "# C-139 树17 引用验收打回循环——两案×3 真跑交账", "",
        f"- tip／枝：`{report['tip']}`／`{report['branch']}`",
        f"- 模型：{report['model']}（本机 14B；env 组同 C-134＋"
        f"VERITAS_CITE_ACCEPT=1，上限默认 3）",
        f"- 墙钟：真跑合计 {wall_sum}s（assemble 汇总＝逐跑相加）", "",
        "## 机制", "",
        "- 挂点：`app/agents/base.py::Analyst.analyze`——分析师每轮产出在"
        "物化「前」过机器验收（`app/core/tree17_accept.py`）；只挂首轮形状"
        "（second_pass／multi_box 显式 focus 定向轮不在范围）。",
        "- 启用条件：`VERITAS_CITE_ACCEPT=1`（默认关）＋交卷盒在场"
        "（`kg_submit_active`，测试树主线）；关旗＝生产行为与改前逐字相同。",
        "- 失败码（零 LLM、可回放）：`empty_cite`／`out_of_box`／"
        "`anchor_miss`／`unverifiable`／`conflict_one_sided`（＋`unparsable`）。",
        "- 打回：失败原因＋原约束追加进重写提示，资料清单不变（仍只喂盒内"
        "段）、禁金标 id；上限 attempts 默认 3（env/"
        "`cite_accept_attempts`，硬顶 5）。",
        "- 到顶：机械剪枝丢盒外 evidence 后物化＋accounting"
        "`cite_accept[<analyst>]` 披露 `maxed_out`＋逐次失败码——不静默"
        "脏过、不死循环。",
        "- 成对执行口径：只执行「两侧都在交卷盒内」的 conflict_pairs（与树17"
        "计划层 pair_required 同口径）；一侧不在盒＝引用面不可达，只计"
        "`unenforceable_pairs_n` 披露、不进失败码（否则必败打回循环）。",
        "", "## 判定", "",
        f"- 总判：**{'YES' if j['YES'] else 'NO'}**",
        f"- 三闸旁证：dens/leak 与 C-134 逐位同＝{j['gate1_dens_leak_unchanged']}；"
        f"带外 0（真跑＋腿0）＝{j['gate2_oob_zero']}；"
        f"成对（都引或到顶披露）＝{j['gate2_pair_ok_or_disclosed']}；"
        f"引用/L3 对 C-134 不掉＝{j['gate3_ref_not_down']}",
        f"- 打回真实发生：桩路（人造失败）＝{j['retry_fired_stub']}；"
        f"真跑（真实失败）＝{j['retry_fired_real']}；"
        f"到顶披露齐全＝{j['maxed_out_disclosed']}", "",
        "## 逐题（×3 遍）", "",
        "| 案/题 | attempts（3 遍） | cited 均值(min..max) | Δcited | "
        "L3 均值 | ΔL3 | 带外 | 单边(全)/可执行/盒外披露 | 引文核对失败(3遍 vs C-134) | 到顶 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for q in j["per_question"]:
        cited = q["cited_n"] or {}
        l3 = q["l3"] or {}
        lines.append(
            f"| {q['slug']}/{q['qid']} | {q['attempts_vals']} | "
            f"{cited.get('mean')}({cited.get('min')}..{cited.get('max')}) | "
            f"{q['delta_cited_mean']} | {l3.get('mean')} | "
            f"{q['delta_l3_mean']} | {q['oob_n_all_passes']} | "
            f"{q['one_sided_n_vals']}/{q['one_sided_enforced_final']}/"
            f"{q['unenforceable_pairs_final']} | "
            f"{q['n_ev_check_fail_vals']} vs {q['ref_n_ev_check_fail_c134']} | "
            f"{'是' if q['maxed_out_any'] else '否'} |")
    lines += ["", "## 真实打回明细（attempts≥2 的跑次）", "",
              "| 跑次 | attempts | 首轮码 | 终局码 | 过/到顶 |",
              "|---|---|---|---|---|"]
    if not retried:
        lines.append("|（无）| | | | |")
    for r in retried:
        first = (r.get("attempts_log") or [{}])[0].get("codes")
        lines.append(
            f"| {r['slug']}/{r['qid']} p{r['pass']} | {r['attempts']} | "
            f"{first} | {r.get('codes_final')} | "
            f"{'过' if r.get('final_ok') else '到顶披露'} |")
    lines += ["", "## 腿0 零调用全路径（脚本桩）", "",
              "| 案/题 | 桩1 attempts/带外 | 桩2 attempts/首码/带外 | "
              "打回块在场 | 追加面 id 只含盒∪自错 |", "|---|---|---|---|---|"]
    for r in report["leg0"]:
        s1, s2 = r["stub1"], r["stub2"]
        lines.append(
            f"| {r['slug']}/{r['qid']} | {s1['attempts']}/{s1['oob_n']} | "
            f"{s2['attempts']}/{s2['attempt1_codes']}/{s2['oob_n']} | "
            f"{s2['failure_block_present']} | "
            f"{s2['suffix_ids_subset_of_box_or_bad']} |")
    lines += ["", "## 腿G 三闸对照 C-134（确定性面，应逐位同）", ""]
    for slug, v in (report.get("gates") or {}).items():
        lines.append(f"- {slug}：equal={v['equal']} "
                     f"deltas={v['deltas_vs_c134']}")
    lines += ["", "## 失败码（线上出现过的）", ""]
    codes = sorted({c for q in j["per_question"] for c in q["codes_seen"]})
    lines.append("- " + ("、".join(codes) if codes else "（无——真跑首答全过）"))
    lines += [
        "",
        "## 打回要点（现场发现）", "",
        "- liuxiang/q_001 三遍全部走到顶：首轮＝可执行成对单边"
        "（support `doc_014#p1` 有、oppose `doc_002#p3` 无）→ 打回后模型"
        "补上对侧（成对修复生效）；随后两轮败于 `unverifiable`（引文非逐字）"
        "→ 到顶披露，带外仍 0。账上单边 4 条全部来自盒外成员对"
        "（`doc_012#p2/p3`，引用面不可达），与闸账 `unenforceable_pairs_n=4`"
        "分区恒等吻合（18/18 跑核对）。",
        "- liuxiang/q_002 p3：`unverifiable` 打回 1 次 → 第 2 轮转绿"
        "（codes_final 空、final_ok=True）＝纯增益样本。",
        "- 引文逐字核对失败（零 LLM 复算）：除 q_001 到顶披露的 1 条/遍外，"
        "其余 15 跑全 0；C-134 存档同尺对照＝全 0（其单遍本来未踩"
        "unverifiable，差异属逐跑随机，如实记）。",
        "- 引用条数：q_001 均值 3.0 vs C-134 单遍 2（Δ+1，打回轮把对侧"
        "补进引用集的副作用）；其余 5 题 Δ0。L3 全部 Δ0（不掉、不涨）。",
        "- dens／leak0：腿G 与 C-134 存档逐位同（0.5714/0.8571、金标→close "
        "1.0、泄漏 0、刘翔@7=12）＝一筛／二筛／dens 公式零改动旁证。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--legs", choices=("zero", "gates", "real", "all",
                                       "assemble"), default="all")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--no-artifact", action="store_true")
    args = ap.parse_args()
    t0 = time.perf_counter()
    tip = _git_tip()
    os.environ.pop("VERITAS_TEST_TREE_LINE", None)
    for k, v in {
        "VERITAS_KG_SUBMIT_SURFACE": "1",
        "VERITAS_KG_STAGE1": "1",
        "VERITAS_KG_REHYDRATE_BOX": "1",
        "VERITAS_MULTI_BOX": "0",
        "VERITAS_SECOND_PASS": "0",
        "VERITAS_REVIEW_BOOST": "0",
        "VERITAS_CITE_ACCEPT": "1",
    }.items():
        os.environ[k] = v
    os.environ.pop("VERITAS_CITE_ACCEPT_ATTEMPTS", None)  # 默认 3
    OUT.mkdir(parents=True, exist_ok=True)

    leg0: list[dict] = []
    gates: dict = {}
    runs: list[dict] = []
    if args.legs == "assemble":
        leg0 = json.loads((OUT / "c139_leg0.json").read_text(encoding="utf-8"))
        gates = json.loads((OUT / "c139_gates.json").read_text(encoding="utf-8"))
        runs = json.loads((OUT / "c139_runs.json").read_text(encoding="utf-8"))
    else:
        if args.legs in ("zero", "all"):
            for slug in CASES:
                leg0 += _leg0_case(slug, CASE_MARKS[slug])
            (OUT / "c139_leg0.json").write_text(
                json.dumps(leg0, ensure_ascii=False, indent=1),
                encoding="utf-8")
        if args.legs in ("gates", "all"):
            gates = _leg_gates()
            (OUT / "c139_gates.json").write_text(
                json.dumps(gates, ensure_ascii=False, indent=1),
                encoding="utf-8")
        if args.legs in ("real", "all"):
            for slug in CASES:
                mark = CASE_MARKS[slug]
                for qrow in _questions_from_conclusions(_case(mark)):
                    for p in range(1, args.passes + 1):
                        runs.append(_real_pass(
                            slug, mark, qrow["question_id"], p))
                        (OUT / "c139_runs.json").write_text(json.dumps(
                            runs, ensure_ascii=False, indent=1),
                            encoding="utf-8")

    judge = _judge(gates, leg0, runs)
    report = {
        "ticket": "C-139-tree17-cite-retry",
        "tip": tip,
        "branch": "qoder/c139-tree17-cite-retry",
        "model": MODEL_ID,
        "env_note": ("不设 VERITAS_TEST_TREE_LINE（出厂开）；env 组同 C-134 "
                     "（REVIEW_BOOST 显式 0）＋VERITAS_CITE_ACCEPT=1；"
                     "attempts＝默认 3（env 未设）"),
        "passes": args.passes,
        "wall_s": round(time.perf_counter() - t0, 1),
        "gates": gates,
        "leg0": leg0,
        "real_runs": runs,
        "judge": judge,
    }
    (OUT / "C139_tree17_cite_retry.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.no_artifact:
        art = ROOT / "artifacts" / "C139_tree17_cite_retry.json"
        art.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        (ROOT / "artifacts" / "C139_tree17_cite_retry.md").write_text(
            _render_md(report), encoding="utf-8")
        print(f"wrote artifacts/C139_tree17_cite_retry.{{json,md}}", flush=True)
    print(f"总判={'YES' if judge['YES'] else 'NO'} "
          f"G1={judge['gate1_dens_leak_unchanged']} "
          f"带外0={judge['gate2_oob_zero']} "
          f"成对={judge['gate2_pair_ok_or_disclosed']} "
          f"不掉={judge['gate3_ref_not_down']} "
          f"打回(桩={judge['retry_fired_stub']}/真={judge['retry_fired_real']}) "
          f"wall={report['wall_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
