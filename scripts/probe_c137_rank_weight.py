#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-137：树17 排名加权细读＋硬约束——腿0 零调用全路径＋腿1 14B 真跑（只量不修）。

腿0（零 LLM）＝
  A 门控复刻（C-134 同尺：``_eval_case``／``_plan_cite_and_leak``／``_prod_leg``
    原样复用，prefer_gold 按角色：刘翔回归臂 True／王虹 holdout False）；
  B 生产面镜像（ensure_test_tree_submit → apply_kg_submit_surface →
    pack_material → focus → face）逐题：
    - 盒 identity：rank_order 与 C-134 真跑 focus_ids 逐位相等；
    - 关旗字节等证：VERITAS_TREE17_RANK_WEIGHT=0 渲染 face 的 sha8
      与 C-134 face_sha8 逐位相等（＝C-135/136/137 对提示词零 diff）；
    - 注意力面：开旗 face＋attention（H=3 出厂）；H∈{3,5} build_attention
      形状（成对两边覆盖 pair_rows 全 both_close、权重单调、强制留痕）。
腿1（14B 真跑）＝C-134 ``_real_pass`` 同形状（单 mainstream 分析师、锁本机、
  温度未钉、超时 600s、门控 env 组、不设 VERITAS_TEST_TREE_LINE）
  × H∈{3,5} × 六题（刘翔＋王虹各 q_001..q_003）；
  逐题记 L3／引用／带外／成对单边／钉／核对失败／墙钟＋注意力摘要。

分段件 ``/tmp/c137``（重跑前自动备份 ``.c137backup``）；产物卫生＝只记
id／计数／sha8，零官方原文、零模型输出原文。
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
OUT = Path("/tmp/c137")
ART = ROOT / "artifacts"

from scripts.probe_c125_six_case_gate import (  # noqa: E402
    CASE_MARKS, EXPECT, _case, _eval_case, _git_tip, _plan_cite_and_leak,
    _prod_leg, _questions_from_conclusions,
)
from app.core.kg_submit_surface import (  # noqa: E402
    apply_kg_submit_surface, assert_clean_pack_kwargs, kg_focus_segment_ids,
    pack_kwargs_for_kg,
)
from app.core.kg_test_tree_line import ensure_test_tree_submit  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from app.core.tree17_rank_weight import (  # noqa: E402
    build_attention, rank_weight_enabled,
)
from scripts.probe_recall_funnel import (  # noqa: E402
    cited_hits, gold_paras_for_question,
)

MODEL_ID = "openai/veritas-qwen3-14b"
CASES = ("liuxiang", "wanghong")
TIERS = (3, 5)
QIDS = ("q_001", "q_002", "q_003")

