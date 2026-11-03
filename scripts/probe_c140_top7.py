#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-140：交卷硬 Top-7＋冲突成对保位——腿0 零调用全路径＋腿1 14B 真跑（只量不修）。

腿0（零 LLM）＝
  A 门控复刻（C-134 同尺：``_eval_case``／``_plan_cite_and_leak``／
    ``_prod_leg`` 原样复用，prefer_gold 按角色：刘翔回归臂 True／王虹
    holdout False）——**先跑**并显式复位 ``set_material_budget``（C-138
    教训：镜像腿 ``align_budget_to_window`` 会钉全局预算，污染复刻腿）；
  B 生产面镜像（选料块：ensure_test_tree_submit → apply_kg_submit_surface
    → apply_submit_top7 → pack_material → focus → face）逐题：
    - 关旗面：focus_off 与 C-134 真跑 focus_ids 逐位相等、渲染 face
      sha8 与 C-134 face_sha8 逐位相等（＝C-140 关旗零 diff）；
    - 开旗面：submit_top7 回放（final＝top7＋reserve、cut＝候选−final
      逐位重算一致）；无对题 final_n＝min(7, 候选长)≤7；
    - 金标注账（评测用，不进线上）：face_gold_after 对 before（C-134
      focus_gold_n 锚）不掉；裁掉段含金标逐条记账（cut_gold_ids）。
腿1（14B 真跑）＝C-134 ``_real_pass`` 同形状（单 mainstream 分析师、
  锁本机、温度未钉、超时 600s、门控 env 组、不设 VERITAS_TEST_TREE_LINE、
  VERITAS_SUBMIT_TOP7 出厂开）× 六题（刘翔＋王虹各 q_001..q_003）；
  逐题记 L3／引用／带外（对 face 与对盒两个口径）／核对失败／墙钟。

分段件 ``/tmp/c140``（重跑前自动备份 ``.c140backup``）；产物卫生＝只记
id／计数／sha8，零官方原文、零模型输出原文。依赖：``artifacts/
C134_two_case_gate.json``（基线，gitignore 同 C-137/C-138 探针）；
``.kgcache``／``.kg_lab_vault`` 须与 C-134 跑时字节对齐（跨树软链）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = Path("/tmp/c140")
ART = ROOT / "artifacts"

from scripts.probe_c125_six_case_gate import (  # noqa: E402
    CASE_MARKS, EXPECT, _case, _eval_case, _plan_cite_and_leak,
    _prod_leg, _questions_from_conclusions,
)
from scripts.probe_recall_funnel import (  # noqa: E402
    cited_hits, gold_paras_for_question,
)

MODEL_ID = "openai/veritas-qwen3-14b"
CASES = ("liuxiang", "wanghong")
QIDS = ("q_001", "q_002", "q_003")

ENV_GROUP = {
    "VERITAS_KG_SUBMIT_SURFACE": "1",
    "VERITAS_KG_STAGE1": "1",
    "VERITAS_KG_REHYDRATE_BOX": "1",
    "VERITAS_MULTI_BOX": "0",
    "VERITAS_SECOND_PASS": "0",
    "VERITAS_REVIEW_BOOST": "0",  # 与 C-129/C-130/C-134/C-137 门控基线同组
}


def _sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _baseline() -> dict[str, Any]:
    raw = json.loads(
        (ART / "C134_two_case_gate.json").read_text(encoding="utf-8"))
    base_rows = {(r["slug"], r["qid"]): r for r in raw["real_runs"]}
    gate = raw["gate_cases"]
    rings = {(r["slug"], r["qid"]): [str(x) for x in (r.get("box_ids") or [])]
             for r in raw["rings"]}
    return {"tip": raw.get("tip"), "rows": base_rows, "gate": gate,
            "rings": rings}


def _backup(path: Path) -> None:
    if path.exists():
        dst = path.with_suffix(path.suffix + ".c140backup")
        shutil.copy2(path, dst)


