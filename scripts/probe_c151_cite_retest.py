#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-151：VERITAS_CITE_ACCEPT 开旗复测判尺（离线零 LLM、零现金；只记 id／计数／sha8）。

三个跑次根同尺复算（不沿用别人的读数，避免口径不可比）：

- ``on``   开旗臂（本刀被验面）：/tmp/c151runs/time-*（刘翔＋王虹）
- ``off``  关旗臂（同环境同案，env=0）：/tmp/c151runs/time-*（刘翔）
- ``ref``  对照存档臂（C-149 关旗六案 18 题）：/tmp/s4runs/time-20261104-135401

每题量：带外 cite／引文逐字核对分桶（C-121 尺）／cited 条数／L3／@7／
支撑 facts 条数与金标 face／``accounting.cite_accept`` 打回次数与失败码／
conflict_trace 行数与分流计数／甲面 conflicting_facts 键数与命中。

跑前写死的门槛（本文件内常量，改判据须改代码＝留痕）：
- 硬闸：带外 cite 必须 0；``kg_submit.rank_order`` 出盒引用 0。
- 不退闸：开旗臂的 引文失败率／@7／L3／支撑条数 与关旗臂比，差值落在
  噪声带（C-120 现量 L3 跨度 2 ⇒ 单遍不可分）之外才算「掉」。
- 旁观：甲面键数或命中相对关旗臂掉 ≥20% ⇒ 记红、默认不开。

用法：
    .venv/bin/python -X utf8 scripts/probe_c151_cite_retest.py classify \\
        --root /tmp/c151runs/time-A,/tmp/c151runs/time-B     # 分臂核验
    .venv/bin/python -X utf8 scripts/probe_c151_cite_retest.py automeasure \\
        --base /tmp/c151runs                                 # 一条腿跑到出件
    ... measure --label on --root 根1,根2 / judge / assemble
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = Path("/tmp/c151")
ART_JSON = ROOT / "artifacts" / "C151_cite_accept_retest.json"
ART_MD = ROOT / "artifacts" / "C151_cite_accept_retest.md"
CASES_ROOT = Path(os.environ.get(
    "OFFICIAL_CASES",
    "/Users/liuboyu/Desktop/veritas-testcases/样例集-拓尔思-20261012"))
CASES = ("刘翔编制“二选一”事件", "王虹“北大discouraged”事件")
CASE_SLUG = {CASES[0]: "liuxiang", CASES[1]: "wanghong"}

# 跑前写死的判据常量
JIA_REGRESS_RATIO = 0.20      # 甲面掉两成＝记红
NOISE_L3_SPAN = 2             # C-120 现量 L3 跨度：｜Δ｜≤2 视为噪声，不说涨跌
REF_ROOT_DEFAULT = "/tmp/s4runs/time-20261104-135401"   # C-149 关旗六案 18 题存档
# 旁证闸比的检索面字段（答题侧的变化不该出现在这里，出现＝旗动到选料）
_DENS_KEYS = ("k", "n_core", "n_filler", "met_target", "route", "cap_segments")


def _load_dossier(report: dict):
    from app.core.evidence import Dossier
    return Dossier.from_dict(report)


def _buckets(d) -> tuple[dict[str, int], int]:
    """存活证据再跑一遍引文核对（C-121 同尺的分桶函数）。

    ⚠ 生产链在归并前已把坏引文打回，所以**存活面上的失败数天然是 0**——
    真正的 C-121 尺在 ``rejected`` 面（见 ``_rejection_face``），这里只作旁证。
    """
    from app.core.citation_check import check_evidence
    b = {"empty_quote": 0, "seg_missing": 0, "verbatim_miss": 0,
         "adjacent_only": 0, "other": 0}
    n_fail = 0
    for e in d.evidences:
        fails = check_evidence(e, d) or []
        if fails:
            n_fail += 1
        for f in fails:
            b[_bucket_of(f)] += 1
    return b, n_fail


def _bucket_of(fail: str) -> str:
    if fail in ("空引文", "引文仅含省略号"):
        return "empty_quote"
    if fail == "证据未指明来源段落" or fail.startswith("来源段落不存在"):
        return "seg_missing"
    if fail.startswith("引文未命中任何所指段落"):
        return "verbatim_miss"
    if fail.startswith("引文只命中相邻段落"):
        return "adjacent_only"
    return "other"


