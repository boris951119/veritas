#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R37 件①：ai171／kh_th 池外与盒稀的**只读**归因（零规则改动）。

R36 把 holdout 三案的主因写成「池外／池内挤」，但它的分母 `l2` 是
**金标 ∩ 生产箱 universe**（run_r36_interview_recall.py:78）——生产装箱
没装进来的金标段被静默摘掉，池外读数因此看不出「根本没到候选面」。
本票只做三件事，不改 app/kg_lab 任何规则：

1) 把分母换成**全金标**，逐段给六层落点：
   A 不在索引面 → B 不在生产箱 → C 池外(>50) → D 池 21‥50
   → E 池前20未进盒 → F 进盒；
2) 对每个未到盒的金标段取其段级角色／档位／声部／与议题的词面桥，
   并列出盒内占位者（谁把它挤掉）；
3) 补一把**固定 k 的召回尺**（top3／top5／top7），与可变 k 的密度并列，
   防止「缩盒抬密度」被当成召回改善。

判据（本票是量尺票，不含涨分门槛）：六层每段有且只有一层；
A＋B＋C＋D＋E＋F ＝ 全金标数；固定 k 尺与可变 k 尺同时出数。
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.config import DEFAULT_K  # noqa: E402
from app.kg_lab.density_submit import density_constrained_submit  # noqa: E402
from app.kg_lab.event_frame import extract_event_frame  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.intent_routes import classify_route, stage2_verifiable_slots  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.portable_tags import apply_portable_features  # noqa: E402
from app.kg_lab.r8_fit import augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import apply_r9  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.source_role import _meta_from_row  # noqa: E402
from app.kg_lab.case_lexicon import lexicon_for_question  # noqa: E402
from app.kg_lab.stage1_claim_holes import extract_verifiable_slots  # noqa: E402
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from app.kg_lab.stage2_authority import authority_rerank  # noqa: E402
from scripts.kg_lab.run_r22_intent_density import _case, _coeff_names  # noqa: E402
from scripts.kg_lab.run_r32_holdout_diag import _label_cause  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

OUT = ROOT / "artifacts"
TARGETS = (("ai171", "印度"), ("kh_th", "柬泰"), ("liuxiang", "刘翔"))
LAYERS = ("A_no_row", "B_not_in_production_box", "C_pool_out_50",
          "D_pool_21_50", "E_pool20_not_in_box", "F_in_box")


def _q_terms(question: str) -> list[str]:
    """议题词面桥：只取通用切面词（≥2字中文串＋数字原串），不碰案名。"""
    import re
    out: list[str] = []
    for m in re.findall(r"[\u4e00-\u9fff]{2,6}", question or ""):
        if m not in out:
            out.append(m)
    for m in re.findall(r"[0-9][0-9.,%]*", question or ""):
        if m not in out:
            out.append(m)
    return out[:24]


