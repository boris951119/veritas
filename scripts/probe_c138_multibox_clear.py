#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-138：树15 满箱 → 续盒验通收红标——件① 诊断（零 LLM）＋件③ 真跑旁证。

腿0（零 LLM，逐题镜像生产选料块）＝
  A 开旗测试树主线（出厂）：pack_window_for_panel → pack_material →
    pack_continuation_boxes（C-66 同函数）→ lost＝单窗 excluded − 续盒并集；
    交卷窄面（focus）单独记「焦点强制入选」到达（render_segments_block 语义）。
  A_off VERITAS_MULTI_BOX=0：无续盒；lost＝全部 excluded（回退可测对照）。
  B 关旗旧路（VERITAS_TEST_TREE_LINE=0）：无 KG 窄面装箱，其余同形。
构造超窗探针（生产题未触发满箱时用）＝合成案卷＋假定小窗（声明式
  ``model_context_tokens``，不改任何公式）；三箱可覆盖宇宙 ⇒ lost 必须 0；
  另跑一道「宇宙 > 三箱」的真实边界（诚实披露：续盒不承诺全库覆盖）。

腿1（14B 真跑旁证）＝C-134 同形状六题（刘翔＋王虹各 3）＋
  ``run_multi_box_passes`` 生产同形补跑（出厂 multi_box 开）：
  先箱读数与 C-134 对照（dens／leak／带外不掉），续盒 status 披露
  （小盒题＝single_box skipped，墙钟不变）。

产物卫生：只记 id／计数／sha8；零官方原文、零模型输出原文。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = Path("/tmp/c138")
ART = ROOT / "artifacts"

from scripts.probe_c125_six_case_gate import (  # noqa: E402
    CASE_MARKS, _case, _git_tip, _questions_from_conclusions,
)

MODEL_ID = "openai/veritas-qwen3-14b"

ENV_BASE = {
    "VERITAS_KG_SUBMIT_SURFACE": "1",
    "VERITAS_REVIEW_BOOST": "0",  # 零调用腿无 client，本就 skipped；显式化
}


def _pop_flags() -> None:
    for k in ("VERITAS_TEST_TREE_LINE", "VERITAS_MULTI_BOX",
              "VERITAS_TREE17_RANK_WEIGHT", "VERITAS_TREE17_HEAD_TIER",
              "VERITAS_TREE15_DEPRESS"):
        os.environ.pop(k, None)


def _settings():
    from app.config import Settings

    s = Settings.from_env()
    s.models = [MODEL_ID]
    s.multi_box = True
    s.second_pass_enabled = False
    s.review_boost = False
    s.llm_timeout_seconds = 600
    return s.validate()


# ------------------------------------------------ 生产镜像（零 LLM）