def _rejection_face(rep: dict) -> tuple[dict[str, int], int]:
    """C-121 尺的正身＝管线打回面（rejected）：只数条数与原因桶，不抄引文原文。"""
    b = {"empty_quote": 0, "seg_missing": 0, "verbatim_miss": 0,
         "adjacent_only": 0, "other": 0}
    n = 0
    for r in rep.get("rejected") or []:
        n += 1
        pr = r.get("problems")
        items = list(pr) if isinstance(pr, dict) else (pr or [])
        for x in items:
            b[_bucket_of(str(x))] += 1
    return b, n



def _jia(d) -> dict[str, Any]:
    """甲面（导出的 conflicting_facts）键数与条数——不重算判定，只数产物。"""
    from app.export.official import _conflicting_facts
    try:
        rows, skip_tie, skip_noloc = _conflicting_facts(d)
    except Exception:  # noqa: BLE001 — 旁观量失败不吞主读数
        return {"error": "jia_failed"}
    keys = {f"{r.get('doc_id')}#{r.get('para_id')}" for r in rows}
    return {"n_rows": len(rows), "n_keys": len(keys),
            "skip_tie": skip_tie, "skip_noloc": skip_noloc,
            "keys": sorted(keys)}


def _find_report(roots: list[str], case: str, qid: str) -> Path | None:
    """同一标签可有多个跑次根（开旗臂＝刘翔一棵＋王虹一棵）：取第一棵有件的。"""
    for r in roots:
        p = Path(r) / case / "questions" / qid / "report.json"
        if p.is_file():
            return p
    return None