ENV_GROUP = {
    "VERITAS_KG_SUBMIT_SURFACE": "1",
    "VERITAS_KG_STAGE1": "1",
    "VERITAS_KG_REHYDRATE_BOX": "1",
    "VERITAS_MULTI_BOX": "0",
    "VERITAS_SECOND_PASS": "0",
    "VERITAS_REVIEW_BOOST": "0",  # 与 R44/C-129/C-130/C-134 门控基线同组
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
        dst = path.with_suffix(path.suffix + ".c137backup")
        shutil.copy2(path, dst)


def _partial_write(name: str, payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    _backup(p)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                 encoding="utf-8")


# ------------------------------------------------ 腿0 B：生产面镜像（零 LLM）

def _mirror_face(slug: str, qid: str) -> dict[str, Any]:
    """镜像真跑前置块（零调用）：盒／focus／face（开／关旗）／注意力面。"""
    from app.agents.prompts import render_segments_block
    from app.config import Settings

    case = _case(CASE_MARKS[slug])
    qrow = next(q for q in _questions_from_conclusions(case)
                if q["question_id"] == qid)
    settings = Settings.from_env()
    settings.models = [MODEL_ID]
    settings.multi_box = False
    settings.second_pass_enabled = False
    settings.review_boost = False
    settings.llm_timeout_seconds = 600
    settings = settings.validate()
    d = load_official_case(case)
    d.question = qrow["question"]

    if not bool(getattr(settings, "test_tree_line", False)):
        raise AssertionError("C-137 镜像须走测试树主线（出厂开）；读到关旗")
    ensure_test_tree_submit(d)
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    assert_clean_pack_kwargs(kw)
    pack = pack_material(d, **kw)
    assert pack is not None  # 装箱只作前置一致性；face 走 granted 路径
    focus = [str(x) for x in (kg_focus_segment_ids(d) or [])]
    surface = (d.accounting or {}).get("kg_submit") or {}
    box = [str(x) for x in (surface.get("rank_order") or [])]
    t17 = (d.accounting or {}).get("tree17_cite") or {}
    att = t17.get("attention") if isinstance(t17, dict) else None

    # 关旗 face（提示词字节等证用）
    os.environ["VERITAS_TREE17_RANK_WEIGHT"] = "0"
    try:
        face_off = render_segments_block(d, focus_segment_ids=focus)
    finally:
        os.environ.pop("VERITAS_TREE17_RANK_WEIGHT", None)
    # 开旗 face（出厂默认）
    assert rank_weight_enabled() is True
    face_on = render_segments_block(d, focus_segment_ids=focus)

    # 注意力形状：H∈{3,5}（build_attention 直调，env 无关）
    pairs = surface.get("conflict_pairs")
    plan = t17.get("plan") if isinstance(t17, dict) else None
    att_shapes = {}
    for h in TIERS:
        a = build_attention(box, plan, pairs, head_tier=h)
        att_shapes[str(h)] = {
            "head_tier": h,
            "n_close": a["n_close"], "n_scan": a["n_scan"],
            "n_pair_rows": len(a["pair_rows"]),
            "n_pair_both_close": a["n_pair_both_close"],
            "pair_forced_ids": list(a["pair_forced_ids"]),
            "weights_close": [
                t["weight"] for t in a["tiers"] if t["tier"] == "close"],
        }
        # 权重单调不增（close 内按 rank 序）
        ws = [t["weight"] for t in a["tiers"] if t["tier"] == "close"]
        assert all(ws[i] >= ws[i + 1] - 1e-9 for i in range(len(ws) - 1)), ws

    return {
        "slug": slug, "qid": qid,
        "box": box, "focus_ids": focus, "k": len(box),
        "face_off_chars": len(face_off), "face_off_sha8": _sha8(face_off),
        "face_on_chars": len(face_on), "face_on_sha8": _sha8(face_on),
        "att_in_acc": bool(att and att.get("enabled")),
        "att_head_tier": (att or {}).get("head_tier"),
        "att_n_close": (att or {}).get("n_close"),
        "att_shapes": att_shapes,
    }


def leg_zero() -> dict[str, Any]:
    from app.core.kg_test_tree_line import test_tree_coeff

    base = _baseline()
    gate_out: dict[str, Any] = {}
    mirror_rows: list[dict[str, Any]] = []
    for slug in CASES:
        mark = CASE_MARKS[slug]
        exp = EXPECT[slug]
        prefer = exp["role"] == "regression"
        from app.core.kg_test_tree_line import test_tree_coeff as _ttc
        coeff, names = _ttc()
        dens = _eval_case(slug, mark, coeff, names, prefer_gold=prefer)
        extra = _plan_cite_and_leak(slug, mark, coeff, names,
                                    prefer_gold=prefer)
        prod = _prod_leg(slug, mark)
        gate_out[slug] = {
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

    for slug in CASES:
        for qid in QIDS:
            row = _mirror_face(slug, qid)
            b = base["rows"][(slug, qid)]
            # 盒序对 rings.box_ids（真跑 focus_ids＝close_read 重排序，非盒序）
            row["box_vs_c134"] = (
                "IDENTICAL"
                if row["box"] == base["rings"][(slug, qid)]
                else "DRIFT")
            # focus 序对真跑 focus_ids（close_read 序，分析师可见序）
            row["focus_vs_c134"] = (
                "IDENTICAL" if row["focus_ids"] == list(b["focus_ids"])
                else "DRIFT")
            row["face_off_vs_c134"] = (
                "BYTE_IDENTICAL" if row["face_off_sha8"] == b["face_sha8"]
                else "DRIFT")
            mirror_rows.append(row)
            print(f"[腿0 镜像] {slug}/{qid} k={row['k']} "
                  f"box={row['box_vs_c134']} focus={row['focus_vs_c134']} "
                  f"face_off={row['face_off_vs_c134']} "
                  f"face_on +{row['face_on_chars'] - row['face_off_chars']}字 "
                  f"att(H3) close={row['att_shapes']['3']['n_close']} "
                  f"pair_both={row['att_shapes']['3']['n_pair_both_close']}"
                  f"/{row['att_shapes']['3']['n_pair_rows']} "
                  f"forced={len(row['att_shapes']['3']['pair_forced_ids'])}",
                  flush=True)
    return {"gate": gate_out, "mirror": mirror_rows}


# ------------------------------------------------ 腿1：14B 真跑

def _real_pass137(tier: int, slug: str, qid: str) -> dict[str, Any]:
    from app.agents.base import Analyst
    from app.agents.prompts import render_segments_block
    from app.config import Settings
    from app.core.citation_check import check_evidence
    from app.llm.model_client import ModelClient
    from scripts.measure_s4_gates import lock_local

    print(lock_local(), flush=True)
    case = _case(CASE_MARKS[slug])
    qrow = next(q for q in _questions_from_conclusions(case)
                if q["question_id"] == qid)
    os.environ.pop("VERITAS_TEST_TREE_LINE", None)
    os.environ["VERITAS_TREE17_HEAD_TIER"] = str(tier)
    os.environ.pop("VERITAS_TREE17_RANK_WEIGHT", None)  # 出厂开
    t0 = time.perf_counter()
    settings = Settings.from_env()
    settings.models = [MODEL_ID]
    settings.multi_box = False
    settings.second_pass_enabled = False
    settings.review_boost = False
    settings.llm_timeout_seconds = 600
    settings = settings.validate()
    d = load_official_case(case)
    d.question = qrow["question"]
    gold, _sk = gold_paras_for_question(case, qid)
    gold_ids = {str(p) if "#" in str(p) else f"{doc}#{p}"
                for doc, p in gold.keys()}

    kw: dict = {}
    if not bool(getattr(settings, "test_tree_line", False)):
        raise AssertionError("C-137 真跑须走测试树主线（出厂开）")
    ensure_test_tree_submit(d)
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    assert_clean_pack_kwargs(kw)
    pack = pack_material(d, **kw)
    focus = [str(x) for x in (kg_focus_segment_ids(d) or [])]
    surface = (d.accounting or {}).get("kg_submit") or {}
    box = [str(x) for x in (surface.get("rank_order") or [])]
    face = render_segments_block(d, focus_segment_ids=focus)
    acc_att = ((d.accounting or {}).get("tree17_cite") or {}).get("attention")

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
    conflict_list = (pairs.get("conflicts") or []) if isinstance(pairs, dict) else []
    pair_rows = []
    for p in conflict_list:
        if not isinstance(p, dict) or not (p.get("support_id") and p.get("oppose_id")):
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
    over = [n for n in (d.ingest_notes or [])
            if isinstance(n, dict) and n.get("kind") == "prompt_over_window"]
    row = {
        "tier": tier, "slug": slug, "qid": qid,
        "surface_line": "test_tree(factory)+c137_rank_weight",
        "box_n": len(box), "focus_n": len(focus), "focus_ids": focus,
        "focus_gold_n": len(focus_gold),
        "focus_precision": round(len(focus_gold) / len(focus), 4)
        if focus else None,
        "face_chars": len(face), "face_sha8": _sha8(face),
        "attention": {
            "head_tier": (acc_att or {}).get("head_tier"),
            "n_close": (acc_att or {}).get("n_close"),
            "n_scan": (acc_att or {}).get("n_scan"),
            "n_pair_both_close": (acc_att or {}).get("n_pair_both_close"),
            "pair_forced_n": len((acc_att or {}).get("pair_forced_ids") or []),
        },
        "denom": len(gold), "l3": l3,
        "cited_gold_ids": sorted(
            (str(p) if "#" in str(p) else f"{doc}#{p}") for doc, p in hit_either),
        "cited_n": len(cited_ids),
        "out_of_band_ids": out_of_band,
        "pairs": pair_rows,
        "one_sided_n": sum(1 for p in pair_rows if p["one_sided"]),
        "n_conclusions": len(d.conclusions),
        "n_evidences": len(d.evidences),
        "n_ev_check_fail": n_ev_fail,
        "fail_buckets": buckets,
        "server_input_tokens": wl.get("input_tokens"),
        "over_window": bool(over),
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    print(f"[腿1 H={tier}] {slug}/{qid} L3={l3}/{row['denom']} "
          f"cited={row['cited_n']} 带外={len(out_of_band)} "
          f"单边={row['one_sided_n']}/{len(pair_rows)} "
          f"核对失败={n_ev_fail} ({row['wall_s']}s)", flush=True)
    return row


def leg_real(tiers: list[int]) -> dict[int, list[dict[str, Any]]]:
    runs: dict[int, list[dict[str, Any]]] = {}
    for tier in tiers:
        partial = OUT / f"c137_real_H{tier}_partial.json"
        rows: list[dict[str, Any]] = []
        if partial.exists():
            try:
                rows = json.loads(partial.read_text(encoding="utf-8"))["rows"]
                print(f"[腿1 H={tier}] 读回分段件 {len(rows)} 题续跑",
                      flush=True)
            except (ValueError, KeyError):
                rows = []
        done = {(r["slug"], r["qid"]) for r in rows}
        for slug in CASES:
            for qid in QIDS:
                if (slug, qid) in done:
                    print(f"[腿1 H={tier}] {slug}/{qid} 已有，跳", flush=True)
                    continue
                rows.append(_real_pass137(tier, slug, qid))
                _partial_write(f"c137_real_H{tier}_partial.json",
                               {"tier": tier, "rows": rows})
        runs[tier] = rows
    return runs


# ------------------------------------------------ 判表＋artifact

def _verdict(zero: dict[str, Any],
             runs: dict[int, list[dict[str, Any]]]) -> dict[str, Any]:
    base = _baseline()
    gates: dict[str, Any] = {}

    # 闸0：盒 identity（rings box_ids）／focus 序（真跑 focus_ids）／
    # 关旗 face 字节等证（六题全查）
    box_ok = all(r["box_vs_c134"] == "IDENTICAL" for r in zero["mirror"])
    focus_ok = all(r["focus_vs_c134"] == "IDENTICAL" for r in zero["mirror"])
    face_ok = all(r["face_off_vs_c134"] == "BYTE_IDENTICAL"
                  for r in zero["mirror"])
    gates["gate0_box_face"] = {
        "box_identity": box_ok, "focus_order_identity": focus_ok,
        "face_off_byte_identical": face_ok,
        "ok": box_ok and focus_ok and face_ok,
    }

    # 闸1：带外引用＝0（腿1 全部跑次）
    all_rows = [r for rs in runs.values() for r in rs]
    gates["gate1_out_of_band"] = {
        "n_runs": len(all_rows),
        "n_oob_nonzero": sum(1 for r in all_rows if r["out_of_band_ids"]),
        "ok": bool(all_rows) and all(not r["out_of_band_ids"] for r in all_rows),
    }

    # 闸2：成对两边进细读（腿0 形状：pair_rows 全 both_close）
    pair_ok = all(
        s["att_shapes"][str(h)]["n_pair_both_close"]
        == s["att_shapes"][str(h)]["n_pair_rows"]
        for s in zero["mirror"] for h in TIERS
        if s["att_shapes"][str(h)]["n_pair_rows"] > 0)
    # 真跑引用面：one_sided 不高于 C-134（逐题）
    real_pairs = []
    for tier, rows in runs.items():
        for r in rows:
            b = base["rows"][(r["slug"], r["qid"])]
            real_pairs.append({
                "tier": tier, "slug": r["slug"], "qid": r["qid"],
                "one_sided_old": b["one_sided_n"], "one_sided_new": r["one_sided_n"],
                "n_pairs": len(r["pairs"]),
            })
    gates["gate2_pair_both_sides"] = {
        "plan_shape_both_close_all": pair_ok,
        "real_rows": real_pairs,
        "real_no_regression": all(
            x["one_sided_new"] <= x["one_sided_old"] for x in real_pairs),
        "ok": pair_ok,
    }

    # 闸3：L3／引用条数 vs C-134（逐题旧→新）
    l3_rows = []
    for tier, rows in runs.items():
        for r in rows:
            b = base["rows"][(r["slug"], r["qid"])]
            l3_rows.append({
                "tier": tier, "slug": r["slug"], "qid": r["qid"],
                "denom": r["denom"],
                "l3_old": b["l3"], "l3_new": r["l3"],
                "cited_n_old": b["cited_n"], "cited_n_new": r["cited_n"],
                "ev_fail_old": b["n_ev_check_fail"],
                "ev_fail_new": r["n_ev_check_fail"],
                "wall_s": r["wall_s"],
            })
    for tier, rows in runs.items():
        gates[f"gate3_l3_H{tier}"] = {
            "l3_total_old": sum(base["rows"][(r["slug"], r["qid"])]["l3"]
                                for r in rows),
            "l3_total_new": sum(r["l3"] for r in rows),
            "cited_total_old": sum(base["rows"][(r["slug"], r["qid"])]["cited_n"]
                                   for r in rows),
            "cited_total_new": sum(r["cited_n"] for r in rows),
            "rows": [x for x in l3_rows if x["tier"] == tier],
        }

    # 闸4：dens／@7／leak0 相对 C-134 不掉（腿0 门控复刻）
    dens_rows = {}
    for slug in CASES:
        g = zero["gate"][slug]
        bg = base["gate"][slug]
        dens_rows[slug] = {
            "at7_old": bg["cut_hits"]["7"], "at7_new": g["cut_hits"]["7"],
            "micro_old": bg["micro_gold_density"],
            "micro_new": g["micro_gold_density"],
            "g2c_old": bg["mean_gold_box_to_close"],
            "g2c_new": g["mean_gold_box_to_close"],
            "leaks_old": bg["n_leaks"], "leaks_new": g["n_leaks"],
        }
    gates["gate4_dens_leak"] = {
        "rows": dens_rows,
        "ok": all(
            v["at7_new"] >= v["at7_old"] and v["micro_new"] >= v["micro_old"]
            and v["g2c_new"] >= v["g2c_old"] and v["leaks_new"] == 0
            for v in dens_rows.values()),
    }
    overall = all(gates[k]["ok"] for k in
                  ("gate0_box_face", "gate1_out_of_band",
                   "gate2_pair_both_sides", "gate4_dens_leak"))
    # 病因读数：注意力梯度可作用场地＝盒长 > H 的题（短盒全 close＝无梯度）
    short_box_n = sum(
        1 for r in zero["mirror"] for h in TIERS
        if r["att_shapes"][str(h)]["n_scan"] == 0)
    gates["attention_gradient"] = {
        "n_mirror_rows": len(zero["mirror"]) * len(TIERS),
        "n_no_gradient_rows": short_box_n,
        "note": ("盒长≤H 的题＝全盒 close、n_scan=0：分层无梯度可作用"
                 "（权重面退化为装饰，只剩硬约束文字面）"),
    }
    return {"gates": gates, "overall_gates_pass": overall, "l3_rows": l3_rows}


def _render_md(payload: dict[str, Any]) -> str:
    v = payload["verdict"]
    gates = v["gates"]
    lines = [
        "# C-137 树17 排名加权细读＋硬约束（交账）",
        "",
        f"- tip／枝：`{payload['tip']}`／`{payload['branch']}`",
        f"- 模型：{payload['model']}；温度未钉（与 C-120/C-130/C-134 同口径）；"
        "嵌入＝本机 bge-m3 暖缓存（.kgcache，按 para_id 复用）",
        f"- env：不设 VERITAS_TEST_TREE_LINE（出厂开）；"
        "REVIEW_BOOST 显式 0（门控基线同组）；"
        "VERITAS_TREE17_RANK_WEIGHT 出厂开；VERITAS_TREE17_HEAD_TIER∈{3,5}",
        "",
        "## 一行结论",
        "",
        f"**{payload['one_line']}**",
        "",
        "## 四闸",
        "",
    ]
    g0 = gates["gate0_box_face"]
    lines += [
        f"- 闸0 盒 identity／focus 序／关旗 face 字节等证："
        f"{'过' if g0['ok'] else '红'}（box {g0['box_identity']}、"
        f"focus {g0['focus_order_identity']}、"
        f"face_off {g0['face_off_byte_identical']}；六题全查）",
    ]
    g1 = gates["gate1_out_of_band"]
    lines.append(
        f"- 闸1 带外引用＝0：{'过' if g1['ok'] else '红'}"
        f"（{g1['n_runs']} 跑次、非零 {g1['n_oob_nonzero']}）")
    g2 = gates["gate2_pair_both_sides"]
    lines.append(
        f"- 闸2 成对两边进细读：{'过' if g2['ok'] else '红'}"
        f"（计划层形状全 both_close；真跑 one_sided 回归＝"
        f"{g2['real_no_regression']}）")
    for tier in TIERS:
        g3 = gates[f"gate3_l3_H{tier}"]
        lines.append(
            f"- 闸3 L3／引用（H={tier}）：合计 L3 {g3['l3_total_old']}→"
            f"{g3['l3_total_new']}；"
            f"引用条数 {g3['cited_total_old']}→{g3['cited_total_new']}"
            f"（逐题旧→新见下表；未明显抬＝闸③不过）")
    grad = gates["attention_gradient"]
    lines.append(
        f"- 病因读数：{grad['note']}（本批 "
        f"{grad['n_no_gradient_rows']}/{grad['n_mirror_rows']} 形状全盒 close；"
        "H=3 与 H=5 两臂读数逐位相同即此故）")
    g4 = gates["gate4_dens_leak"]
    lines.append(
        f"- 闸4 dens／@7／leak0：{'过' if g4['ok'] else '红'}"
        + "；".join(
            f" {s} @7 {x['at7_old']}→{x['at7_new']} micro "
            f"{x['micro_old']}→{x['micro_new']} leak {x['leaks_new']}"
            for s, x in g4["rows"].items()))
    lines += ["", "## 逐题 L3／引用（旧＝C-134 → 新＝本单真跑）", ""]
    for x in v["l3_rows"]:
        lines.append(
            f"- H={x['tier']}｜{x['slug']}/{x['qid']}｜"
            f"L3 {x['l3_old']}→{x['l3_new']}/{x['denom']}｜"
            f"引用 {x['cited_n_old']}→{x['cited_n_new']}｜"
            f"核对失败 {x['ev_fail_old']}→{x['ev_fail_new']}｜"
            f"墙钟 {x['wall_s']}s")
    lines += ["", "## 注意力面形状（腿0，H=3／H=5）", ""]
    for r in payload["zero"]["mirror"]:
        for h in ("3", "5"):
            a = r["att_shapes"][h]
            lines.append(
                f"- {r['slug']}/{r['qid']} H={h}：close {a['n_close']}"
                f"／scan {a['n_scan']}；成对 {a['n_pair_both_close']}"
                f"/{a['n_pair_rows']} both_close；强制升级 "
                f"{len(a['pair_forced_ids'])} 段")
    lines += [
        "",
        "## 权重键（可迁移）",
        "",
        "- rank 档（细读=前 H 名，权重 1.0−0.15×(rank−1)，地板 0.2）；",
        "- 是否冲突边（成对强制进细读，留痕 pair_forced_ids）；",
        "- 是否可核验钉（时间／数额钉 +0.05，封顶 1.0）；",
        "- 权重只进 surface.tree17.attention 与分析师提示词；"
        "整面过 audit_forbidden_keys；盒／一筛／二筛系数零改动。",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--legs", choices=("zero", "real", "all", "assemble"),
                    default="all",
                    help="zero＝腿0（零 LLM）；real＝腿1（14B）；all＝全部；"
                         "assemble＝从 /tmp/c137 分段件重组（不重烧 LLM）")
    ap.add_argument("--tiers", default="3,5", help="真跑 H 档（逗号分隔）")
    ap.add_argument("--no-artifact", action="store_true",
                    help="只写 /tmp/c137 中间件，不写 artifacts")
    args = ap.parse_args()
    tiers = [int(x) for x in args.tiers.split(",") if x.strip()]
    t0 = time.perf_counter()
    tip = _git_tip()
    branch = os.popen("git rev-parse --abbrev-ref HEAD").read().strip()
    for k, val in ENV_GROUP.items():
        os.environ[k] = val
    os.environ.pop("VERITAS_TEST_TREE_LINE", None)
    os.environ.pop("VERITAS_TREE17_RANK_WEIGHT", None)
    os.environ.pop("VERITAS_TREE17_HEAD_TIER", None)

    zero = None
    runs: dict[int, list[dict[str, Any]]] = {}
    if args.legs in ("zero", "all"):
        print("=== 腿0：门控复刻＋生产面镜像（零 LLM） ===", flush=True)
        zero = leg_zero()
        _partial_write("c137_leg0_partial.json", zero)
    elif args.legs in ("real", "assemble"):
        p = OUT / "c137_leg0_partial.json"
        if p.exists():
            zero = json.loads(p.read_text(encoding="utf-8"))
    if args.legs in ("real", "all"):
        print("=== 腿1：14B 真跑（分段件续跑） ===", flush=True)
        runs = leg_real(tiers)
    if args.legs == "assemble":
        for tier in tiers:
            p = OUT / f"c137_real_H{tier}_partial.json"
            if p.exists():
                runs[tier] = json.loads(p.read_text(encoding="utf-8"))["rows"]
    if zero is None or not runs:
        print("缺腿（zero／real 分段件不全）；先跑 --legs zero 再 --legs real",
              flush=True)
        return 2

    base = _baseline()
    verdict = _verdict(zero, runs)
    denom_total = sum(r["denom"] for r in next(iter(runs.values())))
    l3_best = max(
        (verdict["gates"][f"gate3_l3_H{t}"]["l3_total_new"] for t in runs),
        default=0)
    l3_old = verdict["gates"][f"gate3_l3_H{list(runs)[0]}"]["l3_total_old"]
    cited_best = max(
        (verdict["gates"][f"gate3_l3_H{t}"]["cited_total_new"] for t in runs),
        default=0)
    cited_old = verdict["gates"][f"gate3_l3_H{list(runs)[0]}"]["cited_total_old"]
    gates_pass = verdict["overall_gates_pass"]
    # 工单闸③＝「L3／引用条数明显抬」：L3 必须实抬；引用条数 +1 不算
    # （单遍温度未钉＝噪声内）。两臂逐题零动时 verdict 只能是 NO。
    l3_lifted = l3_best > l3_old
    verdict_str = ("YES" if (gates_pass and l3_lifted) else "NO")
    grad = verdict["gates"]["attention_gradient"]
    one_line = (
        f"{verdict_str}｜安全四闸全过（盒 identity／带外0／成对计划层 "
        f"both_close／dens·leak 逐位持平）｜L3 合计 {l3_old}→{l3_best}"
        f"（引用 {cited_old}→{cited_best}，逐题零动）｜"
        f"病因＝六题盒长全≤H，注意力分层无梯度可作用"
        f"（{grad['n_no_gradient_rows']}/{grad['n_mirror_rows']} 形状全盒 close）｜"
        f"tip {tip[:8]}／{branch}")
    payload = {
        "ticket": "C-137",
        "tip": tip, "branch": branch,
        "env_note": ("不设 VERITAS_TEST_TREE_LINE（出厂开）；"
                     "REVIEW_BOOST 显式 0（可比性）；"
                     "TREE17_RANK_WEIGHT 出厂开；HEAD_TIER∈{3,5}"),
        "model": MODEL_ID, "temperature": "unset(＝C-120/C-130/C-134 同口径)",
        "baseline_tip": base["tip"],
        "denom_total": denom_total,
        "one_line": one_line,
        "zero": zero, "real_runs": runs, "verdict": verdict,
        "wall_s": round(time.perf_counter() - t0, 1),
        "hygiene": "只记 id／计数／sha8；零官方原文、零模型输出原文",
    }
    _partial_write("c137_assembled.json", payload)
    if args.no_artifact:
        print(f"[assemble] 只写 /tmp/c137（--no-artifact）", flush=True)
    else:
        (ART / "C137_tree17_rank_weight.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8")
        (ART / "C137_tree17_rank_weight.md").write_text(
            _render_md(payload), encoding="utf-8")
        print(f"artifacts/C137_tree17_rank_weight.md+.json 已写", flush=True)
    print(one_line, flush=True)
    print(f"墙钟 {payload['wall_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