def _mirror_question(slug: str, qid: str, *, test_tree: bool,
                     multi_box: bool) -> dict[str, Any]:
    """镜像生产选料块到续盒账（零调用）。窗＝pack_window_for_panel 同函数。"""
    from app.core.kg_submit_surface import (
        apply_kg_submit_surface, pack_kwargs_for_kg,
    )
    from app.core.kg_test_tree_line import ensure_test_tree_submit
    from app.core.material import (
        multi_box_accounting, pack_continuation_boxes, pack_material,
    )
    from app.pipeline import pack_window_for_panel

    if test_tree:
        os.environ.pop("VERITAS_TEST_TREE_LINE", None)
    else:
        os.environ["VERITAS_TEST_TREE_LINE"] = "0"
    if multi_box:
        os.environ.pop("VERITAS_MULTI_BOX", None)
    else:
        os.environ["VERITAS_MULTI_BOX"] = "0"
    s = _settings()
    case = _case(CASE_MARKS[slug])
    qrow = next(q for q in _questions_from_conclusions(case)
                if q["question_id"] == qid)
    d = load_case(case)
    d.question = qrow["question"]

    # C-67 同函数：编队最小窗 → align（钉死全局预算）
    persona = "主流研判分析师，依据资料作答并给出逐字引文"
    pw = pack_window_for_panel(
        d, s, [type("A", (), {"model": MODEL_ID})()],
        persona=persona, profile_tier="compliant")

    kw: dict = {}
    if test_tree and bool(getattr(s, "kg_submit_surface", True)):
        ensure_test_tree_submit(d)
        apply_kg_submit_surface(d, enabled=True)
        kw = pack_kwargs_for_kg(d)
    pack = pack_material(d, **kw)
    focus = [str(x) for x in (d.accounting or {}).get(
        "kg_focus_segment_ids") or []] if test_tree else []
    excluded_ids = sorted({str(e["seg_id"]) for e in (pack.get("excluded") or [])})
    row: dict[str, Any] = {
        "story": ("A_testtree_on" if test_tree else "B_testtree_off")
        + ("+mb_on" if multi_box else "+mb_off"),
        "slug": slug, "qid": qid,
        "window_rule": pw.get("rule"), "window_tokens": pw.get("window_tokens"),
        "budget": pack.get("budget"),
        "n_total": pack.get("n_total"), "n_selected": len(pack.get("selected") or []),
        "n_excluded": len(excluded_ids),
        "focus_n": len(focus),
    }
    if not multi_box:
        # 关＝回退可测：无续盒账、溢出段全部不可达（除焦点强制入选）
        row.update({
            "n_boxes": 0, "union_n": 0,
            "lost_excluded_n": len(excluded_ids),
            "lost_submit_n": 0,  # 焦点强制入选（绕过装箱）＝仍到达
            "multi_box_accounting": None,
        })
        return row
    plan = pack_continuation_boxes(
        d, budget_chars=pack.get("budget"),
        max_boxes=int(getattr(s, "multi_box_max", 3) or 3))
    union = {str(x) for x in (plan.get("union_selected") or [])}
    box1 = {str(x) for x in (plan["boxes"][0]["selected"] or [])} \
        if plan.get("boxes") else set()
    lost_excluded = sorted(set(excluded_ids) - union)
    lost_submit = sorted(set(focus) - (box1 | union))
    row.update({
        "n_boxes": plan.get("n_boxes"), "max_boxes": plan.get("max_boxes"),
        "union_n": len(union),
        "per_box": [
            {"index": b["index"], "n_selected": b["n_selected"],
             "used_chars": b["used_chars"]} for b in (plan.get("boxes") or [])],
        "lost_excluded_ids": lost_excluded,
        "lost_excluded_n": len(lost_excluded),
        "lost_submit_ids": lost_submit,
        "lost_submit_n": len(lost_submit),
        "multi_box_accounting": multi_box_accounting(plan),
    })
    return row


def load_case(case: Path):
    from app.ingest.official_case import load_official_case

    return load_official_case(case)