def measure_root(label: str, root: str) -> dict:
    from scripts.probe_c125_six_case_gate import _questions_from_conclusions
    from scripts.probe_c134_two_case_gate import _gold_ids
    from scripts.probe_recall_funnel import cited_hits

    roots = [r.strip() for r in str(root).split(",") if r.strip()]
    per: list[dict] = []
    for case in CASES:
        cdir = CASES_ROOT / case
        if not cdir.is_dir():
            per.append({"case": CASE_SLUG[case], "error": "case_dir_missing"})
            continue
        gold_by_q = {}
        for q in _questions_from_conclusions(cdir):
            qid = str(q["question_id"])
            gold_by_q[qid] = _gold_ids(cdir, qid)[0]
        for qid, gold in sorted(gold_by_q.items()):
            p = _find_report(roots, case, qid)
            if p is None:
                per.append({"case": CASE_SLUG[case], "qid": qid,
                            "error": "report_missing"})
                continue
            rep = json.loads(p.read_text(encoding="utf-8"))
            acc = rep.get("accounting") or {}
            d = _load_dossier(rep)
            cited: set[str] = set()
            for e in d.evidences:
                cited.update(str(x) for x in (e.segment_ids or []))
            box = [str(x) for x in
                   ((acc.get("kg_submit") or {}).get("rank_order") or [])]
            # 两层「带外」：硬闸＝引用了没进提示词的段（越权／编造）；
            # 描述量＝引用了交卷窄面盒外的段（续盒与定向轮本就在盒外，不判红）
            packed = {str(x) for x in (acc.get("material_pack_union") or [])}
            oob_hard = sorted(cited - packed) if packed else []
            oob_box = sorted(cited - set(box)) if box else []
            buckets, n_ev_fail = _buckets(d)
            r_buckets, n_rejected = _rejection_face(rep)
            hp, hq, he = cited_hits(gold, d)
            # 金标键在 _gold_ids 里是 (doc_id, para_id) 元组——不归一会把交集算成 0
            gold_raw = set(gold.keys())          # (doc_id, para_id) 元组＝cited_hits 的键形
            gold_keys = {k[1] if isinstance(k, tuple) else str(k)
                         for k in gold_raw}      # 归一 para 键＝与甲面／焦点面可比
            focus_list = [str(x) for x in (acc.get("kg_focus_segment_ids") or [])]
            top7 = focus_list[:7]          # 分析师可见焦点面前七＝Top-7 落点
            hit7 = len(gold_keys & set(top7))
            box7 = box[:7]
            hit_box7 = len(gold_keys & set(box7))
            sup = _supporting_count(d)
            ca = acc.get("cite_accept") or {}
            ca_rows = {
                analyst: {
                    "attempts": v.get("attempts"),
                    "attempts_cap": v.get("attempts_cap"),
                    "maxed_out": bool(v.get("maxed_out")),
                    "final_ok": v.get("final_ok"),
                    "codes_final": list(v.get("codes_final") or []),
                    "codes_seen": sorted({c for log in (v.get("attempts_log") or [])
                                          for c in (log.get("codes") or [])}),
                    "n_log": len(v.get("attempts_log") or []),
                    "log_first": (v.get("attempts_log") or [{}])[0],
                    "pruned_dropped": {
                        "evidence": (v.get("pruned") or {}).get("n_dropped_evidence"),
                        "conclusions": (v.get("pruned") or {}).get(
                            "n_dropped_conclusions")},
                } for analyst, v in ca.items() if isinstance(v, dict)}
            ct = acc.get("conflict_trace") or {}
            ct_sm = ct.get("summary") or {}
            jia = _jia(d)
            n_attempted = len(d.evidences) + n_rejected
            per.append({
                "case": CASE_SLUG[case], "qid": qid,
                "n_evidences": len(d.evidences),
                "n_ev_with_fail": n_ev_fail,
                "n_rejected": n_rejected,
                "n_attempted_evidences": n_attempted,
                "citation_fail_rate": (round(n_rejected / n_attempted, 4)
                                        if n_attempted else None),
                "buckets": buckets,
                "reject_buckets": r_buckets,
                "cited_n": len(cited),
                "out_of_band_n": len(oob_hard),
                "out_of_band_ids": oob_hard[:8],
                "out_of_box_n": len(oob_box),
                "packed_n": len(packed),
                "l3": sum(1 for k in gold_raw if k in he),
                "gold_n": len(gold_keys),
                "hit_para": len(hp), "hit_quote": len(hq),
                "box_n": len(box), "focus_n": len(focus_list),
                "@7_gold_in_top7": hit7, "@7_gold_in_submit_box7": hit_box7,
                "supporting_facts_n": sup,
                "cite_accept": ca_rows,
                "cite_accept_present": bool(ca_rows),
                "conflict_trace_n": ct_sm.get("n"),
                "conflict_trace_by_triage": ct_sm.get("by_triage"),
                "conflict_trace_by_class": ct_sm.get("by_class"),
                "jia_rows": jia.get("n_rows"), "jia_keys": jia.get("n_keys"),
                "jia_gold_keys_hit": len(set(jia.get("keys") or [])
                                          & gold_keys),
                "jia_keys_sample_n": len(jia.get("keys") or []),
                "kg_density": (acc.get("kg_density") or {}),
                "n_calls": acc.get("n_calls"), "elapsed_s": acc.get("elapsed_s"),
                "tokens": acc.get("tokens"),
            })
    out = {"label": label, "root": str(root), "n_questions": len(per),
           "rows": per}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"measure_{label}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def _supporting_count(d) -> int:
    from app.export.official import _supporting_facts
    try:
        return len(_supporting_facts(d) or [])
    except Exception:  # noqa: BLE001
        return -1


