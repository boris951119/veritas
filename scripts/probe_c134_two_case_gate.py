#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-134：两案并线全链路复验＋树17 旧症是否仍在（C-133 合 main 后；本地 14B 零现金）。

三腿（全部复用现成闸，勿平行管线）：
  腿0 门控复刻＝C-125 `_eval_case`／`_plan_cite_and_leak`／`_prod_leg` 原样复用
      （R44 同尺：刘翔回归臂 prefer_gold 固定 k=7；王虹 holdout density_cut）。
  腿1 环证据＝按 build_test_tree_surface 同块序镜像走一遍（切／标／扩／一筛／
      二筛／窄面／tree17），每题落环 0-6 证据；**镜像盒与生产入口盒断言逐位相等**，
      相等则环证据＝生产证据。金标只进量尺（gold_ids 不进生产调用）。
  腿2 真跑＝C-130 run_pass 同形状（单 mainstream 分析师、锁本机、温度未钉、
      超时 600s、门控 env 组），**不设 VERITAS_TEST_TREE_LINE**（出厂开）；
      逐题记症状 A-F 证据（带宽外引用／成对单边／核验钉优先／采信标注／
      可用密度／名单准度）＋引文核对分桶＋服务端 tok＋墙钟。

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
OUT = Path("/tmp/c134")

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
from app.kg_lab.case_lexicon import lexicon_for_question  # noqa: E402
from app.kg_lab.event_frame import extract_event_frame  # noqa: E402
from app.kg_lab.index_build import (  # noqa: E402
    KgIndex, build_corpus_rows, keyword_expand_query,
)
from app.kg_lab.intent_routes import classify_route  # noqa: E402
from app.kg_lab.layer_boundary import (  # noqa: E402
    audit_forbidden_keys, stage2_box_export,
)
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.portable_tags import apply_portable_features  # noqa: E402
from app.kg_lab.query_expand import rule_paraphrase_questions  # noqa: E402
from app.kg_lab.r8_fit import augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import apply_r9  # noqa: E402
from app.kg_lab.source_role import _meta_from_row  # noqa: E402
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from app.kg_lab.stage2_authority import authority_rerank  # noqa: E402
from app.kg_lab.tree17_cite import apply_tree17_cite  # noqa: E402
from scripts.probe_recall_funnel import (  # noqa: E402
    cited_hits, gold_paras_for_question,
)

MODEL_ID = "openai/veritas-qwen3-14b"
CASES = ("liuxiang", "wanghong")
DROP_EPS = 0.02

# C-129 计划层参照（artifacts/C129_two_case_smoke；R44 式回归臂口径）
C129_PLAN = {
    "liuxiang": {"list_precision": 0.5714, "gold_to_close": 1.0},
    "wanghong": {"list_precision": 0.8571, "gold_to_close": 1.0},
}
# C-130 开臂（＝测试树生产面）真跑参照——与 C-134 真跑同臂可比；
# 现抄自 artifacts/C130_tree17_measure.json paired_runs（face 确定性＝逐位同）。
C130_ON_ARM = {
    ("liuxiang", "q_003"): {"focus_precision": 0.6667, "l3_mean": 2.0,
                            "fail_rate": 0.0},
}


def _sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _gold_ids(case: Path, qid: str) -> tuple[dict, set[str]]:
    gold, _sk = gold_paras_for_question(case, qid)
    ids = {str(p) if "#" in str(p) else f"{doc}#{p}" for doc, p in gold.keys()}
    return gold, ids


def _universe_for(case: Path, question: str) -> tuple[Any, set[str]]:
    from app.kg_lab.slices import pack_selected_for_question
    d = load_official_case(case)
    d.question = question
    return d, {str(x) for x in (pack_selected_for_question(d, question) or [])}


# ------------------------------------------------ 腿1：环 0-6 证据（镜像＋等价断言）