def _diag_case(slug: str, mark: str) -> dict[str, Any]:
    case = _case(mark, prefer_local=(slug == "liuxiang"))
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "") for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "") for d in raw}
    coeff, names = _coeff_names()
    by_row_all = {str(r.get("para_id")): r for r in rows}
    lex_all = lexicon_for_question(questions[0]["question"], case_slug=slug)

    per_q: list[dict[str, Any]] = []
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold_pairs, _ = gold_paras_for_question(case, qid)
        gold_all = sorted({p for _d, p in gold_pairs})
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for p in gold_all if p in universe)

        sub_rows = [r for r in rows if str(r["para_id"]) in universe]
        sub = KgIndex(slug, sub_rows)
        sub.embeddings = {
            pid: v for pid, v in index.embeddings.items() if pid in universe}
        fr = fuse_r19(sub, question, use_llm_views=False, neighbor_window=1)
        pool_ranked = fr.get("pool_ranked") or fr["ranked"]
        pool_pos = {pid: i for i, (pid, _sc) in enumerate(pool_ranked, 1)}

        s1 = extract_verifiable_slots(question)
        slots = stage2_verifiable_slots(question)
        frame = extract_event_frame(question)
        route_obj = classify_route(question, frame)
        route = getattr(route_obj, "route", None) or str(route_obj)
        bundle = build_bundle(
            sub_rows, fr["ranked"], question, frames=True,
            prefer_ids=None, case_slug=slug)
        metas = dict(bundle["metas"])
        for pid, _sc in pool_ranked[:50]:
            if pid in metas:
                continue
            row = by_row_all.get(pid)
            if row:
                metas[pid] = _meta_from_row(row, lex=lex_all)
                bundle["feats"].setdefault(pid, {})
        augment_features(bundle["feats"], metas, url_of)
        apply_r9(bundle["feats"], metas, question)
        apply_portable_features(
            bundle["feats"], metas, url_of, question, frame,
            publish_of=publish_of)
        bundle["metas"] = metas
        bundle["qid"], bundle["question"], bundle["l2"] = qid, question, l2
        stage1 = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)
        ranked = stage1["ranked"][qid]
        texts = {
            pid: str((metas.get(pid) or {}).get("text") or "")
            for pid in set([p for p, _ in ranked[:30]] + [p for p, _ in pool_ranked[:30]])
        }
        out = authority_rerank(
            ranked, pool_ranked,
            texts=texts, feats=bundle["feats"], metas=metas,
            question=question, frame=frame, url_of=url_of, publish_of=publish_of,
            pool=20, k=20, head_keep=1, max_inject=8, density_cut=True,
            gold_ids=set(l2), k_min=3, k_max=7)
        dens = out.get("density") or {}
        k_sel = int(dens.get("k") or 3)
        box = list(out.get("top_ids") or dens.get("submission") or [])
        box_head = box[:k_sel]
        final_order = [str(r["id"]) for r in (out.get("order") or [])]
        box_pos = {pid: i for i, pid in enumerate(box, 1)}

        terms = _q_terms(question)
        # 同文档兄弟段在池内的最好名次（判「文档到了、段选错」是否成立）
        def _sibling_best(pid: str) -> tuple[int | None, int | None]:
            doc = str(pid).split("#", 1)[0]
            best20 = best50 = None
            for sib_pid, rank in pool_pos.items():
                if str(sib_pid).split("#", 1)[0] != doc or sib_pid == pid:
                    continue
                if rank <= 20:
                    best20 = rank if best20 is None else min(best20, rank)
                if rank <= 50:
                    best50 = rank if best50 is None else min(best50, rank)
            return best20, best50

        rows_gold = []
        for pid in gold_all:
            row = by_row_all.get(pid)
            meta = metas.get(pid) or (
                _meta_from_row(row, lex=lex_all) if row else None) or {}
            text = str(meta.get("text") or (row or {}).get("text") or "")
            feat = bundle["feats"].get(pid) or {}
            pr = pool_pos.get(pid)
            in_box = pid in set(box_head)
            # 只对「池外且未进盒」的金标查同文档兄弟段（件② 的立刀依据）
            sib20 = sib50 = None
            if (pr is None or pr > 50) and pid in universe and not in_box:
                sib20, sib50 = _sibling_best(pid)
            if row is None:
                layer = "A_no_row"
            elif pid not in universe:
                layer = "B_not_in_production_box"
            elif in_box:
                # 进盒优先：二筛可把池 #83／#223 的段拉进盒，这类不能记成「池外」
                layer = "F_in_box"
            elif pr is None or pr > 50:
                layer = "C_pool_out_50"
            elif pr > 20:
                layer = "D_pool_21_50"
            else:
                layer = "E_pool20_not_in_box"
            rows_gold.append({
                "pid": pid, "layer": layer, "in_universe": pid in universe,
                "pool_rank": pr, "box_rank": box_pos.get(pid),
                "sibling_best_pool20": sib20, "sibling_best_pool50": sib50,
                "final_rank": (final_order.index(pid) + 1) if pid in final_order else None,
                "role": str(meta.get("role") or ""),
                "fine_role": str(meta.get("fine_role") or ""),
                "portable_role": str(meta.get("portable_role") or ""),
                "authority_band": str(feat.get("authority_band") or ""),
                "option_side": str(feat.get("option_side") or ""),
                "channel_tier": str(feat.get("channel_tier") or ""),
                "credibility": meta.get("credibility"),
                "n_title": len(str(meta.get("title") or "")),
                "len": len(text),
                "term_hits": sum(1 for t in terms if t and t in text),
                "n_terms": len(terms),
                "head": text[:64].replace("\n", " "),
                "title": str(meta.get("title") or "")[:40],
            })

        occupants = []
        for pid in box_head:
            meta = metas.get(pid) or {}
            feat = bundle["feats"].get(pid) or {}
            occupants.append({
                "pid": pid, "in_gold": pid in set(gold_all),
                "pool_rank": pool_pos.get(pid),
                "role": str(meta.get("role") or ""),
                "portable_role": str(meta.get("portable_role") or ""),
                "authority_band": str(feat.get("authority_band") or ""),
                "option_side": str(feat.get("option_side") or ""),
                "proxy_core": pid in set(dens.get("submission") or []) and bool(
                    (dens.get("n_core") or 0)),
            })

        fixed = {
            f"top{k}": sum(1 for pid in final_order[:k] if pid in set(gold_all))
            for k in (3, 5, 7)
        }
        fixed_univ = {
            f"top{k}": sum(1 for pid in final_order[:k] if pid in set(l2))
            for k in (3, 5, 7)
        }
        n_pool20 = sum(1 for g in l2 if pool_pos.get(g, 10 ** 9) <= 20)
        n_box = sum(1 for g in l2 if g in set(box_head))
        per_q.append({
            "qid": qid, "route": route,
            "n_gold_all": len(gold_all), "n_gold_universe": len(l2),
            "k_sel": k_sel,
            "proxy_density": dens.get("density"),
            "gold_density_var_k": round(n_box / k_sel, 4) if k_sel else 0.0,
            "cause_r36_label": _label_cause(
                n_gold=len(l2), n_pool20=n_pool20, n_box=n_box,
                k=k_sel, dens=(n_box / k_sel) if k_sel else 0.0),
            "layers": dict(Counter(r["layer"] for r in rows_gold)),
            "n_pool_out_C": sum(1 for r in rows_gold if r["layer"] == "C_pool_out_50"),
            "C_with_sibling_in_pool20": sum(
                1 for r in rows_gold
                if r["layer"] == "C_pool_out_50" and r["sibling_best_pool20"] is not None),
            "C_with_sibling_in_pool50": sum(
                1 for r in rows_gold
                if r["layer"] == "C_pool_out_50" and r["sibling_best_pool50"] is not None),
            "fixed_k_recall_full_gold": fixed,
            "fixed_k_recall_universe": fixed_univ,
            "gold_rows": rows_gold,
            "box_occupants": occupants,
            "claim_inj20": fr.get("n_claim_injected_in_pool20"),
        })

    layer_tot = Counter()
    for q in per_q:
        layer_tot.update(q["layers"])
    return {
        "slug": slug, "mark": mark,
        "n_gold_all": sum(q["n_gold_all"] for q in per_q),
        "n_gold_universe": sum(q["n_gold_universe"] for q in per_q),
        "layers": dict(layer_tot),
        "sum_fixed_top3": sum(q["fixed_k_recall_full_gold"]["top3"] for q in per_q),
        "sum_fixed_top5": sum(q["fixed_k_recall_full_gold"]["top5"] for q in per_q),
        "sum_fixed_top7": sum(q["fixed_k_recall_full_gold"]["top7"] for q in per_q),
        "n_pool_out_C": sum(q["n_pool_out_C"] for q in per_q),
        "C_with_sibling_in_pool20": sum(q["C_with_sibling_in_pool20"] for q in per_q),
        "C_with_sibling_in_pool50": sum(q["C_with_sibling_in_pool50"] for q in per_q),
        "questions": per_q,
    }