def _agg(rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]
    n = len(ok)
    if not n:
        return {"n_ok": 0}

    def _mean(k):
        vs = [r[k] for r in ok if isinstance(r.get(k), (int, float))]
        return round(sum(vs) / len(vs), 4) if vs else None
    ev_total = sum(r["n_evidences"] for r in ok)
    fail_total = sum(r["n_ev_with_fail"] for r in ok)
    rej_total = sum(r.get("n_rejected", 0) for r in ok)
    attempted_total = sum(r.get("n_attempted_evidences", 0) for r in ok)
    return {
        "n_ok": n,
        "oob_total": sum(r["out_of_band_n"] for r in ok),
        "oob_box_total": sum(r.get("out_of_box_n", 0) for r in ok),
        "evidences_total": ev_total,
        "ev_with_fail_total": fail_total,
        "rejected_total": rej_total,
        "attempted_total": attempted_total,
        "citation_fail_rate_pooled": (round(rej_total / attempted_total, 4)
                                       if attempted_total else None),
        "reject_buckets_pooled": {
            k: sum((r.get("reject_buckets") or {}).get(k, 0) for r in ok)
            for k in ("empty_quote", "seg_missing", "verbatim_miss",
                      "adjacent_only", "other")},
        "fail_rate_pooled": (round(fail_total / ev_total, 4)
                              if ev_total else None),
        "buckets_pooled": {k: sum(r["buckets"][k] for r in ok)
                            for k in ok[0]["buckets"]},
        "cited_n_mean": _mean("cited_n"),
        "l3_mean": _mean("l3"),
        "l3_total": sum(r["l3"] for r in ok),
        "at7_total": sum(r["@7_gold_in_top7"] for r in ok),
        "at7_box7_total": sum(r.get("@7_gold_in_submit_box7", 0) for r in ok),
        "supporting_total": sum(max(r["supporting_facts_n"], 0) for r in ok),
        "jia_rows_total": sum(r["jia_rows"] or 0 for r in ok),
        "jia_keys_total": sum(r["jia_keys"] or 0 for r in ok),
        "jia_hit_total": sum(r["jia_gold_keys_hit"] or 0 for r in ok),
        "ct_rows_total": sum(r["conflict_trace_n"] or 0 for r in ok),
        "wall_mean_s": _mean("elapsed_s"),
        "calls_mean": _mean("n_calls"),
        "cite_accept_questions": sum(1 for r in ok
                                      if r["cite_accept_present"]),
        "attempts_vals": [a["attempts"] for r in ok
                           for a in (r["cite_accept"] or {}).values()],
        "maxed_out_any": any(a["maxed_out"] for r in ok
                              for a in (r["cite_accept"] or {}).values()),
        "codes_final_seen": sorted({c for r in ok
                                    for a in (r["cite_accept"] or {}).values()
                                    for c in (a.get("codes_final") or [])}),
        "pruned_dropped_evidence_total": sum(
            (a.get("pruned_dropped") or {}).get("evidence") or 0
            for r in ok for a in (r["cite_accept"] or {}).values()),
        "pruned_dropped_conclusions_total": sum(
            (a.get("pruned_dropped") or {}).get("conclusions") or 0
            for r in ok for a in (r["cite_accept"] or {}).values()),
        "unenforceable_pairs_vals": [
            ((a.get("log_first") or {}).get("unenforceable_pairs_n"))
            for r in ok for a in (r["cite_accept"] or {}).values()],
    }