def _ring_evidence(slug: str, mark: str, qid: str) -> dict[str, Any]:
    case = _case(mark)
    qrow = next(q for q in _questions_from_conclusions(case)
                if q["question_id"] == qid)
    question = qrow["question"]
    gold, gold_ids = _gold_ids(case, qid)
    l2 = sorted(g for g in gold_ids)  # 全量金标（量尺侧）；L1 下面按 universe 收窄
    d, universe = _universe_for(case, question)
    rows = build_corpus_rows(d, case_slug=slug, para_ids=universe)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    sub_rows = [r for r in rows if r["para_id"] in universe]
    sub = KgIndex(slug, sub_rows)
    sub.embeddings = {pid: v for pid, v in index.embeddings.items()
                      if pid in universe}
    # 环0 切片
    max_row_chars = max((len(str(r.get("text") or "")) for r in rows), default=0)
    l1_gold = sorted(g for g in gold_ids if g in universe)
    # 环2 扩写披露＝读生产 accounting（下方 ensure_test_tree_submit 后取数；
    # 旧口径的独立量测已并入 ring2 的 disclosure_matches_independent）
    # 环3 一筛（与生产同参）
    fr = fuse_r19(sub, question, use_llm_views=False, neighbor_window=1)
    submit_ranked = fr["ranked"]
    pool_ranked = fr.get("pool_ranked") or fr["ranked"]
    pool20 = [p for p, _sc in pool_ranked[:20]]
    frame = extract_event_frame(question)
    route = classify_route(question, frame)
    bundle = build_bundle(sub_rows, submit_ranked, question, frames=True,
                          prefer_ids=None, case_slug=slug)
    by_row = {r["para_id"]: r for r in sub_rows}
    lex = lexicon_for_question(question, case_slug=slug)
    for pid, _sc in pool_ranked[:60]:
        if pid in bundle["metas"]:
            continue
        row = by_row.get(pid)
        if row:
            bundle["metas"][pid] = _meta_from_row(row, lex=lex)
            bundle["feats"].setdefault(pid, {})
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(x.get("doc_id")): str(x.get("content_url") or "") for x in raw}
    publish_of = {str(x.get("doc_id")): str(x.get("publish_time") or "")
                  for x in raw}
    augment_features(bundle["feats"], bundle["metas"], url_of)
    apply_r9(bundle["feats"], bundle["metas"], question)
    apply_portable_features(bundle["feats"], bundle["metas"], url_of, question,
                            frame, publish_of=publish_of)
    from app.core.kg_test_tree_line import test_tree_coeff
    coeff, names = test_tree_coeff()
    bundle["qid"] = qid
    bundle["question"] = question
    bundle["l2"] = []
    stage1 = evaluate([bundle], coeff, k7=7, k15=15, names=names)
    ranked = stage1["ranked"][qid]
    texts = {pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
             for pid in set([p for p, _ in ranked[:40]]
                            + [p for p, _ in pool_ranked[:40]])}
    out = authority_rerank(
        ranked, pool_ranked, texts=texts, feats=bundle["feats"],
        metas=bundle["metas"], question=question, frame=frame, url_of=url_of,
        publish_of=publish_of, pool=20, k=20,
        head_keep=1, max_inject=8, density_cut=True, gold_ids=None,
        k_min=3, k_max=7,
    )
    order = [row["id"] for row in out["order"]]
    dens = out.get("density") if out.get("density_cut") else None
    dens = dens or {}
    k_sel = int(dens.get("k") or 7) if dens else 7
    box = list(out.get("top_ids") or dens.get("submission") or order[:k_sel]) \
        if dens else order[:k_sel]
    if not box:
        box = order[:k_sel]
    # 环4 二筛
    raw_pairs = out.get("conflict_pairs") or {}
    conflicts = raw_pairs.get("conflicts") or [] if isinstance(raw_pairs, dict) else []
    paired = [p for p in conflicts
              if isinstance(p, dict) and p.get("support_id") and p.get("oppose_id")]
    preferred = [p for p in conflicts
                 if isinstance(p, dict) and p.get("preferred")]
    # 环5/6 窄面＋tree17（生产同参：gold_ids=None）
    box_export = stage2_box_export(out)
    box_export = {**box_export, "box_ids": list(box), "k": k_sel}
    leaks_s2 = audit_forbidden_keys(box_export)
    t17 = apply_tree17_cite(
        box, metas=bundle["metas"], question=question, anchors=route.anchors,
        align_to_box=True, gold_ids=None, support_ids=None,
    )
    plan = t17.get("plan") or {}
    close = list(plan.get("close_read") or [])
    # 生产入口面（零金标）＋等价断言——C-135 起走 ensure_test_tree_submit
    # （＝生产 accounting 写入路径；build 结果与 build_test_tree_surface 同一 dict）
    d2 = load_official_case(case)
    d2.question = question
    prod = ensure_test_tree_submit(d2, case_slug=slug)
    equiv_box = list(prod["box"]) == list(box)
    equiv_k = int(prod["k"]) == int(k_sel)
    equiv_close = list(prod["close_read"]) == list(close)
    # 环2 生产 accounting 披露（C-135）：键集非空＋与独立复算逐键一致
    expand_acc = ((getattr(d2, "accounting", None) or {})
                  .get("kg_test_tree") or {}).get("expand")
    acc_keys = sorted(expand_acc.keys()) if isinstance(expand_acc, dict) else []
    q_exp_prod = keyword_expand_query(question, sub_rows)
    para_prod = rule_paraphrase_questions(question, n=1)
    match_terms = (isinstance(expand_acc, dict)
                   and expand_acc.get("terms_n") == len(str(q_exp_prod).split()))
    match_para = (isinstance(expand_acc, dict)
                  and expand_acc.get("paraphrase_n") == len(para_prod))
    match_enabled = (isinstance(expand_acc, dict)
                     and expand_acc.get("enabled") is True)
    disclosure_match = bool(acc_keys) and match_terms and match_para \
        and match_enabled
    # 环1 标签（盒内 meta 覆盖率）
    def _nz(pid: str, key: str) -> bool:
        v = (bundle["metas"].get(pid) or {}).get(key)
        return bool(v)
    ring1 = {
        "n_box": len(box),
        "role_nonempty": sum(1 for p in box if _nz(p, "role")),
        "fine_role_nonempty": sum(1 for p in box if _nz(p, "fine_role")),
        "portable_role_nonempty": sum(1 for p in box if _nz(p, "portable_role")),
        "channel_nonempty": sum(1 for p in box if _nz(p, "channel")),
        "signals_nonempty": sum(1 for p in box if _nz(p, "signals")),
    }
    # 症状 C 量尺：核验钉（feats）
    nail_keys = ("has_time_nail", "has_number_nail", "verifiability")
    nail_ids: set[str] = set()
    for pid in box:
        f = bundle["feats"].get(pid) or {}
        if any(bool(f.get(kk)) for kk in nail_keys if kk in f):
            nail_ids.add(pid)
        elif f.get("verifiability"):
            try:
                if float(f["verifiability"]) >= 0.5:
                    nail_ids.add(pid)
            except (TypeError, ValueError):
                pass
    gold_in_box = [g for g in l2 if g in box]
    gold_in_pool = [g for g in l2 if g in pool20]
    gold_in_close = [g for g in l2 if g in close]
    row = {
        "slug": slug, "qid": qid,
        "ring0": {
            "rows_n": len(rows), "universe_n": len(universe),
            "max_row_chars": max_row_chars,
            "gold_total": len(gold_ids),
            "l1_gold_in_universe_n": len(l1_gold),
            "l1_ratio": round(len(l1_gold) / len(gold_ids), 4)
            if gold_ids else None,
            "l1_missing_ids": sorted(set(gold_ids) - set(l1_gold)),
        },
        "ring1": ring1,
        "ring2": {
            "expand_terms_n": len(str(q_exp_prod).split())
            if str(q_exp_prod).strip() else 0,
            "paraphrase_n": len(para_prod),
            "accounting_expand_keys": acc_keys,
            "disclosure_matches_independent": disclosure_match,
            "note": "C-135 已落：accounting.kg_test_tree.expand 三键"
                    "（enabled/terms_n/paraphrase_n，只记计数不记词原文）；"
                    "terms_n＝canonical 扩写词数（生产同 rows 口径）",
        },
        "ring3": {
            "pool_n": len(pool_ranked), "pool20_n": len(pool20),
            "gold_in_pool_n": len(gold_in_pool),
            "pool_missing_gold_ids": sorted(set(l2) - set(pool20)),
            "stage1_names_n": len(names),
        },
        "ring4": {
            "k": k_sel, "n_core": dens.get("n_core"),
            "n_filler": dens.get("n_filler"),
            "proxy_density": dens.get("density"),
            "met_target": dens.get("met_target"),
            "n_pairs": len(conflicts), "n_pairs_paired": len(paired),
            "n_pairs_preferred": len(preferred),
            "pairs_in_close": [
                {"support_id": p.get("support_id"),
                 "oppose_id": p.get("oppose_id"),
                 "both_in_close": bool(p.get("support_id") in close
                                       and p.get("oppose_id") in close)}
                for p in paired],
            "box_is_order_head": list(order[:k_sel]) == list(box),
        },
        "ring5": {
            "leaks_s2": len(leaks_s2),
            "surface_keys": sorted((prod["surface"] or {}).keys()),
            "hints_keys": sorted((prod["hints"] or {}).keys()),
            "n_pairs_surface": int(prod["n_pairs"]),
        },
        "ring6": {
            "close_n": len(close), "close_ids": close,
            "gold_in_close_n": len(gold_in_close),
            "gold_to_close_prod": round(
                len(gold_in_close) / len(gold_in_box), 4)
            if gold_in_box else None,
            "list_precision_prod": round(len(gold_in_close) / len(close), 4)
            if close else None,
            "nail_ids_in_box": sorted(nail_ids),
            "nail_in_close_n": len(nail_ids & set(close)),
            "tree17_keys": sorted(
                (prod["surface"].get("tree17") or {}).keys())
            if isinstance(prod["surface"], dict) else [],
        },
        "box_ids": list(box),
        "equiv_prod_entry": {"box": equiv_box, "k": equiv_k,
                             "close": equiv_close},
    }
    print(f"… 环 {slug}/{qid} k={k_sel} L1={row['ring0']['l1_ratio']} "
          f"池内金标={len(gold_in_pool)}/{len(l2)} close={len(close)} "
          f"prec={row['ring6']['list_precision_prod']} "
          f"等价={all(row['equiv_prod_entry'].values())}", flush=True)
    return row