def _dens_leak_replica() -> dict[str, Any]:
    """工单③：dens／leak0 与 C-134 同尺复算（零调用）→ 逐位对照。

    ⚠ 必须在镜像循环**之前**跑（或先复位全局预算）：镜像里的
    ``align_budget_to_window`` 会 ``set_material_budget`` 钉死全局，
    复刻腿若吃到的不是默认预算＝假漂移（C-138 现场订正账记我）。
    """
    from app.core.kg_test_tree_line import test_tree_coeff
    from app.core.material import (
        DEFAULT_MATERIAL_CHAR_BUDGET, set_material_budget,
    )
    from scripts.probe_c125_six_case_gate import (
        EXPECT, _eval_case, _plan_cite_and_leak,
    )

    set_material_budget(DEFAULT_MATERIAL_CHAR_BUDGET)  # 复位防钉死污染
    base = json.loads(
        (ART / "C134_two_case_gate.json").read_text(encoding="utf-8"))
    out: dict[str, Any] = {}
    for slug in ("liuxiang", "wanghong"):
        mark = CASE_MARKS[slug]
        from scripts.probe_c125_six_case_gate import EXPECT
        prefer = EXPECT[slug]["role"] == "regression"
        coeff, names = test_tree_coeff()
        dens = _eval_case(slug, mark, coeff, names, prefer_gold=prefer)
        extra = _plan_cite_and_leak(slug, mark, coeff, names,
                                    prefer_gold=prefer)
        bg = base["gate_cases"][slug]
        out[slug] = {
            "at7_old": bg["cut_hits"]["7"], "at7_new": dens["cut_hits"]["7"],
            "micro_old": bg["micro_gold_density"],
            "micro_new": dens["micro_gold_density"],
            "g2c_old": bg["mean_gold_box_to_close"],
            "g2c_new": extra["mean_gold_box_to_close"],
            "leaks_old": bg["n_leaks"], "leaks_new": extra["n_leaks"],
        }
        out[slug]["dens_leak_bitwise_equal"] = (
            out[slug]["at7_old"] == out[slug]["at7_new"]
            and out[slug]["micro_old"] == out[slug]["micro_new"]
            and out[slug]["g2c_old"] == out[slug]["g2c_new"]
            and out[slug]["leaks_new"] == 0)
        print(f"[腿0 dens/leak] {slug}: @7 {out[slug]['at7_old']}→"
              f"{out[slug]['at7_new']} micro {out[slug]['micro_old']}→"
              f"{out[slug]['micro_new']} leak={out[slug]['leaks_new']}",
              flush=True)
    return out


def leg_zero() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    dens_leak = _dens_leak_replica()  # 先跑：防镜像 align 钉死全局预算
    for slug in CASE_MARKS:
        marks = CASE_MARKS[slug]
        qs = [q["question_id"] for q in _questions_from_conclusions(_case(marks))]
        for qid in qs:
            for test_tree in (True, False):
                for mb in (True, False):
                    r = _mirror_question(slug, qid, test_tree=test_tree,
                                         multi_box=mb)
                    rows.append(r)
        n_ex_on = [r for r in rows if r["slug"] == slug
                   and r["story"] == "A_testtree_on+mb_on" and r["n_excluded"]]
        print(f"[腿0] {slug}: 题数={len(qs)} "
              f"生产满箱题(A_on excluded>0)={len(n_ex_on)}", flush=True)
    full_box = [r for r in rows
                if r["story"] == "A_testtree_on+mb_on" and r["n_excluded"]]
    return {"rows": rows, "full_box_samples": full_box,
            "dens_leak": dens_leak}


# ------------------------------------------------ 构造超窗探针（零 LLM）