def stage_judge() -> dict:
    docs = {}
    for name in ("on", "off", "ref"):
        p = OUT / f"measure_{name}.json"
        if p.is_file():
            docs[name] = json.loads(p.read_text(encoding="utf-8"))
    if "on" not in docs:
        raise SystemExit("缺开旗臂读数（先跑 measure --label on）")
    on_rows = [r for r in docs["on"]["rows"] if "error" not in r]
    off_rows_all = [r for r in (docs["off"].get("rows") if "off" in docs else [])
                    if "error" not in r]
    a_on = _agg(on_rows)
    a_off = _agg(off_rows_all)
    a_ref = _agg([r for r in docs["ref"]["rows"]
                   if "error" not in r and r["case"] in ("liuxiang", "wanghong")]
                  ) if "ref" in docs else {}

    # 逐题配对：只比两臂都出结论的同题同号（缺的题单列，不当 0 分）。
    # ⚠ 开旗臂可能有两棵根（刘翔＋王虹）、关旗臂只抽检一案——全量对比会把
    # 「案数不同」当成「旗的效果」，所以对照一律在配对集上算。
    on_by = {(r["case"], r["qid"]): r for r in on_rows}
    off_by = {(r["case"], r["qid"]): r for r in off_rows_all}
    common = sorted(set(on_by) & set(off_by))
    paired_rows_on = [on_by[k] for k in common]
    paired_rows_off = [off_by[k] for k in common]
    paired = []
    for key in common:
        o, f_ = on_by[key], off_by[key]
        paired.append({
            "case": key[0], "qid": key[1],
            "l3": (o["l3"], f_["l3"]),
            "at7": (o["@7_gold_in_top7"], f_["@7_gold_in_top7"]),
            "cited_n": (o["cited_n"], f_["cited_n"]),
            "evidences": (o["n_evidences"], f_["n_evidences"]),
            "rejected": (o["n_rejected"], f_["n_rejected"]),
            "fail_rate": (o["citation_fail_rate"], f_["citation_fail_rate"]),
            "supporting": (o["supporting_facts_n"], f_["supporting_facts_n"]),
            "jia_keys": (o["jia_keys"], f_["jia_keys"]),
        })
    missing_off = sorted(set(on_by) - set(off_by))
    missing_on = sorted(set(off_by) - set(on_by))

    # 旁证闸（dens／焦点面）：逐题比两臂的检索面读数——必须两侧都取到数才算
    # 「相同」，空比空不作数；这一条决定 Δ 是长在答题侧还是选料侧。
    dens_pairs = []
    for key in common:
        o, f_ = on_by[key], off_by[key]
        kd_o = o.get("kg_density") or {}
        kd_f = f_.get("kg_density") or {}
        fields = {x: (kd_o.get(x), kd_f.get(x)) for x in _DENS_KEYS}
        fields["focus_n"] = (o.get("focus_n"), f_.get("focus_n"))
        has_both = all(v is not None and w is not None for v, w in fields.values())
        dens_pairs.append({
            "case": key[0], "qid": key[1], "has_both": has_both,
            "identical": has_both and all(v == w for v, w in fields.values()),
            "fields": fields})
    dens_side_identical = bool(dens_pairs) and all(p["identical"] for p in dens_pairs)
    a_on_cmp = _agg(paired_rows_on) if common else {}
    a_off_cmp = _agg(paired_rows_off) if common else {}

    hard_oob_zero = a_on["oob_total"] == 0
    # 不退闸：与同环境关旗臂在**配对集**上逐键比（ref 只作存档，不同跑次不能当反事实）
    def _cmp(key, higher_better=True):
        if not a_off_cmp:
            return None
        b, c = a_on_cmp.get(key), a_off_cmp.get(key)
        if not isinstance(b, (int, float)) or not isinstance(c, (int, float)):
            return None
        return {"on": b, "off": c, "delta": round(b - c, 4),
                "n_paired": len(common)}
    deltas = {k: _cmp(k) for k in (
        "l3_total", "at7_total", "supporting_total", "cited_n_mean",
        "jia_rows_total", "jia_keys_total", "jia_hit_total",
        "citation_fail_rate_pooled", "rejected_total", "attempted_total")}
    l3_noise = (abs(deltas["l3_total"]["delta"]) <= NOISE_L3_SPAN
                if deltas.get("l3_total") else None)
    fail_worse = (deltas["citation_fail_rate_pooled"]["delta"] > 0
                  if deltas.get("citation_fail_rate_pooled") else None)
    jia_regress = None
    if deltas.get("jia_keys_total") and deltas["jia_keys_total"]["off"]:
        ratio = deltas["jia_keys_total"]["on"] / deltas["jia_keys_total"]["off"]
        jia_regress = ratio < (1 - JIA_REGRESS_RATIO)

    verdict = "NO"
    why = []
    if not hard_oob_zero:
        why.append(f"带外 cite＝{a_on['oob_total']}（硬闸＝0）")
    if fail_worse:
        why.append(f"引文逐字失败率（C-121 尺＝打回面／应考面）高于同环境关旗臂（"
                    f"Δ{deltas['citation_fail_rate_pooled']['delta']:+}）")
    if jia_regress:
        why.append("甲面冲突键数掉超 20%（冲突旁观记红）")
    if not why and not common:
        verdict = "PARTIAL"
        why.append("两臂无同题配对集（关旗臂未跑到开旗臂的题）⇒ 不退闸不可判，"
                   "只记机制读数，不能据此翻出厂默认")
    elif not why:
        if (deltas.get("l3_total") and deltas["l3_total"]["delta"] > NOISE_L3_SPAN) or \
           (deltas.get("at7_total") and deltas["at7_total"]["delta"] > 0):
            verdict = "YES"
            why.append("支撑／引用在噪声带外上行，硬闸与旁观均未破")
        else:
            verdict = "PARTIAL"
            why.append(f"机制仍正（打回真发生／带外 0），但支撑面 Δ 在噪声带内"
                       f"（L3 Δ≤{NOISE_L3_SPAN} 单遍不可分）⇒ 默认仍关")
    return {"verdict": verdict, "why": why, "agg_on": a_on,
            "agg_off": a_off, "agg_ref_two_cases": a_ref,
            "agg_on_paired": a_on_cmp, "agg_off_paired": a_off_cmp,
            "n_paired": len(common), "paired": paired,
            "paired_keys": [list(k) for k in common],
            "missing_in_off": [list(k) for k in missing_off],
            "missing_in_on": [list(k) for k in missing_on],
            "deltas": deltas,
            "l3_within_noise": l3_noise, "jia_regress": jia_regress,
            "gates": {"oob_zero": hard_oob_zero,
                      "fail_not_worse": not fail_worse,
                      "jia_not_regressed": not bool(jia_regress),
                      "paired_set_nonempty": bool(common),
                      # ⚠ 本条＝跑后补的旁证披露，不参与本次裁决（裁决只吃跑前写死的
                      # 三条：带外 0／失败率不升／甲面不掉两成），掉了也只作说明。
                      "dens_side_unchanged_posthoc": dens_side_identical},
            "dens_side": dens_pairs,
            "per_question_on": on_rows,
            "per_question_off": off_rows_all}