def main() -> int:
    print("======== R37 件① 池外／盒稀只读归因 ========", flush=True)
    t0 = time.time()
    cases = [_diag_case(slug, mark) for slug, mark in TARGETS]
    wall = round(time.time() - t0, 1)
    tot_all = sum(c["n_gold_all"] for c in cases)
    lay = Counter()
    for c in cases:
        lay.update(c["layers"])
    invariant = sum(lay.values()) == tot_all
    report = {
        "ticket": "R37-poolout-diag", "kind": "read-only", "wall_s": wall,
        "cases": cases,
        "totals": {
            "n_gold_all": tot_all,
            "n_gold_universe": sum(c["n_gold_universe"] for c in cases),
            "layers": dict(lay),
            "layer_sum_equals_denominator": invariant,
            "fixed_top3": sum(c["sum_fixed_top3"] for c in cases),
            "fixed_top5": sum(c["sum_fixed_top5"] for c in cases),
            "fixed_top7": sum(c["sum_fixed_top7"] for c in cases),
            "C_pool_out": sum(c["n_pool_out_C"] for c in cases),
            "C_reachable_via_sibling_pool20": sum(
                c["C_with_sibling_in_pool20"] for c in cases),
            "C_reachable_via_sibling_pool50": sum(
                c["C_with_sibling_in_pool50"] for c in cases),
        },
        "note": "分母＝全金标（未按生产箱 universe 预筛）；"
                "r36_label 仍按 l2＝金标∩universe 出，两者并列以便换算。",
    }
    (OUT / "R37_poolout_diag.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "六层落点（全金标 " + str(tot_all) + "）：" +
        "／".join(f"{k}={lay.get(k, 0)}" for k in LAYERS),
        "不变式 Σ层＝分母：" + str(invariant),
        "universe 预筛摘掉的金标＝"
        + str(tot_all - report["totals"]["n_gold_universe"])
        + "（R36 分母只数了 " + str(report["totals"]["n_gold_universe"]) + "）",
        "固定 k 召回（全金标）：top3=" + str(report["totals"]["fixed_top3"])
        + " top5=" + str(report["totals"]["fixed_top5"])
        + " top7=" + str(report["totals"]["fixed_top7"]),
        "池外(C) " + str(report["totals"]["C_pool_out"]) + " 段中，同文档兄弟段已在池前20 的＝"
        + str(report["totals"]["C_reachable_via_sibling_pool20"])
        + "、已在池前50 的＝" + str(report["totals"]["C_reachable_via_sibling_pool50"]),
    ]
    (OUT / "R37_poolout_diag.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for l in lines:
        print(l, flush=True)
    for c in cases:
        print(f"--- {c['slug']} 全金标{c['n_gold_all']}／universe{c['n_gold_universe']} "
              f"{json.dumps(c['layers'], ensure_ascii=False)}", flush=True)
        for q in c["questions"]:
            print(f"  {q['qid']} k={q['k_sel']} 标签={q['cause_r36_label']} "
                  f"top3/5/7={q['fixed_k_recall_full_gold']['top3']}/"
                  f"{q['fixed_k_recall_full_gold']['top5']}/"
                  f"{q['fixed_k_recall_full_gold']['top7']} "
                  f"{json.dumps(q['layers'], ensure_ascii=False)}", flush=True)
            for g in q["gold_rows"]:
                if g["layer"] == "F_in_box":
                    continue
                print(f"    {g['pid']} [{g['layer']}] pool#{g['pool_rank']} "
                      f"role={g['role']}/{g['portable_role']} band={g['authority_band']} "
                      f"side={g['option_side']} 词面{g['term_hits']}/{g['n_terms']} "
                      f"len={g['len']} 《{g['title']}》 {g['head']}", flush=True)
    print(f"墙钟 {wall}s；零规则改动（app/kg_lab 未动）。", flush=True)
    return 0 if invariant else 1


if __name__ == "__main__":
    raise SystemExit(main())