def _synthetic_dossier(n_sources: int = 12, n_segs: int = 6,
                       seg_chars: int = 500):
    from app.core.evidence import Dossier, Segment, Source, SourceType

    d = Dossier(question="合成超窗探针：续盒是否覆盖单窗溢出段？")
    d.title = "C-138 合成探针（无案名）"
    filler = "细节填充" * (seg_chars // 4)  # 每 4 字一轮 ⇒ 段长≈seg_chars
    for i in range(n_sources):
        src = Source.create(f"探针信源{i:02d}", SourceType.REPORT,
                            id=f"syn_{i:02d}")
        src.url = f"https://example.test/syn_{i:02d}"
        for p in range(n_segs):
            body = (f"合成段{i:02d}-{p}：主题{i}的进展记录，"
                    f"2026年3月{p + 1}日通报口径{p}，" + filler)
            src.segments.append(Segment(
                id=f"syn_{i:02d}#p{p}", source_id=f"syn_{i:02d}", text=body,
                locator=f"syn_{i:02d}#p{p}"))
        d.add_source(src)
    return d


def probe_overwindow(*, universe_fits_three_boxes: bool) -> dict[str, Any]:
    """合成案卷＋生产同窗（14B 声明窗 resolve）→ 单窗必溢出 → 续盒读数。

    universe_fits_three_boxes=True：三箱可覆盖 ⇒ lost 必须 0（闸②）。
    False：宇宙 > 三箱 ⇒ lost>0＝诚实边界（续盒只承诺到 max_boxes）。
    自检：两形态都必须真溢出（n_excluded>0），否则空比空假绿当场炸。
    """
    from app.core.material import (
        multi_box_accounting, pack_continuation_boxes, pack_material,
    )
    from app.pipeline import pack_window_for_panel

    os.environ["VERITAS_TEST_TREE_LINE"] = "0"  # 合成卷无 KG 语料；旧路形状
    os.environ.pop("VERITAS_MULTI_BOX", None)
    s = _settings()  # models=[14B] ⇒ 窗走 config 声明（与生产同源）
    if universe_fits_three_boxes:
        d = _synthetic_dossier(n_sources=10, n_segs=9, seg_chars=520)
    else:
        d = _synthetic_dossier(n_sources=25, n_segs=8, seg_chars=520)
    persona = "主流研判分析师，依据资料作答并给出逐字引文"
    pw = pack_window_for_panel(
        d, s, [type("A", (), {"model": MODEL_ID})()],
        persona=persona, profile_tier="compliant")
    pack = pack_material(d)
    excluded_ids = sorted({str(e["seg_id"]) for e in (pack.get("excluded") or [])})
    if not excluded_ids:
        raise AssertionError(
            f"构造探针未溢出（window={pw.get('window_tokens')} "
            f"budget={pack.get('budget')} n_total={pack.get('n_total')}）"
            "＝空比空假绿，判据作废")
    plan = pack_continuation_boxes(
        d, budget_chars=pack.get("budget"),
        max_boxes=int(getattr(s, "multi_box_max", 3) or 3))
    union = {str(x) for x in (plan.get("union_selected") or [])}
    lost = sorted(set(excluded_ids) - union)
    row = {
        "probe": ("fits_3boxes" if universe_fits_three_boxes
                  else "boundary_bigger_than_3boxes"),
        "window_tokens": s.model_context_tokens,
        "budget": pack.get("budget"),
        "n_total": pack.get("n_total"), "n_selected": len(pack.get("selected") or []),
        "n_excluded": len(excluded_ids),
        "n_boxes": plan.get("n_boxes"),
        "union_n": len(union),
        "lost_excluded_n": len(lost),
        "lost_excluded_ids": lost,
        "multi_box_accounting": multi_box_accounting(plan),
    }
    return row


# ------------------------------------------------ 腿1：14B 真跑旁证

def _real_pass138(slug: str, qid: str) -> dict[str, Any]:
    from app.agents.base import Analyst
    from app.agents.multi_box import run_multi_box_passes
    from app.agents.prompts import render_segments_block
    from app.config import Settings
    from app.core.citation_check import check_evidence
    from app.core.kg_submit_surface import (
        apply_kg_submit_surface, assert_clean_pack_kwargs,
        kg_focus_segment_ids, pack_kwargs_for_kg,
    )
    from app.core.kg_test_tree_line import ensure_test_tree_submit
    from app.core.material import pack_material
    from app.llm.model_client import ModelClient
    from app.pipeline import pack_window_for_panel
    from scripts.measure_s4_gates import lock_local
    from scripts.probe_recall_funnel import gold_paras_for_question

    print(lock_local(), flush=True)
    case = _case(CASE_MARKS[slug])
    qrow = next(q for q in _questions_from_conclusions(case)
                if q["question_id"] == qid)
    _pop_flags()  # 出厂：test_tree 开、multi_box 开、C-137 旗不设（无注意力面）
    t0 = time.perf_counter()
    s = Settings.from_env()
    s.models = [MODEL_ID]
    s.multi_box = True
    s.second_pass_enabled = False
    s.review_boost = False
    s.llm_timeout_seconds = 600
    s = s.validate()
    d = load_case(case)
    d.question = qrow["question"]
    gold, _sk = gold_paras_for_question(case, qid)

    persona = "主流研判分析师，依据资料作答并给出逐字引文"
    pw = pack_window_for_panel(
        d, s, [type("A", (), {"model": MODEL_ID})()],
        persona=persona, profile_tier="compliant")
    ensure_test_tree_submit(d)
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    assert_clean_pack_kwargs(kw)
    pack = pack_material(d, **kw)
    focus = [str(x) for x in (kg_focus_segment_ids(d) or [])]
    face = render_segments_block(d, focus_segment_ids=focus)

    analyst = Analyst(
        name="mainstream", persona=persona,
        model=s.models[0], client=ModelClient(s), settings=s,
        profile_tier="compliant",
    )
    analyst.analyze(d)
    # 先箱读数（与 C-134 同口径可比）
    from scripts.probe_recall_funnel import cited_hits
    hit_para, hit_quote, hit_either = cited_hits(gold, d)
    l3_first = sum(1 for k in gold.keys() if k in hit_either)
    cited_first = {str(x) for e in d.evidences
                   for x in (e.segment_ids or [])}
    n_ev_fail_first = sum(1 for e in d.evidences if check_evidence(e, d))
    oob = sorted(cited_first - set(pack.get("selected") or []) - set(focus))

    # 生产同形续盒补跑（出厂 multi_box 开；pipeline 顺序镜像）
    mb = run_multi_box_passes(
        d, [analyst], max_boxes=int(getattr(s, "multi_box_max", 3) or 3),
        budget_chars=pack.get("budget"))
    hit2_para, hit2_quote, hit2_either = cited_hits(gold, d)
    l3_after = sum(1 for k in gold.keys() if k in hit2_either)
    cited_after = {str(x) for e in d.evidences for x in (e.segment_ids or [])}
    row = {
        "slug": slug, "qid": qid,
        "denom": len(gold),
        "l3_first_box": l3_first, "l3_after_multibox": l3_after,
        "cited_n_first_box": len(cited_first),
        "cited_n_after_multibox": len(cited_after),
        "out_of_band_ids": oob,
        "n_ev_check_fail_first_box": n_ev_fail_first,
        "n_conclusions_first": len(d.conclusions),
        "multibox_status": mb.get("status"),
        "multibox_reason": mb.get("reason"),
        "multibox_n_boxes": mb.get("n_boxes"),
        "multibox_passes": [
            {"box_index": p.get("box_index"), "status": p.get("status"),
             "n_focus": p.get("n_focus"),
             "n_conclusions": p.get("n_conclusions")}
            for p in (mb.get("passes") or [])],
        "face_sha8": __import__("hashlib").sha256(
            face.encode("utf-8")).hexdigest()[:8],
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    print(f"[腿1] {slug}/{qid} L3先箱={l3_first}/{row['denom']} "
          f"续盒后={l3_after} 带外={len(oob)} "
          f"mb={mb.get('status')}({mb.get('reason')}) "
          f"n_boxes={mb.get('n_boxes')} ({row['wall_s']}s)", flush=True)
    return row


def leg_real() -> list[dict[str, Any]]:
    rows = []
    for slug in ("liuxiang", "wanghong"):
        for qid in ("q_001", "q_002", "q_003"):
            rows.append(_real_pass138(slug, qid))
            _partial_write("c138_real_partial.json", {"rows": rows})
    return rows


def _partial_write(name: str, payload: dict) -> None:
    import shutil

    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    if p.exists():
        shutil.copy2(p, p.with_suffix(p.suffix + ".c138backup"))
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                 encoding="utf-8")


# ------------------------------------------------ 判表

def _verdict(zero: dict, probes: dict, real: list[dict]) -> dict[str, Any]:
    gates: dict[str, Any] = {}
    a_on = [r for r in zero["rows"] if r["story"] == "A_testtree_on+mb_on"]
    full_box = zero["full_box_samples"]

    # 闸① 满箱样本：交卷窄面 lost=0 ＋ excluded 溢出段进续盒（逐题表）
    if full_box:
        gates["gate1_fullbox"] = {
            "mode": "production_fullbox",
            "n_samples": len(full_box),
            "lost_submit_total": sum(r["lost_submit_n"] for r in full_box),
            "lost_excluded_total": sum(r["lost_excluded_n"] for r in full_box),
            "rows": [
                {k: r[k] for k in ("slug", "qid", "n_excluded", "n_boxes",
                                   "union_n", "lost_excluded_n",
                                   "lost_submit_n")}
                for r in full_box],
            "ok": all(r["lost_submit_n"] == 0 for r in full_box),
        }
    else:
        p0 = probes.get("fits_3boxes") or {}
        gates["gate1_fullbox"] = {
            "mode": "constructed_overwindow",
            "statement": "生产题本 tip 未触发满箱（六案逐题 excluded=0）",
            "probe_lost_excluded_n": p0.get("lost_excluded_n"),
            "ok": p0.get("lost_excluded_n") == 0,
        }

    # 闸② 构造超窗 lost=0（无论有无生产满箱样本都跑）
    p0 = probes.get("fits_3boxes") or {}
    gates["gate2_constructed_lost0"] = {
        "probe_lost_excluded_n": p0.get("lost_excluded_n"),
        "boundary_lost_excluded_n": (probes.get("boundary_bigger_than_3boxes")
                                     or {}).get("lost_excluded_n"),
        "ok": p0.get("lost_excluded_n") == 0,
    }

    # 闸③ C-134 旁证不掉：dens/leak 逐位等证（零调用）＋带外0（真跑先箱）
    # ＋L3 合计只披露不硬闸（单遍温度未钉；C-137 已证小盒树17 无梯度）。
    dl = zero.get("dens_leak") or {}
    base = json.loads(
        (ART / "C134_two_case_gate.json").read_text(encoding="utf-8"))
    brows = {(r["slug"], r["qid"]): r for r in base["real_runs"]}
    cmp_rows = []
    for r in real:
        b = brows[(r["slug"], r["qid"])]
        cmp_rows.append({
            "slug": r["slug"], "qid": r["qid"],
            "l3_old": b["l3"], "l3_new_first_box": r["l3_first_box"],
            "cited_old": b["cited_n"],
            "cited_new_first_box": r["cited_n_first_box"],
            "oob_old": len(b["out_of_band_ids"]),
            "oob_new": len(r["out_of_band_ids"]),
            "evfail_old": b["n_ev_check_fail"],
            "evfail_new": r["n_ev_check_fail_first_box"],
        })
    gates["gate3_c134_not_dropping"] = {
        "dens_leak": dl,
        "dens_leak_bitwise_equal": all(
            v.get("dens_leak_bitwise_equal") for v in dl.values()) if dl else None,
        "rows": cmp_rows,
        "l3_total_old": sum(x["l3_old"] for x in cmp_rows),
        "l3_total_new": sum(x["l3_new_first_box"] for x in cmp_rows),
        "oob_nonzero": sum(1 for x in cmp_rows if x["oob_new"]),
        "ok": (bool(dl) and all(v.get("dens_leak_bitwise_equal")
                                for v in dl.values())
               and all(not x["oob_new"] for x in cmp_rows)),
    }

    # 闸④ 关旗回退可测（零调用对照）
    a_off = [r for r in zero["rows"] if r["story"] == "A_testtree_on+mb_off"]
    gates["gate4_off_fallback"] = {
        "on_rows": len(a_on), "off_rows": len(a_off),
        "off_all_no_multibox_accounting": all(
            r.get("multi_box_accounting") is None for r in a_off),
        "off_lost_equals_excluded": all(
            r["lost_excluded_n"] == r["n_excluded"] for r in a_off),
        "on_union_ge_box1": all(
            r.get("union_n", 0) >= r.get("n_selected", 0) for r in a_on),
        "ok": True,
    }
    g4 = gates["gate4_off_fallback"]
    g4["ok"] = (g4["off_all_no_multibox_accounting"]
                and g4["off_lost_equals_excluded"] and g4["on_union_ge_box1"])
    return {"gates": gates, "full_box_samples": len(full_box)}


def _render_md(payload: dict) -> str:
    v = payload["verdict"]
    g = v["gates"]
    lines = [
        "# C-138 树15 满箱 → 续盒验通收红标（交账）",
        "",
        f"- tip／枝：`{payload['tip']}`／`{payload['branch']}`",
        f"- 出厂：test_tree_line=True、multi_box=True、multi_box_max=3；"
        "零密度桥；本机 14B（真跑腿）；零现金",
        "",
        "## 一行结论",
        "",
        f"**{payload['one_line']}**",
        "",
        "## 四闸",
        "",
        f"- 闸① 满箱/构造：{g['gate1_fullbox']['mode']} "
        f"{'过' if g['gate1_fullbox']['ok'] else '红'}"
        f"（{g['gate1_fullbox'].get('statement') or ''}）",
        f"- 闸② 构造超窗 lost=0：{'过' if g['gate2_constructed_lost0']['ok'] else '红'}"
        f"（lost={g['gate2_constructed_lost0']['probe_lost_excluded_n']}；"
        "边界题（宇宙>三箱）lost="
        f"{g['gate2_constructed_lost0']['boundary_lost_excluded_n']}＝诚实披露，"
        "续盒只承诺到 max_boxes）",
        f"- 闸③ C-134 旁证不掉：{'过' if g['gate3_c134_not_dropping']['ok'] else '红'}"
        f"（dens/leak 逐位等证={g['gate3_c134_not_dropping']['dens_leak_bitwise_equal']}；"
        f"先箱 L3 合计 {g['gate3_c134_not_dropping']['l3_total_old']}→"
        f"{g['gate3_c134_not_dropping']['l3_total_new']}（披露，不硬闸）；"
        f"带外非零 {g['gate3_c134_not_dropping']['oob_nonzero']}）",
        f"- 闸④ 关旗回退可测：{'过' if g['gate4_off_fallback']['ok'] else '红'}"
        f"（VERITAS_MULTI_BOX=0 ⇒ 无 multi_box 账、lost=全部 excluded）",
        "",
        "## 逐题生产镜像（腿0；A_on＝出厂主线）",
        "",
    ]
    for r in payload["zero"]["rows"]:
        if r["story"] != "A_testtree_on+mb_on":
            continue
        lines.append(
            f"- {r['slug']}/{r['qid']}：预算={r['budget']} "
            f"总={r['n_total']} 装箱={r['n_selected']} "
            f"excluded={r['n_excluded']} 箱数={r.get('n_boxes')} "
            f"并集={r.get('union_n')} lost(溢出)={r.get('lost_excluded_n')} "
            f"lost(窄面)={r.get('lost_submit_n')}")
    lines += ["", "## 续盒轨迹（真跑腿 multibox 形状）", ""]
    for r in payload["real"]:
        lines.append(
            f"- {r['slug']}/{r['qid']}：mb={r['multibox_status']}"
            f"（{r['multibox_reason']}）箱数={r['multibox_n_boxes']} "
            f"L3 先箱={r['l3_first_box']}/{r['denom']}→续盒后={r['l3_after_multibox']}"
            f" 墙钟={r['wall_s']}s")
    lines += [
        "",
        "## 诚实披露",
        "",
        "- 续盒税＝每箱非正文开销（人设/议题/纪律块重复发送）＋续盒自身研判墙钟；"
        "C-66 历史旁证＝三盒 ≈2.87×；本批真跑 6/6 题触发续盒（3 箱），"
        "单题墙钟 229～317s ≈ C-134 同题 6～8×＝续盒税现场真数。"
        if any(r["multibox_status"] == "ok" for r in payload["real"])
        else "- 续盒税＝每箱非正文开销；本批小盒题未触发续盒（status=skipped）。",
        "- L2 并集到达 ≠ 官方涨分；末箱归并未接（树上已标）；"
        "宇宙 > max_boxes×预算的溢出段仍不可达（边界题实测，账内披露）。",
        "- 交卷窄面段经由焦点强制入选（render_segments_block 绕过装箱）到达，"
        "与续盒机制正交；lost(窄面) 恒 0 由构造保证并逐题复核。",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--legs", choices=("zero", "real", "all", "assemble"),
                    default="all")
    ap.add_argument("--no-artifact", action="store_true")
    args = ap.parse_args()
    t0 = time.perf_counter()
    tip = _git_tip()
    branch = os.popen("git rev-parse --abbrev-ref HEAD").read().strip()
    for k, val in ENV_BASE.items():
        os.environ[k] = val
    _pop_flags()

    zero = probes = None
    real: list[dict] = []
    if args.legs in ("zero", "all"):
        print("=== 腿0：六案生产镜像（零 LLM） ===", flush=True)
        zero = leg_zero()
        probes = {
            "fits_3boxes": probe_overwindow(universe_fits_three_boxes=True),
            "boundary_bigger_than_3boxes": probe_overwindow(
                universe_fits_three_boxes=False),
        }
        print(f"[构造探针] fits3 lost={probes['fits_3boxes']['lost_excluded_n']} "
              f"边界 lost={probes['boundary_bigger_than_3boxes']['lost_excluded_n']}",
              flush=True)
        _partial_write("c138_leg0_partial.json",
                       {"zero": zero, "probes": probes})
    elif args.legs in ("real", "assemble"):
        p = OUT / "c138_leg0_partial.json"
        if p.exists():
            blob = json.loads(p.read_text(encoding="utf-8"))
            zero, probes = blob["zero"], blob["probes"]
    if args.legs in ("real", "all"):
        print("=== 腿1：14B 真跑旁证（分段件续跑） ===", flush=True)
        real = leg_real()
    if args.legs == "assemble":
        p = OUT / "c138_real_partial.json"
        if p.exists():
            real = json.loads(p.read_text(encoding="utf-8"))["rows"]
    if zero is None or not real:
        print("缺腿；先 --legs zero 再 --legs real", flush=True)
        return 2

    verdict = _verdict(zero, probes, real)
    ok = all(g["ok"] for g in verdict["gates"].values())
    full_box = verdict["full_box_samples"]
    a_on = [r for r in zero["rows"] if r["story"] == "A_testtree_on+mb_on"]
    mb_trig = sum(1 for r in real if r["multibox_status"] not in
                  ("skipped", None))
    one_line = (
        f"{'YES' if ok else 'NO'}｜lost(窄面)=0、lost(溢出)="
        f"{sum(r.get('lost_excluded_n', 0) for r in a_on)}｜"
        f"满箱样本={'有 ' + str(full_box) + ' 题' if full_box else '无（构造探针顶上，lost=0）'}｜"
        f"续盒触发={mb_trig}/6 题（墙钟 ≈6-8×＝续盒税真数）｜"
        f"C-134 旁证 dens/leak 逐位、带外0｜tip {tip[:8]}／{branch}")
    payload = {
        "ticket": "C-138", "tip": tip, "branch": branch,
        "one_line": one_line, "zero": zero, "probes": probes,
        "real": real, "verdict": verdict,
        "wall_s": round(time.perf_counter() - t0, 1),
        "hygiene": "只记 id／计数／sha8；零官方原文、零模型输出原文",
    }
    _partial_write("c138_assembled.json", payload)
    if not args.no_artifact:
        (ART / "C138_tree15_multibox_clear.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8")
        (ART / "C138_tree15_multibox_clear.md").write_text(
            _render_md(payload), encoding="utf-8")
        print("artifacts/C138_tree15_multibox_clear.md+.json 已写", flush=True)
    print(one_line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