# ------------------------------------------------ 腿2：14B 真跑（生产形状）

def _real_pass(slug: str, mark: str, qid: str, ring: dict[str, Any]) -> dict[str, Any]:
    from app.agents.base import Analyst
    from app.agents.prompts import render_segments_block
    from app.config import Settings
    from app.core.citation_check import check_evidence
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
    settings = settings.validate()
    d = load_official_case(case)
    d.question = qrow["question"]
    gold, gold_ids = _gold_ids(case, qid)

    kw: dict = {}
    if bool(getattr(settings, "kg_submit_surface", True)):
        if bool(getattr(settings, "test_tree_line", False)):
            from app.core.kg_test_tree_line import ensure_test_tree_submit
            ensure_test_tree_submit(d)
        else:
            raise AssertionError("C-134 真跑须走测试树主线（出厂开）；读到关旗＝环境污染")
        apply_kg_submit_surface(d, enabled=True)
        kw = pack_kwargs_for_kg(d)
        assert_clean_pack_kwargs(kw)
    pack = pack_material(d, **kw)
    focus = [str(x) for x in (kg_focus_segment_ids(d) or [])]
    surface = (d.accounting or {}).get("kg_submit") or {}
    box = [str(x) for x in (surface.get("rank_order") or [])]
    close = list(ring["ring6"]["close_ids"])
    nails = set(ring["ring6"]["nail_ids_in_box"])
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
            key = None
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
    # 症状 A：带宽外引用（引用 ⊄ 交卷盒）
    out_of_band = sorted(cited_ids - set(box))
    # 症状 B：成对单边
    pairs = (surface.get("conflict_pairs") or {})
    conflict_list = pairs.get("conflicts") or [] if isinstance(pairs, dict) else []
    pair_rows = []
    for p in conflict_list:
        if not isinstance(p, dict) or not (p.get("support_id") and p.get("oppose_id")):
            continue
        s_c = p["support_id"] in cited_ids
        o_c = p["oppose_id"] in cited_ids
        pair_rows.append({
            "support_id": p["support_id"], "oppose_id": p["oppose_id"],
            "support_cited": s_c, "oppose_cited": o_c,
            "preferred": str(p.get("preferred") or ""),
            "one_sided": bool(s_c) != bool(o_c),
        })
    # 症状 C：核验钉优先
    nail_in_close = sorted(nails & set(close))
    nail_cited = sorted(nails & cited_ids)
    # 症状 D：采信/对立标注（单分析师形状无标注面）
    n_conclusions = len(d.conclusions)
    # 症状 E/F：可用密度／名单准度（真跑 focus＝close）
    focus_gold = sorted(set(focus) & gold_ids)
    wl = (d.accounting or {}).get("window_ledger") or {}
    pw = (d.accounting or {}).get("prompt_window") or {}
    over = [n for n in (d.ingest_notes or [])
            if isinstance(n, dict) and n.get("kind") == "prompt_over_window"]
    row = {
        "slug": slug, "qid": qid,
        "surface_line": "test_tree(factory)",
        "box_n": len(box), "focus_n": len(focus), "focus_ids": focus,
        "focus_gold_n": len(focus_gold),
        "focus_precision": round(len(focus_gold) / len(focus), 4)
        if focus else None,
        "face_chars": len(face), "face_sha8": _sha8(face),
        "denom": len(gold), "l3": l3,
        "cited_gold_ids": sorted(
            (str(p) if "#" in str(p) else f"{doc}#{p}") for doc, p in hit_either),
        "cited_n": len(cited_ids),
        "out_of_band_ids": out_of_band,
        "pairs": pair_rows,
        "one_sided_n": sum(1 for p in pair_rows if p["one_sided"]),
        "nail_ids": sorted(nails),
        "nail_in_close_n": len(nail_in_close),
        "nail_cited_n": len(nail_cited),
        "n_conclusions": n_conclusions,
        "stance_labels": "single_analyst_shape(无标注面)＝D 不可判",
        "n_evidences": len(d.evidences),
        "n_ev_check_fail": n_ev_fail,
        "fail_buckets": buckets,
        "server_input_tokens": wl.get("input_tokens"),
        "over_window": bool(over),
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    print(f"… 真跑 {slug}/{qid} focus={len(focus)} "
          f"prec={row['focus_precision']} L3={l3}/{row['denom']} "
          f"带外={len(out_of_band)} 单边对={row['one_sided_n']}/{len(pair_rows)} "
          f"钉 close={len(nail_in_close)}/{len(nails)} "
          f"核对失败={n_ev_fail} ({row['wall_s']}s)", flush=True)
    return row


# ------------------------------------------------ 症状判表

def _symptom_table(rings: list[dict], runs: list[dict]) -> list[dict]:
    table: list[dict] = []
    by_q_ring = {(r["slug"], r["qid"]): r for r in rings}
    for run in runs:
        slug, qid = run["slug"], run["qid"]
        ring = by_q_ring[(slug, qid)]
        c129 = C129_PLAN[slug]
        # A 带宽外引用
        a_state = "仍在" if run["out_of_band_ids"] else "已消"
        table.append({
            "sym": "A_带宽外引用", "slug": slug, "qid": qid, "state": a_state,
            "evidence": f"带外 {len(run['out_of_band_ids'])} 条＝"
                        f"{run['out_of_band_ids'][:4]}",
            "ref": "本跑（C-130 未量带外；面已坍缩 focus＝构造上受限）",
        })
        # B 冲突成对（注意：focus 面不含碰撞块＝成对信息只经段文本到达模型；
        # 单边引用属面构成预期，判「仍在」时记贡献来源）
        b_state = "仍在" if run["one_sided_n"] > 0 else (
            "已消" if run["pairs"] else "无对可判")
        pairs_in_close = sum(
            1 for p in ring["ring4"].get("pairs_in_close") or [])
        table.append({
            "sym": "B_成对单边", "slug": slug, "qid": qid, "state": b_state,
            "evidence": f"单边 {run['one_sided_n']}/{len(run['pairs'])} 对；"
                        f"计划层成对 {ring['ring4']['n_pairs_paired']}"
                        f"/{ring['ring4']['n_pairs']}；"
                        f"close 覆盖成对 {pairs_in_close}"
                        f"/{ring['ring4']['n_pairs']}；"
                        "focus 面不含碰撞块（C-130 件①），成对只经段文本到达",
            "ref": "C-129 计划层 pair_violation 全 False；本跑看引用侧",
        })
        # C 核验钉
        nail_n = len(run["nail_ids"])
        c_state = ("无钉可判" if nail_n == 0 else
                   ("已消" if run["nail_in_close_n"] == nail_n else "仍在"))
        table.append({
            "sym": "C_核验钉未优先", "slug": slug, "qid": qid, "state": c_state,
            "evidence": f"钉进 close {run['nail_in_close_n']}/{nail_n}；"
                        f"钉被引 {run['nail_cited_n']}/{nail_n}",
            "ref": "本跑首量（R41 设计意图；C-130 未量）",
        })
        # D 采信/对立标注
        table.append({
            "sym": "D_采信对立标注", "slug": slug, "qid": qid,
            "state": "缺环（单分析师形状无标注面）",
            "evidence": f"结论数 {run['n_conclusions']}；计划层 preferred "
                        f"{ring['ring4']['n_pairs_preferred']}/{ring['ring4']['n_pairs']}",
            "ref": "标注面在归并/仲裁层；本跑形状与 C-130 同",
        })
        # E 可用密度（金标→细读＋细读非金标占比）
        g2c = ring["ring6"]["gold_to_close_prod"]
        close_n = ring["ring6"]["close_n"]
        gold_close_n = ring["ring6"]["gold_in_close_n"]
        e_state = "已消" if (g2c is not None and g2c >= 1.0 - 1e-9) else "仍在"
        if not ring["ring6"]["gold_in_close_n"] and ring["ring0"]["l1_gold_in_universe_n"]:
            e_state = "仍在"
        table.append({
            "sym": "E_可用密度低", "slug": slug, "qid": qid, "state": e_state,
            "evidence": f"金标→close {g2c}（{gold_close_n} 金标/"
                        f"{close_n} close，非金标 {close_n - gold_close_n}）",
            "ref": "C-129 计划层 6/6=1.0；C-130 q_003 开臂可用密度低",
        })
        # F 名单准度（同臂对照：C-130 开臂＝测试树生产面；R44 臂 0.5714/0.8571
        # 是另一臂口径、不可比，只作附注）
        prec = run["focus_precision"]
        ref = C130_ON_ARM.get((slug, qid))
        if ref is not None:
            f_state = ("已消（持平）"
                       if prec is not None
                       and prec + 1e-9 >= ref["focus_precision"] - 1e-9
                       else "仍在")
            f_ev = (f"focus 准度 {prec} vs C-130 开臂 {ref['focus_precision']}"
                    f"（L3 本跑 {run['l3']} vs 均值 {ref['l3_mean']}）；"
                    f"R44 臂口径 {C129_PLAN[slug]['list_precision']} 不可比仅附注")
        else:
            f_state = "首量（无同臂参照）"
            f_ev = (f"focus 准度 {prec}；R44 臂口径 "
                    f"{C129_PLAN[slug]['list_precision']} 为另一臂、不可比")
        table.append({
            "sym": "F_名单准度", "slug": slug, "qid": qid, "state": f_state,
            "evidence": f_ev,
            "ref": "同臂＝C-130 开臂（仅 liuxiang q_003 有真跑参照）；"
                   "C-129 为 R44 式回归臂口径",
        })
    return table


# ------------------------------------------------ main

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--legs", choices=("zero", "real", "all", "assemble"),
                    default="all",
                    help="zero＝腿0+1（零 LLM）；real＝腿2（14B 真跑）；"
                         "all＝全部；assemble＝从 /tmp/c134 分段件重组判表"
                         "（不重烧 LLM）")
    ap.add_argument("--no-artifact", action="store_true",
                    help="只写 /tmp/c134 中间件，不写 artifacts（分段跑时用）")
    args = ap.parse_args()
    t0 = time.perf_counter()
    tip = _git_tip()
    os.environ.pop("VERITAS_TEST_TREE_LINE", None)
    for k, v in {
        "VERITAS_KG_SUBMIT_SURFACE": "1",  # 与出厂默认一致，显式化只为可复核
        "VERITAS_KG_STAGE1": "1",
        "VERITAS_KG_REHYDRATE_BOX": "1",
        "VERITAS_MULTI_BOX": "0",
        "VERITAS_SECOND_PASS": "0",
        "VERITAS_REVIEW_BOOST": "0",  # 与 R44/C-129/C-130 门控基线同组
    }.items():
        os.environ[k] = v
    OUT.mkdir(parents=True, exist_ok=True)

    # 腿0＋腿1（零 LLM；assemble 模式从分段件读回）
    gate_cases: dict[str, dict] = {}
    rings: list[dict] = []
    if args.legs == "assemble":
        gate_cases = json.loads(
            (OUT / "c134_leg01_partial.json").read_text(
                encoding="utf-8"))["gate"]
        rings = json.loads(
            (OUT / "c134_leg01_partial.json").read_text(
                encoding="utf-8"))["rings"]
        print(f"assemble：读回 gate {sorted(gate_cases)}＋rings {len(rings)}",
              flush=True)
    else:
        for slug in CASES:
            mark = CASE_MARKS[slug]
            exp = EXPECT[slug]
            prefer = exp["role"] == "regression"
            print(f"=== 腿0 门控复刻 {slug}（prefer_gold={prefer}） ===",
                  flush=True)
            from app.core.kg_test_tree_line import test_tree_coeff
            coeff, names = test_tree_coeff()
            dens = _eval_case(slug, mark, coeff, names, prefer_gold=prefer)
            extra = _plan_cite_and_leak(slug, mark, coeff, names,
                                        prefer_gold=prefer)
            prod = _prod_leg(slug, mark)
            dens.update(extra)
            dens["prod_leg"] = prod
            gate_cases[slug] = dens
            for qrow in _questions_from_conclusions(_case(mark)):
                rings.append(_ring_evidence(slug, mark, qrow["question_id"]))
            (OUT / "c134_leg01_partial.json").write_text(json.dumps(
                {"gate": gate_cases, "rings": rings}, ensure_ascii=False,
                indent=1), encoding="utf-8")

    # 腿2（14B 真跑，逐题；assemble 模式从分段件读回）
    runs: list[dict] = []
    if args.legs == "assemble":
        runs = json.loads(
            (OUT / "c134_leg02_partial.json").read_text(encoding="utf-8"))
        print(f"assemble：读回 real runs {len(runs)}", flush=True)
    elif args.legs in ("real", "all"):
        for slug in CASES:
            mark = CASE_MARKS[slug]
            for qrow in _questions_from_conclusions(_case(mark)):
                ring = next(r for r in rings
                            if r["slug"] == slug
                            and r["qid"] == qrow["question_id"])
                runs.append(_real_pass(slug, mark, qrow["question_id"], ring))
                (OUT / "c134_leg02_partial.json").write_text(json.dumps(
                    runs, ensure_ascii=False, indent=1), encoding="utf-8")

    # 三闸＋症状表（显式布尔，不靠字符串匹配）
    g1_dens_ok = True
    g2_tree17_ok = True
    g3_leak_ok = True
    anomalies: list[str] = []
    for slug in CASES:
        c = gate_cases[slug]
        exp = EXPECT[slug]
        if c["micro_gold_density"] + 1e-12 < float(exp["micro_min"]) - DROP_EPS:
            anomalies.append(f"{slug} 微密度 {c['micro_gold_density']} < 期望 "
                             f"{exp['micro_min']}")
            g1_dens_ok = False
        if slug == "liuxiang" and int(c["cut_hits"]["7"]) != 12:
            anomalies.append(f"liuxiang @7={c['cut_hits']['7']} ≠ 12")
            g1_dens_ok = False
        if slug == "wanghong":
            q2 = next(r for r in c["density_rows"] if r["qid"] == "q_002")
            if q2["gold_density"] + 1e-12 < 0.6667:
                anomalies.append(f"wanghong q_002 密度 {q2['gold_density']} < 2/3")
                g1_dens_ok = False
        if c["mean_gold_box_to_close"] is not None \
                and abs(c["mean_gold_box_to_close"] - 1.0) > 1e-9:
            anomalies.append(f"{slug} 计划层金标→细读 "
                             f"{c['mean_gold_box_to_close']} ≠ 1.0")
            g2_tree17_ok = False
        if int(c["n_leaks"]) != 0:
            anomalies.append(f"{slug} 泄漏 {c['n_leaks']}")
            g3_leak_ok = False
    for r in rings:
        if not all(r["equiv_prod_entry"].values()):
            anomalies.append(f"{r['slug']}/{r['qid']} 镜像与生产入口不等价 "
                             f"{r['equiv_prod_entry']}")
        if r["ring5"]["leaks_s2"]:
            anomalies.append(f"{r['slug']}/{r['qid']} 环5 泄漏 "
                             f"{r['ring5']['leaks_s2']}")
            g3_leak_ok = False
    # C-135 环2 判定：两案各 ≥1 题 accounting_expand_keys 非空且逐键
    # 与独立复算一致（不折进三闸；三闸读数与本单前同源同尺）
    ring2_by_slug = {s: [r for r in rings if r["slug"] == s] for s in CASES}
    ring2_ok = True
    ring2_notes: list[str] = []
    for s, rs in ring2_by_slug.items():
        hit = [r for r in rs if r["ring2"]["accounting_expand_keys"]
               and r["ring2"]["disclosure_matches_independent"]]
        if not hit:
            ring2_ok = False
            ring2_notes.append(f"{s} 环2 无任何题的扩写披露非空且一致")
    gate1 = g1_dens_ok
    gate2 = g2_tree17_ok
    gate3 = g3_leak_ok
    sym = _symptom_table(rings, runs)
    n_still = sum(1 for s in sym if s["state"] == "仍在")
    n_gone = sum(1 for s in sym if s["state"] == "已消")
    n_new = sum(1 for s in sym if s["state"] == "新现")
    n_gap = sum(1 for s in sym if s["state"].startswith("缺环")
                or s["state"].startswith("无"))
    report = {
        "ticket": "C-134-two-case-gate",
        "tip": tip,
        "branch": "qoder/c134-two-case-gate",
        "env_note": "不设 VERITAS_TEST_TREE_LINE（出厂开）；env 组与 R44/C-129/C-130 "
                    "门控基线同（REVIEW_BOOST 显式 0 非出厂，为可比性）",
        "model": MODEL_ID,
        "embed": "本机 bge-m3 暖缓存（.kgcache，按 para_id 复用）",
        "temperature": "unset(None)＝与 C-120/C-130 同口径",
        "wall_s": round(time.perf_counter() - t0, 1),
        "gate": {"gate1_dens": gate1, "gate2_tree17": gate2, "gate3_leak": gate3,
                 "ring2_expand_ok": ring2_ok, "ring2_notes": ring2_notes,
                 "anomalies": anomalies},
        "gate_cases": gate_cases,
        "rings": rings,
        "real_runs": runs,
        "symptoms": sym,
        "symptom_count": {"仍在": n_still, "已消": n_gone, "新现": n_new,
                          "缺环/无对": n_gap},
        "deltas_vs_refs": {
            "note": "R44 尺见 EXPECT；C-129 计划层名单准度/金标→close 见 C129_PLAN；"
                    "C-130 q_003 真跑 L3 off 2.6／on 2.0（单题）",
        },
    }
    (OUT / "C134_two_case_gate.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.no_artifact:
        art = ROOT / "artifacts" / "C134_two_case_gate.json"
        art.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"wrote {art}", flush=True)
    else:
        print("no-artifact：artifacts/C134 未动（只写 /tmp 中间件）", flush=True)
    print(f"G1={gate1} G2={gate2} G3={gate3} 环2扩写={ring2_ok} "
          f"症状 仍在{n_still}/已消{n_gone}/新现{n_new}/缺环{n_gap} "
          f"wall={report['wall_s']}s", flush=True)
    if anomalies:
        print("异常：" + "；".join(anomalies), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