def root_flag_state(root: str) -> dict:
    """从产物自身判这棵根是开旗还是关旗（不靠启动顺序猜）。

    开旗臂的每题 `accounting.cite_accept` 必在场（`enabled` 只在闸真开着时写）；
    关旗臂不写这个键。两边都数出来才算「分类有据」，空根不当「关旗」。
    """
    n_rep = n_on = n_off = 0
    for p in sorted(Path(root).glob("*/questions/*/report.json")):
        try:
            rep = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        n_rep += 1
        if (rep.get("accounting") or {}).get("cite_accept"):
            n_on += 1
        else:
            n_off += 1
    arm = ("empty" if n_rep == 0 else
           "on" if n_on == n_rep else
           "off" if n_off == n_rep else "mixed")
    return {"root": str(root), "n_reports": n_rep,
            "n_with_cite_accept": n_on, "n_without_cite_accept": n_off,
            "arm": arm}


def stage_automeasure(base_dir: str, ref_root: str = "") -> dict:
    """跑完后的收口腿：分臂→两臂同尺复算→判→出件（一条命令，不靠手拼根名）。"""
    roots = sorted(d for d in glob.glob(os.path.join(base_dir, "time-*"))
                   if os.path.isdir(d))
    if not roots:
        raise SystemExit(f"{base_dir} 下没有 time-* 跑次根")
    cls = [root_flag_state(r) for r in roots]
    bad = [c for c in cls if c["arm"] in ("mixed", "empty")]
    if bad:
        raise SystemExit(f"跑次根分臂不明（不猜，交人工）：{bad}")
    on = [c["root"] for c in cls if c["arm"] == "on"]
    off = [c["root"] for c in cls if c["arm"] == "off"]
    if not on or not off:
        raise SystemExit(f"缺臂：开旗根 {len(on)} 棵／关旗根 {len(off)} 棵")
    measure_root("on", ",".join(on))
    measure_root("off", ",".join(off))
    ref_used = ""
    for cand in (ref_root, REF_ROOT_DEFAULT):
        if cand and Path(cand).is_dir():
            measure_root("ref", cand)
            ref_used = cand
            break
    extra = {"arm_classification": cls, "n_on_roots": len(on),
             "n_off_roots": len(off), "ref_root_used": ref_used}
    doc = stage_assemble(extra)
    print(json.dumps({k: doc[k] for k in
                      ("verdict", "why", "gates", "n_paired",
                       "arm_classification")}, ensure_ascii=False, indent=1))
    return doc


def stage_assemble(extra: dict | None = None) -> dict:
    j = stage_judge()
    docs = {}
    for name in ("on", "off", "ref"):
        p = OUT / f"measure_{name}.json"
        if p.is_file():
            docs[name] = json.loads(p.read_text(encoding="utf-8"))
    doc = {"ticket": "C-151", "roots": {k: v["root"] for k, v in docs.items()},
           "n_by_arm": {k: v["n_questions"] for k, v in docs.items()},
           "case_root": str(CASES_ROOT), "judge_constants": {
               "JIA_REGRESS_RATIO": JIA_REGRESS_RATIO,
               "NOISE_L3_SPAN": NOISE_L3_SPAN},
           **(extra or {}), **j}
    ART_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    _render_md(doc)
    return doc