def _partial_write(name: str, payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    _backup(p)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def _gate_env() -> None:
    for k, v in ENV_GROUP.items():
        os.environ[k] = v
    os.environ.pop("VERITAS_SUBMIT_TOP7", None)   # 出厂开
    os.environ.pop("VERITAS_TEST_TREE_LINE", None)
    os.environ.pop("VERITAS_TREE17_RANK_WEIGHT", None)
    os.environ.pop("VERITAS_TREE17_HEAD_TIER", None)


def _selection(dossier, *, c140: bool):
    """镜像 pipeline 选料块；返回 (box, focus, acc)。"""
    from app.core.kg_submit_surface import (
        apply_kg_submit_surface, assert_clean_pack_kwargs, pack_kwargs_for_kg,
    )
    from app.core.kg_test_tree_line import ensure_test_tree_submit

    ensure_test_tree_submit(dossier)
    apply_kg_submit_surface(dossier, enabled=True)
    kw = pack_kwargs_for_kg(dossier)
    assert_clean_pack_kwargs(kw)
    if c140:
        from app.core.submit_top7 import apply_submit_top7
        apply_submit_top7(dossier, enabled=True)
    else:
        os.environ["VERITAS_SUBMIT_TOP7"] = "0"
        try:
            from app.core.submit_top7 import apply_submit_top7
            apply_submit_top7(dossier)  # env 关＝零行为
        finally:
            os.environ.pop("VERITAS_SUBMIT_TOP7", None)
    acc = dossier.accounting
    box = [str(x) for x in ((acc.get("kg_submit") or {}).get("rank_order")
                            or [])]
    focus = [str(x) for x in (acc.get("kg_focus_segment_ids") or [])]
    return box, focus, acc


# ------------------------------------------------ 腿0：零调用全路径

def _gate_replica() -> dict[str, Any]:
    """C-134 同尺门控复刻（先跑；显式复位全局预算＝C-138 教训）。"""
    from app.core.material import DEFAULT_MATERIAL_CHAR_BUDGET
    from app.core.material import set_material_budget

    set_material_budget(DEFAULT_MATERIAL_CHAR_BUDGET)
    out: dict[str, Any] = {}
    for slug in CASES:
        mark = CASE_MARKS[slug]
        prefer = EXPECT[slug]["role"] == "regression"
        from app.core.kg_test_tree_line import test_tree_coeff
        coeff, names = test_tree_coeff()
        dens = _eval_case(slug, mark, coeff, names, prefer_gold=prefer)
        extra = _plan_cite_and_leak(slug, mark, coeff, names,
                                    prefer_gold=prefer)
        prod = _prod_leg(slug, mark)
        out[slug] = {
            "slug": slug, "gold_total": dens["gold_total"],
            "cut_hits": dens["cut_hits"],
            "micro_gold_density": dens["micro_gold_density"],
            "avg_gold_density": dens["avg_gold_density"],
            "mean_gold_box_to_close": extra["mean_gold_box_to_close"],
            "n_leaks": extra["n_leaks"],
            "n_submit_ok": extra["n_submit_ok"],
            "prod_leg": prod,
        }
        print(f"[腿0 门控] {slug}: @7={dens['cut_hits']['7']} "
              f"micro={dens['micro_gold_density']} "
              f"g2c={extra['mean_gold_box_to_close']} "
              f"leak={extra['n_leaks']}", flush=True)
    return out


def _gold_ids(slug: str, qid: str) -> tuple[dict, set[str]]:
    case = _case(CASE_MARKS[slug])
    gold, _sk = gold_paras_for_question(case, qid)
    gids = {str(p) if "#" in str(p) else f"{doc}#{p}"
            for doc, p in gold.keys()}
    return gold, gids


def _mirror(slug: str, qid: str) -> dict[str, Any]:
    from app.agents.prompts import render_segments_block
    from app.config import Settings
    from app.core.material import pack_material
    from app.ingest.official_case import load_official_case

    case = _case(CASE_MARKS[slug])
    qrow = next(q for q in _questions_from_conclusions(case)
                if q["question_id"] == qid)
    _gate_env()
    settings = Settings.from_env()
    settings.models = [MODEL_ID]
    settings.multi_box = False
    settings.second_pass_enabled = False
    settings.review_boost = False
    settings.llm_timeout_seconds = 600
    settings = settings.validate()

    # 关旗臂（改前形状）
    d_off = load_official_case(case)
    d_off.question = qrow["question"]
    box_off, focus_off, acc_off = _selection(d_off, c140=False)
    assert "submit_top7" not in acc_off, "关旗臂不得写 submit_top7"
    face_off = render_segments_block(d_off, focus_segment_ids=focus_off)

    # 开旗臂（本刀行为）
    d_on = load_official_case(case)
    d_on.question = qrow["question"]
    box, _focus_pre, acc = _selection(d_on, c140=False)  # 先拿改前形状
    focus_pre = list(acc["kg_focus_segment_ids"])
    t17_pre = json.dumps(acc["tree17_cite"], ensure_ascii=False,
                         sort_keys=True)
    from app.core.submit_top7 import apply_submit_top7
    face_d = apply_submit_top7(d_on, enabled=True)
    assert face_d and face_d.get("enabled") is True
    face_on = render_segments_block(d_on, focus_segment_ids=face_d["final_ids"])

    cand = [str(x) for x in ((acc.get("kg_test_tree") or {}).get(
        "rerank_order") or [])]
    # 回放：final＝top7＋reserve；cut＝候选−final（逐位重算）
    replay_ok = (
        face_d["final_ids"] ==
        face_d["top_ids"] + face_d["reserve_ids"]
        and face_d["cut_ids"] ==
        [c for c in cand if c not in set(face_d["final_ids"])]
    )
    # 盒／tree17 不被本机制改动
    box_untouched = box == box_off
    t17_untouched = json.dumps(acc["tree17_cite"], ensure_ascii=False,
                               sort_keys=True) == t17_pre

    # 金标注账（评测用，不进线上）
    gold, gids = _gold_ids(slug, qid)
    face_gold_before = sorted(set(focus_off) & gids)
    face_gold_after = sorted(set(face_d["final_ids"]) & gids)
    cut_gold = sorted(set(face_d["cut_ids"]) & gids)
    box_dropped = [b for b in box if b not in set(face_d["final_ids"])]
    box_dropped_gold = sorted(set(box_dropped) & gids)

    return {
        "slug": slug, "qid": qid,
        "box": box, "box_n": len(box),
        "candidates_n": face_d["candidates_n"],
        "candidates_source": face_d["candidates_source"],
        "k_top": face_d["k_top"],
        "reserve_added": face_d["reserve_added"],
        "final_n": face_d["final_n"],
        "top_ids": face_d["top_ids"],
        "reserve_ids": face_d["reserve_ids"],
        "final_ids": face_d["final_ids"],
        "cut_ids": face_d["cut_ids"],
        "pair_rows_n": face_d["n_pair_rows"],
        "pair_reserve_n": face_d["n_pair_reserve"],
        "replay_ok": bool(replay_ok),
        "box_untouched": bool(box_untouched),
        "t17_untouched": bool(t17_untouched),
        "focus_pre_n": len(focus_pre),
        "focus_off_ids": focus_off,
        "focus_off_vs_c134": "PENDING",
        "face_off_chars": len(face_off), "face_off_sha8": _sha8(face_off),
        "face_on_chars": len(face_on), "face_on_sha8": _sha8(face_on),
        # 金标注账（评测用）
        "gold_n": len(gids),
        "face_gold_before_ids": face_gold_before,
        "face_gold_after_ids": face_gold_after,
        "cut_gold_ids": cut_gold,
        "box_dropped_n": len(box_dropped),
        "box_dropped_gold_ids": box_dropped_gold,
    }


def leg_zero() -> dict[str, Any]:
    base = _baseline()
    gate = _gate_replica()
    # 门控逐位对 C-134 gate_cases（dens／leak0 不掉的旁证）
    gate_cmp: dict[str, Any] = {}
    for slug in CASES:
        old = base["gate"][slug] if isinstance(base["gate"], dict) else None
        new = gate[slug]
        if isinstance(old, dict):
            same = (
                old.get("cut_hits") == new["cut_hits"]
                and old.get("micro_gold_density") == new["micro_gold_density"]
                and old.get("avg_gold_density") == new["avg_gold_density"]
                and old.get("mean_gold_box_to_close")
                == new["mean_gold_box_to_close"]
                and old.get("n_leaks") == new["n_leaks"]
            )
            gate_cmp[slug] = {"bitwise_equal": bool(same), "old": old,
                              "new": new}
        else:
            gate_cmp[slug] = {"bitwise_equal": None, "old": None, "new": new}
        print(f"[腿0 门控比对] {slug}: bitwise={gate_cmp[slug]['bitwise_equal']}",
              flush=True)

    mirror_rows: list[dict[str, Any]] = []
    for slug in CASES:
        for qid in QIDS:
            row = _mirror(slug, qid)
            b = base["rows"][(slug, qid)]
            row["focus_off_vs_c134"] = (
                "IDENTICAL" if row["focus_off_ids"] == list(b["focus_ids"])
                else "DRIFT")
            row["face_off_vs_c134"] = (
                "BYTE_IDENTICAL" if row["face_off_sha8"] == b["face_sha8"]
                else "DRIFT")
            row["c134_focus_gold_n"] = b.get("focus_gold_n")
            # 锚：离线 before 金标数应与 C-134 真跑 focus_gold_n 一致
            row["gold_anchor_ok"] = (
                len(row["face_gold_before_ids"]) == int(b.get("focus_gold_n")
                                                        or -1))
            mirror_rows.append(row)
            print(f"[腿0 镜像] {slug}/{qid} cand={row['candidates_n']} "
                  f"k_top={row['k_top']} reserve={row['reserve_added']} "
                  f"final_n={row['final_n']} replay={row['replay_ok']} "
                  f"box不动={row['box_untouched']} "
                  f"off_face={row['face_off_vs_c134']} "
                  f"金标 before={len(row['face_gold_before_ids'])}"
                  f"→after={len(row['face_gold_after_ids'])} "
                  f"cut_gold={len(row['cut_gold_ids'])} "
                  f"锚={row['gold_anchor_ok']}", flush=True)
    return {"gate": gate, "gate_cmp": gate_cmp, "mirror": mirror_rows}


# ------------------------------------------------ 腿1：14B 真跑

def _real_pass(slug: str, qid: str) -> dict[str, Any]:
    from app.agents.base import Analyst
    from app.agents.prompts import render_segments_block
    from app.config import Settings
    from app.core.citation_check import check_evidence
    from app.ingest.official_case import load_official_case
    from app.llm.model_client import ModelClient
    from scripts.measure_s4_gates import lock_local

    print(lock_local(), flush=True)
    case = _case(CASE_MARKS[slug])
    qrow = next(q for q in _questions_from_conclusions(case)
                if q["question_id"] == qid)
    _gate_env()
    t0 = time.perf_counter()
    settings = Settings.from_env()
    settings.models = [MODEL_ID]
    settings.multi_box = False
    settings.second_pass_enabled = False
    settings.review_boost = False
    settings.llm_timeout_seconds = 600
    settings = settings.validate()
    if not bool(getattr(settings, "submit_top7", False)):
        raise AssertionError("C-140 真跑须开旗（出厂开）；读到关旗")
    d = load_official_case(case)
    d.question = qrow["question"]

    box, _pre, acc = _selection(d, c140=False)
    from app.core.submit_top7 import apply_submit_top7
    face_d = apply_submit_top7(d, enabled=True)
    assert face_d and face_d.get("enabled") is True
    focus = [str(x) for x in (acc.get("kg_focus_segment_ids") or [])]
    assert focus == face_d["final_ids"]
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

    gold, gids = _gold_ids(slug, qid)
    hit_para, hit_quote, hit_either = cited_hits(gold, d)
    l3 = sum(1 for k in gold.keys() if k in hit_either)
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
    oob_face = sorted(cited_ids - set(face_d["final_ids"]))
    oob_box = sorted(cited_ids - set(box))
    face_gold_after = sorted(set(face_d["final_ids"]) & gids)
    wl = (d.accounting or {}).get("window_ledger") or {}
    over = [n for n in (d.ingest_notes or [])
            if isinstance(n, dict) and n.get("kind") == "prompt_over_window"]
    row = {
        "slug": slug, "qid": qid,
        "surface_line": "test_tree(factory)+c140_top7",
        "box_n": len(box), "focus_n": len(focus),
        "k_top": face_d["k_top"], "reserve_added": face_d["reserve_added"],
        "final_n": face_d["final_n"],
        "focus_gold_n": len(face_gold_after),
        "face_chars": len(face), "face_sha8": _sha8(face),
        "denom": len(gold), "l3": l3,
        "cited_gold_ids": sorted(
            (str(p) if "#" in str(p) else f"{doc}#{p}") for doc, p in
            hit_either),
        "cited_n": len(cited_ids),
        "oob_face_ids": oob_face, "oob_box_ids": oob_box,
        "n_conclusions": len(d.conclusions),
        "n_evidences": len(d.evidences),
        "n_ev_check_fail": n_ev_fail,
        "fail_buckets": buckets,
        "server_input_tokens": wl.get("input_tokens"),
        "over_window": bool(over),
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    print(f"[腿1] {slug}/{qid} L3={l3}/{row['denom']} cited={row['cited_n']} "
          f"final_n={row['final_n']}(+{row['reserve_added']}) "
          f"带外face={len(oob_face)} 带外box={len(oob_box)} "
          f"核对失败={n_ev_fail} ({row['wall_s']}s)", flush=True)
    return row


def leg_real() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    partial = OUT / "c140_real_partial.json"
    if partial.exists():
        try:
            rows = json.loads(partial.read_text(encoding="utf-8"))["rows"]
            print(f"[腿1] 读回分段件 {len(rows)} 题续跑", flush=True)
        except (ValueError, KeyError):
            rows = []
    done = {(r["slug"], r["qid"]) for r in rows}
    for slug in CASES:
        for qid in QIDS:
            if (slug, qid) in done:
                print(f"[腿1] {slug}/{qid} 已有，跳", flush=True)
                continue
            rows.append(_real_pass(slug, qid))
            _partial_write("c140_real_partial.json", {"rows": rows})
    return rows


# ------------------------------------------------ 判表＋artifact

def _verdict(zero: dict[str, Any], real: list[dict[str, Any]]) -> dict[str, Any]:
    base = _baseline()
    mirror = zero["mirror"]

    # 闸①：final_n 回放（无对题＝min(7,候选)≤7；有对＝保位追加可回放）
    no_pair_ok = all(
        r["pair_reserve_n"] == 0 and r["final_n"] == r["k_top"] <= 7
        for r in mirror if r["pair_rows_n"] == 0)
    replay_ok = all(r["replay_ok"] for r in mirror)
    g1 = bool(no_pair_ok and replay_ok)

    # 闸②：dens／leak 逐位对 C-134；真跑带外（对 face）＝0
    dens_ok = all(
        v["bitwise_equal"] is True for v in zero["gate_cmp"].values())
    oob_face_ok = bool(real) and all(len(r["oob_face_ids"]) == 0
                                     for r in real)
    g2 = bool(dens_ok and oob_face_ok)

    # 闸③：金标评测臂——离线 face 金标 after 对 before 总数不掉；
    # 裁掉段含金标逐条记账（cut_gold_ids 在场即可回放）
    before_total = sum(len(r["face_gold_before_ids"]) for r in mirror)
    after_total = sum(len(r["face_gold_after_ids"]) for r in mirror)
    cut_gold_total = sum(len(r["cut_gold_ids"]) for r in mirror)
    anchor_ok = all(r["gold_anchor_ok"] for r in mirror)
    l3_new = sum(r["l3"] for r in real) if real else None
    l3_old = sum(int(r.get("l3") or 0) for r in base["rows"].values())
    g3 = bool(anchor_ok and after_total >= before_total)

    # 闸④：关旗回退——focus_off 序逐位、face_off sha 逐位、无 submit_top7
    off_ok = all(
        r["focus_off_vs_c134"] == "IDENTICAL"
        and r["face_off_vs_c134"] == "BYTE_IDENTICAL"
        for r in mirror)

    # 盒／tree17 不被机制改动（旁证）
    box_ok = all(r["box_untouched"] and r["t17_untouched"] for r in mirror)

    final_ns = [(r["slug"], r["qid"], r["final_n"], r["k_top"],
                 r["reserve_added"]) for r in mirror]
    verdict = {
        "g1_final_n_replay": g1, "g2_dens_leak_oob": g2,
        "dens_bitwise": bool(dens_ok),
        "g3_gold_face_no_drop": g3, "g4_off_fallback": bool(off_ok),
        "box_t17_untouched": bool(box_ok),
        "final_n_rows": final_ns,
        "gold_face_before_total": before_total,
        "gold_face_after_total": after_total,
        "cut_gold_total": cut_gold_total,
        "gold_anchor_ok": bool(anchor_ok),
        "l3_new_total": l3_new, "l3_c134_total": l3_old,
        "real_oob_face_total": (sum(len(r["oob_face_ids"]) for r in real)
                                if real else None),
        "real_oob_box_total": (sum(len(r["oob_box_ids"]) for r in real)
                               if real else None),
        "all_yes": bool(g1 and g2 and g3 and off_ok),
    }
    return verdict


def _render_md(payload: dict[str, Any]) -> str:
    v = payload["verdict"]
    zero = payload["zero"]
    real = payload.get("real") or []
    lines = [
        "# C-140 交卷硬 Top-7＋冲突成对保位——交账",
        "",
        f"- tip／枝：`{payload['tip']}`／`{payload['branch']}`",
        f"- 一行：{payload['one_line']}",
        "",
        "## 判表（件② 五闸）",
        "",
        f"- 闸① final_n 回放（无对≤7、有对保位可回放）：{v['g1_final_n_replay']}",
        f"- 闸② dens／leak 逐位对 C-134＋真跑带外(face)=0：{v['g2_dens_leak_oob']}",
        f"- 闸③ 金标评测臂 face 金标 after≥before（锚逐题"
        f"{v['gold_anchor_ok']}）：{v['g3_gold_face_no_drop']}",
        f"- 闸④ 关旗回退（focus 序逐位＋face sha 逐位＋无 submit_top7 键）："
        f"{v['g4_off_fallback']}",
        f"- 旁证：盒 rank_order／tree17_cite 逐位不动＝{v['box_t17_untouched']}",
        f"- 闸⑤ pytest 不新增红：见交付行（探针外独立跑）",
        "",
        "## 腿0 镜像（六题；id／计数／sha8；零表格）",
        "",
    ]
    for r in zero["mirror"]:
        lines.append(
            f"- {r['slug']}/{r['qid']}：候选 {r['candidates_n']}｜"
            f"k_top {r['k_top']}｜保位 {r['reserve_added']}｜"
            f"final_n {r['final_n']}｜off面 {r['face_off_vs_c134']}｜"
            f"金标 before {len(r['face_gold_before_ids'])} → after "
            f"{len(r['face_gold_after_ids'])}｜裁掉含金标 "
            f"{len(r['cut_gold_ids'])}｜盒内被裁 {r['box_dropped_n']}"
            f"（含金标 {len(r['box_dropped_gold_ids'])}）｜"
            f"replay {r['replay_ok']}")
    lines += [
        "",
        f"- 金标 face 合计：before {v['gold_face_before_total']} → "
        f"after {v['gold_face_after_total']}；裁掉段含金标 "
        f"{v['cut_gold_total']} 条（逐题 cut_gold_ids 在 json 回放）",
        "",
        "## 腿1 14B 真跑（六题；门控 env 组同 C-134）",
        "",
    ]
    if real:
        for r in real:
            lines.append(
                f"- {r['slug']}/{r['qid']}：L3 {r['l3']}/{r['denom']}｜"
                f"cited {r['cited_n']}｜final_n {r['final_n']}"
                f"(+{r['reserve_added']})｜带外face {len(r['oob_face_ids'])}"
                f"｜带外box {len(r['oob_box_ids'])}｜核对失败 "
                f"{r['n_ev_check_fail']}｜墙钟 {r['wall_s']}s")
        lines += [
            "",
            f"- L3 合计：新 {v['l3_new_total']} vs C-134 基线 "
            f"{v['l3_c134_total']}（单跑单臂，逐跑噪声未量——按 10-28 纪律"
            f"不据此说涨分；交叉读数看离线 face 金标）",
        ]
    else:
        lines.append("- （腿1 未跑／未交）")
    lines += [
        "",
        "## 诚实披露",
        "",
        "- final_n 上限：保位不设硬顶（工单「可变成 8／9…」按字面实现），"
        "逐题真数见 final_n_rows；超 9 的题在此注明——",
    ]
    over9 = [(s, q, n) for (s, q, n, _k, _r) in v["final_n_rows"] if n > 9]
    lines.append(
        f"- 超 9 题：{over9 if over9 else '无'}")
    lines += [
        "- dens 公式／pack 系数／MULTI_BOX 默认零改动；盒 rank_order 与 "
        "tree17_cite 逐位不动（旁证闸）",
        "- 真跑带外按两个口径记：对 final face（提示词只许名单内，应为 0）"
        "与对盒 rank_order（保位段引用会落在盒外，逐题披露）",
        "- 金标只活在量尺（本探针与 artifact），生产 submit_top7 accounting "
        "零金标、过 audit_forbidden_keys",
        "- 候选池＝kg_test_tree.rerank_order（C-140 起随 ensure_test_tree_submit "
        "落账；序尾补盒内缺员）；缺席回退 rank_order（candidates_source 披露）",
    ]
    return "\n".join(lines)


def _one_line(v: dict[str, Any], tip: str, branch: str) -> str:
    ns = v["final_n_rows"]
    ns_txt = "/".join(f"{s[:2]}{q.split('_')[1]}:{n}"
                      for s, q, n, _k, _r in ns)
    reserve_total = sum(r for (_s, _q, _n, _k, r) in ns)
    gold = (f"{v['gold_face_before_total']}→{v['gold_face_after_total']}"
            f"(cut_gold={v['cut_gold_total']})")
    return (
        f"{'YES' if v['all_yes'] else 'NO'}｜final_n={ns_txt}（保位合计"
        f"{reserve_total}）｜dens/leak="
        f"{'逐位' if v['dens_bitwise'] else '漂移'}"
        f"｜带外face={v['real_oob_face_total']}｜金标face {gold}"
        f"｜L3 {v['l3_new_total']} vs {v['l3_c134_total']}"
        f"｜tip {tip[:7]}／{branch}")


def _assemble(payload: dict[str, Any]) -> None:
    tip = payload["tip"]
    branch = payload["branch"]
    v = payload["verdict"]
    payload["one_line"] = _one_line(v, tip, branch)
    art_json = {
        "ticket": "C-140", "tip": tip, "branch": branch,
        "model": MODEL_ID, "env_group": ENV_GROUP,
        "one_line": payload["one_line"],
        "verdict": v, "zero": payload["zero"],
        "real": payload.get("real") or [],
    }
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "C140_top7_conflict_reserve.json").write_text(
        json.dumps(art_json, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (ART / "C140_top7_conflict_reserve.md").write_text(
        _render_md(payload) + "\n", encoding="utf-8")
    print(f"[assemble] artifacts/C140_top7_conflict_reserve."
          f"{{json,md}} 已写；one_line:\n{payload['one_line']}", flush=True)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--legs", choices=("zero", "real", "all", "assemble"),
                    default="all")
    args = ap.parse_args()
    tip = _git_tip()
    branch = _git_branch()
    if args.legs in ("zero", "all"):
        zero = leg_zero()
        _partial_write("c140_zero.json", {"zero": zero})
    else:
        zero = json.loads(
            (OUT / "c140_zero.json").read_text(encoding="utf-8"))["zero"]
    real: list[dict[str, Any]] = []
    if args.legs in ("real", "all"):
        real = leg_real()
    elif args.legs == "assemble":
        p = OUT / "c140_real_partial.json"
        if p.exists():
            real = json.loads(p.read_text(encoding="utf-8"))["rows"]
    payload = {"tip": tip, "branch": branch, "zero": zero, "real": real,
               "verdict": _verdict(zero, real)}
    _partial_write("c140_payload.json", payload)
    _assemble(payload)
    return 0


def _git_tip() -> str:
    import subprocess
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()


def _git_branch() -> str:
    import subprocess
    return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                          cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