def _render_md(doc: dict) -> None:
    def g(k):
        return doc.get(k) or {}
    n_paired = doc.get("n_paired") or 0
    # 对照列一律取配对集（两臂同题同号）；全量列只单独披露
    on = g("agg_on_paired") if n_paired else g("agg_on")
    off = g("agg_off_paired") if n_paired else {}
    ref = g("agg_ref_two_cases")
    d = doc.get("deltas") or {}

    def row(name, key, fmt="{:}"):
        o = on.get(key)
        f_ = off.get(key)
        r_ = ref.get(key)
        dl = (d.get(key) or {}).get("delta")
        return (f"| {name} | {o if o is not None else '—'} "
                f"| {f_ if f_ is not None else '—'} "
                f"| {dl if dl is not None else '—'} "
                f"| {r_ if r_ is not None else '—'} |")
    on_full = g("agg_on")
    lines = [
        "# C-151 复测读数（脚本现抄，非手打）",
        "",
        f"- 开旗根＝`{doc['roots'].get('on')}`",
        f"- 关旗根＝`{doc['roots'].get('off')}`",
        f"- 存档根（C-149，只取同两案）＝`{doc['roots'].get('ref')}`",
        f"- 题数：开旗 {doc['n_by_arm'].get('on')}／关旗 "
        f"{doc['n_by_arm'].get('off')}／存档 {doc['n_by_arm'].get('ref')}",
        f"- 配对集（两臂同题同号）＝{n_paired} 题"
        f"｜只在开旗＝{doc.get('missing_in_off')}"
        f"｜只在关旗＝{doc.get('missing_in_on')}",
        "",
        f"**裁决＝{doc.get('verdict')}**，理由：{'；'.join(doc.get('why') or [])}",
        "",
        "| 量 | 开旗（配对） | 关旗（同环境配对） | Δ(开−关) | C-149 存档（两案） |",
        "|---|---|---|---|---|",
        row("证据条数合计（存活面）", "evidences_total"),
        row("引文打回条数（C-121 尺＝打回面）", "rejected_total"),
        row("应考条数（存活＋打回）", "attempted_total"),
        row("逐字失败率（C-121 尺，池化）", "citation_fail_rate_pooled"),
        row("存活面再核对失败条数（旁证，天然≈0）", "ev_with_fail_total"),
        row("带外（引用未进提示词＝硬闸）", "oob_total"),
        row("盒外（引用未进交卷窄面＝描述量）", "oob_box_total"),
        row("被引段数均值", "cited_n_mean"),
        row("L3（金标被引到）合计", "l3_total"),
        row("@7（金标进焦点面前七）合计", "at7_total"),
        row("@7（金标进交卷窄面前七）合计", "at7_box7_total"),
        row("支撑 facts 合计", "supporting_total"),
        row("甲面冲突条数", "jia_rows_total"),
        row("甲面冲突键数", "jia_keys_total"),
        row("甲面命中金标键", "jia_hit_total"),
        row("conflict_trace 行合计", "ct_rows_total"),
        "",
        "## 打回环现场（开旗臂全量）",
        f"- 有 cite_accept 记账的题数＝{on_full.get('cite_accept_questions')}",
        f"- attempts 取值＝{on_full.get('attempts_vals')}",
        f"- 到顶（attempts 打满上限）任意为真＝{on_full.get('maxed_out_any')}",
        f"- 末轮仍失败码集合＝{on_full.get('codes_final_seen')}",
        f"- 首轮不可执法对（unenforceable_pairs_n）取值＝"
        f"{on_full.get('unenforceable_pairs_vals')}",
        f"- 打回环裁掉：证据 {on_full.get('pruned_dropped_evidence_total')} 条／"
        f"结论 {on_full.get('pruned_dropped_conclusions_total')} 条",
        f"- 全量（非配对）：L3={on_full.get('l3_total')}｜@7="
        f"{on_full.get('at7_total')}｜支撑={on_full.get('supporting_total')}"
        f"｜失败率={on_full.get('citation_fail_rate_pooled')}",
        "",
        "## 逐题（开旗臂）",
        "",
        "| 案 | 题 | attempts | 码 | 带外 | cited | L3 | @7 | 打回条/应考 | 甲面键 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in doc.get("per_question_on") or []:
        ca = list((r.get("cite_accept") or {}).values())
        att = [a.get("attempts") for a in ca]
        codes = sorted({c for a in ca for c in (a.get("codes_final") or [])})
        lines.append(
            f"| {r['case']} | {r['qid']} | {att} | {'、'.join(codes) or '—'} "
            f"| {r['out_of_band_n']} | {r['cited_n']} | {r['l3']}/{r['gold_n']} "
            f"| {r['@7_gold_in_top7']} | {r['n_rejected']}/"
            f"{r['n_attempted_evidences']} | {r['jia_keys']} |")
    lines += ["", "## 逐题配对（开旗 vs 同环境关旗；每格＝开／关）", "",
              "| 案 | 题 | L3 | @7 | cited | 存活证据 | 打回条 | 失败率 "
              "| 支撑 | 甲面键 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for p in doc.get("paired") or []:
        lines.append(
            f"| {p['case']} | {p['qid']} | {list(p['l3'])} | {list(p['at7'])} "
            f"| {list(p['cited_n'])} | {list(p['evidences'])} "
            f"| {list(p['rejected'])} | {list(p['fail_rate'])} "
            f"| {list(p['supporting'])} | {list(p['jia_keys'])} |")
    lines += ["", "## 分桶（池化，C-121 同尺＝打回面）", ""]
    for k, v in (on.get("reject_buckets_pooled") or {}).items():
        lines.append(f"- 开旗 {k}＝{v}")
    for k, v in (off.get("reject_buckets_pooled") or {}).items():
        lines.append(f"- 关旗 {k}＝{v}")
    lines += ["", "## 分桶（存活面再核对，天然≈0，只作旁证）", ""]
    for k, v in (on.get("buckets_pooled") or {}).items():
        lines.append(f"- 开旗 {k}＝{v}")
    for k, v in (off.get("buckets_pooled") or {}).items():
        lines.append(f"- 关旗 {k}＝{v}")
    lines += [
        "",
        "## 旁证闸（检索面逐题两臂对照；跑后补的披露，不参与裁决）",
        f"- 两臂 k／n_core／n_filler／met_target／route／cap_segments／focus_n "
        f"逐题全同＝{(doc.get('gates') or {}).get('dens_side_unchanged_posthoc')}"
        f"（配对 {n_paired} 题，两侧都取到数才算同）",
    ]
    for p in doc.get("dens_side") or []:
        lines.append(f"- {p['case']} {p['qid']}：同＝{p['identical']}｜"
                     f"两臂有数＝{p['has_both']}")
    lines += [
        "",
        f"- 墙钟均值：开旗 {on.get('wall_mean_s')}s／关旗 {off.get('wall_mean_s')}s"
        f"（打回环允许上升，不作判据；关旗只抽检一案，跨案不可直接比）",
        f"- 调用数均值：开旗 {on.get('calls_mean')}／关旗 {off.get('calls_mean')}",
        "",
        "产物卫生：本件只含 id／计数／比率，零案卷原文、零模型输出原文。",
    ]
    ART_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["measure", "judge", "assemble",
                                      "automeasure", "classify"])
    ap.add_argument("--label", default="on")
    ap.add_argument("--root", default="")
    ap.add_argument("--base", default="/tmp/c151runs")
    ap.add_argument("--ref", default="")
    args = ap.parse_args()
    if args.stage == "classify":
        if not args.root:
            print("classify 需要 --root")
            return 2
        print(json.dumps([root_flag_state(r) for r in
                          [x.strip() for x in args.root.split(",") if x.strip()]],
                         ensure_ascii=False, indent=1))
        return 0
    if args.stage == "automeasure":
        stage_automeasure(args.base, args.ref)
        return 0
    if args.stage == "measure":
        if not args.root:
            print("measure 需要 --root")
            return 2
        out = measure_root(args.label, args.root)
        print(json.dumps(_agg(out["rows"]), ensure_ascii=False, indent=1))
        return 0
    doc = stage_assemble() if args.stage == "assemble" else stage_judge()
    print(json.dumps({k: doc[k] for k in ("verdict", "why", "gates", "deltas")
                      if k in doc}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
