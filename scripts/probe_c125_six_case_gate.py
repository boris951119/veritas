#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-125 件③：主仓端口后的六案门控（R44 同尺复刻＋生产链现场腿）。

三腿（全部零 LLM；嵌入＝本机 bge-m3 暖缓存；金标只进量尺面）：
  A. 密度复刻腿＝R44 `_eval_case` 同参数（刘翔回归臂 prefer_gold=True
     固定 k=7；其余臂 density_cut=True）→ 案均／微密度、@7、分题密度；
  B. 计划层金标→细读＋交卷窄面泄漏抽检（R44 `_plan_cite_and_leak` 同式）；
  C. 生产链现场腿＝`app.core.kg_test_tree_line.build_test_tree_surface`
     （零金标、density_cut=True、嵌入自动降级披露）→ 每题盒密度／k／路由。

判定尺（工单）：holdout 微密度 ≈≥2/3、回归／冒烟不掉、刘翔@7=12、
泄漏＝0；漂移如实记录，不改尺。

产物卫生：只记 id／计数／sha8，零官方原文。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.kg_test_tree_line import (  # noqa: E402
    build_test_tree_surface, test_tree_coeff,
)
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from app.kg_lab.case_lexicon import lexicon_for_question  # noqa: E402
from app.kg_lab.event_frame import extract_event_frame  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.intent_routes import classify_route  # noqa: E402
from app.kg_lab.layer_boundary import (  # noqa: E402
    FORBIDDEN_PACK_KEYS, assert_submit_no_coeff, audit_forbidden_keys,
    build_submit_surface, pack_hints_from_submit, stage2_box_export,
)
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.portable_tags import apply_portable_features  # noqa: E402
from app.kg_lab.r8_fit import augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import apply_r9  # noqa: E402
from app.kg_lab.source_role import _meta_from_row  # noqa: E402
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from app.kg_lab.stage2_authority import authority_rerank  # noqa: E402
from app.kg_lab.tree17_cite import apply_tree17_cite  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SAMPLES = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
OUT = ROOT / "artifacts" / "c125"
KS = (4, 5, 7)
DEFAULT_K = 7

# R44 期望（相对 R43/R42；漂移如实记录）
EXPECT = {
    "liuxiang": {"role": "regression", "micro_min": 0.5714, "at7": 12},
    "jilong": {"role": "smoke", "micro_min": 0.6667, "at7": 6},
    "us_cn_ai": {"role": "smoke", "micro_min": 0.6667, "at7": 6},
    "wanghong": {"role": "holdout", "micro_min": 0.8571, "at7": 6,
                 "q002_min": 0.6667},
    "kh_th": {"role": "holdout", "micro_min": 0.80, "at7": 4},
    "ai171": {"role": "holdout", "micro_min": 0.80, "at7": 5},
}
GATE_DENS = 2.0 / 3.0
DROP_EPS = 0.02

CASE_MARKS = {
    "liuxiang": "刘翔", "jilong": "吉隆", "us_cn_ai": "中美AI",
    "wanghong": "王虹", "kh_th": "柬泰", "ai171": "印度航空",
}


def _case(mark: str) -> Path:
    hits = [p for p in SAMPLES.iterdir()
            if p.is_dir() and mark in p.name
            and (p / "raw_documents.json").is_file()]
    if len(hits) == 1:
        return hits[0]
    raise SystemExit(f"case {mark} not found")


def _git_tip() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT), text=True).strip()
    except Exception:
        return "unknown"


# ------------------------------------------------ 评测侧助手（自 exp slices.py 迁入）

def _questions_from_conclusions(case_dir: Path) -> list[dict[str, str]]:
    conc = json.loads(
        (case_dir / "conclusions.json").read_text(encoding="utf-8"))
    seen: dict[str, str] = {}
    for row in conc:
        qid = str(row.get("question_id") or "").strip()
        q = str(row.get("question") or "").strip()
        if qid and q and qid not in seen:
            seen[qid] = q
    return [{"question_id": k, "question": v}
            for k, v in sorted(seen.items())]


def _union_pack_ids(case_dir: Path) -> tuple[Dossier, set[str],
                                             list[dict[str, str]]]:
    dossier = load_official_case(case_dir)
    qs = _questions_from_conclusions(case_dir)
    union: set[str] = set()
    for row in qs:
        dossier.question = row["question"]
        pack = pack_material(dossier)
        union |= {str(x) for x in (pack.get("selected") or [])}
    return dossier, union, qs


# ------------------------------------------------ 腿 A：密度复刻（R44 同参数）

def _eval_case(slug: str, mark: str, coeff: dict[str, float],
               names: tuple[str, ...], *, prefer_gold: bool) -> dict[str, Any]:
    case = _case(mark)
    t0 = time.perf_counter()
    print(f"=== 腿A 密度 {slug}（prefer_gold={prefer_gold}） ===", flush=True)
    dossier, union, questions = _union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "")
              for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "")
                  for d in raw}
    cut_hits = {str(k): 0 for k in KS}
    gold_total = 0
    dens_rows: list[dict[str, Any]] = []
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, _ = gold_paras_for_question(case, qid)
        dossier.question = question
        pack = pack_material(dossier)
        universe = {str(x) for x in (pack.get("selected") or [])}
        l2 = sorted(p for _d, p in gold if p in universe)
        gold_total += len(l2)
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(slug, sub_rows)
        sub.embeddings = {pid: v for pid, v in index.embeddings.items()
                          if pid in universe}
        fr = fuse_r19(sub, question, use_llm_views=False, neighbor_window=1)
        submit_ranked = fr["ranked"]
        pool_ranked = fr.get("pool_ranked") or fr["ranked"]
        frame = extract_event_frame(question)
        route = classify_route(question, frame)
        prefer = set(l2) if prefer_gold else None
        bundle = build_bundle(
            sub_rows, submit_ranked, question, frames=True,
            prefer_ids=prefer, case_slug=slug,
        )
        by_row = {r["para_id"]: r for r in sub_rows}
        lex = lexicon_for_question(question, case_slug=slug)
        for pid, _sc in pool_ranked[:50]:
            if pid in bundle["metas"]:
                continue
            row = by_row.get(pid)
            if row:
                bundle["metas"][pid] = _meta_from_row(row, lex=lex)
                bundle["feats"].setdefault(pid, {})
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question)
        apply_portable_features(
            bundle["feats"], bundle["metas"], url_of, question, frame,
            publish_of=publish_of,
        )
        bundle["qid"] = qid
        bundle["question"] = question
        bundle["l2"] = l2
        stage1 = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)
        ranked = stage1["ranked"][qid]
        texts = {
            pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
            for pid in set(
                [p for p, _ in ranked[:30]] + [p for p, _ in pool_ranked[:30]])
        }
        out = authority_rerank(
            ranked, pool_ranked,
            texts=texts, feats=bundle["feats"], metas=bundle["metas"],
            question=question, frame=frame, url_of=url_of,
            publish_of=publish_of,
            pool=20, k=20,
            head_keep=7 if prefer_gold else 1,
            max_inject=2 if prefer_gold else 8,
            density_cut=not prefer_gold,
            gold_ids=set(l2),
            k_min=3, k_max=7,
        )
        order = [row["id"] for row in out["order"]]
        dens = out.get("density") if out.get("density_cut") else None
        dens = dens or {}
        if dens and out.get("density_cut"):
            k_sel = int(dens.get("k") or 7)
            box = list(out.get("top_ids") or dens.get("submission")
                       or order[:k_sel])
            if not box:
                box = order[:k_sel]
        else:
            k_sel = 7  # 回归臂：固定 k=7 披露密度（不改序）
            box = order[:k_sel]
        n_gold = sum(1 for g in l2 if g in box)
        gold_dens = n_gold / k_sel if k_sel else 0.0
        dens_rows.append({
            "qid": qid, "route": route.route, "k": k_sel, "n_gold": n_gold,
            "gold_density": round(gold_dens, 4), "density_cut": bool(dens),
        })
        for kk in KS:
            cut_hits[str(kk)] += sum(1 for g in l2 if g in order[:kk])
        print(f"  {qid} route={route.route} k={k_sel} "
              f"gold_dens={gold_dens:.0%} ({n_gold}/{k_sel}) @7 "
              f"{cut_hits['7']}", flush=True)
    sum_g = sum(r["n_gold"] for r in dens_rows)
    sum_k = sum(r["k"] for r in dens_rows)
    micro = round(sum_g / sum_k, 4) if sum_k else 0.0
    avg_gd = (round(sum(r["gold_density"] for r in dens_rows)
                    / len(dens_rows), 4) if dens_rows else 0.0)
    return {
        "slug": slug, "gold_total": gold_total, "cut_hits": cut_hits,
        "density_rows": dens_rows, "avg_gold_density": avg_gd,
        "micro_gold_density": micro, "sum_gold_in_boxes": sum_g,
        "sum_k": sum_k, "wall_s": round(time.perf_counter() - t0, 1),
    }


# ------------------------------------------------ 腿 B：计划层＋泄漏（R44 同式）

def _plan_cite_and_leak(slug: str, mark: str, coeff: dict[str, float],
                        names: tuple[str, ...], *,
                        prefer_gold: bool) -> dict[str, Any]:
    case = _case(mark)
    print(f"=== 腿B 计划层/泄漏 {slug} ===", flush=True)
    dossier, union, questions = _union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "")
              for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "")
                  for d in raw}
    plan_rows: list[dict[str, Any]] = []
    leak_hits: list[str] = []
    n_submit_ok = 0
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, _ = gold_paras_for_question(case, qid)
        dossier.question = question
        pack = pack_material(dossier)
        universe = {str(x) for x in (pack.get("selected") or [])}
        l2 = sorted(p for _d, p in gold if p in universe)
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(slug, sub_rows)
        sub.embeddings = {pid: v for pid, v in index.embeddings.items()
                          if pid in universe}
        fr = fuse_r19(sub, question, use_llm_views=False, neighbor_window=1)
        submit_ranked = fr["ranked"]
        pool_ranked = fr.get("pool_ranked") or fr["ranked"]
        frame = extract_event_frame(question)
        route = classify_route(question, frame)
        prefer = set(l2) if prefer_gold else None
        bundle = build_bundle(
            sub_rows, submit_ranked, question, frames=True,
            prefer_ids=prefer, case_slug=slug,
        )
        by_row = {r["para_id"]: r for r in sub_rows}
        lex = lexicon_for_question(question, case_slug=slug)
        for pid, _sc in list(pool_ranked[:60]) + [(g, 0) for g in l2]:
            if pid in bundle["metas"]:
                continue
            row = by_row.get(pid)
            if row:
                bundle["metas"][pid] = _meta_from_row(row, lex=lex)
                bundle["feats"].setdefault(pid, {})
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question)
        apply_portable_features(
            bundle["feats"], bundle["metas"], url_of, question, frame,
            publish_of=publish_of,
        )
        bundle["qid"] = qid
        bundle["question"] = question
        bundle["l2"] = l2
        stage1 = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)
        ranked = stage1["ranked"][qid]
        texts = {
            pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
            for pid in set(
                [p for p, _ in ranked[:40]] + [p for p, _ in pool_ranked[:40]]
                + l2)
        }
        out = authority_rerank(
            ranked, pool_ranked,
            texts=texts, feats=bundle["feats"], metas=bundle["metas"],
            question=question, frame=frame, url_of=url_of,
            publish_of=publish_of,
            pool=20, k=20,
            head_keep=7 if prefer_gold else 1,
            max_inject=2 if prefer_gold else 8,
            density_cut=not prefer_gold,
            gold_ids=set(l2),
            k_min=3, k_max=7,
        )
        order = [row["id"] for row in out["order"]]
        dens = out.get("density") if out.get("density_cut") else {}
        dens = dens or {}
        if dens and out.get("density_cut"):
            k_sel = int(dens.get("k") or 7)
            box = list(out.get("top_ids") or dens.get("submission")
                       or order[:k_sel])
        else:
            k_sel = 7
            box = order[:k_sel]
        box_export = stage2_box_export(out)
        box_export = {**box_export, "box_ids": list(box), "k": k_sel}
        leak_hits.extend(audit_forbidden_keys(
            box_export, path=f"{slug}.{qid}.s2"))
        t17 = apply_tree17_cite(
            box, metas=bundle["metas"], question=question,
            anchors=route.anchors, align_to_box=True,
            gold_ids=set(l2), support_ids=set(l2),
        )
        plan = t17.get("plan") or {}
        surface = build_submit_surface(box_export, tree17_plan=plan)
        assert_submit_no_coeff(surface)
        hints = pack_hints_from_submit(surface)
        leak_hits.extend(audit_forbidden_keys(
            hints, path=f"{slug}.{qid}.hints"))
        n_submit_ok += 1
        gold_box = [g for g in l2 if g in box]
        close = list(plan.get("close_read") or [])
        g2c = (sum(1 for g in gold_box if g in close) / len(gold_box)
               if gold_box else 1.0)
        plan_rows.append({
            "qid": qid, "k": k_sel,
            "n_gold": len(gold_box),
            "gold_density": round(len(gold_box) / k_sel if k_sel else 0, 4),
            "gold_in_box_to_close": round(g2c, 4),
            "n_pairs": len((surface.get("conflict_pairs") or {}).get(
                "conflicts") or [])
            if isinstance(surface.get("conflict_pairs"), dict) else 0,
        })
    mean_g2c = (round(sum(r["gold_in_box_to_close"] for r in plan_rows)
                      / len(plan_rows), 4) if plan_rows else None)
    return {
        "plan_rows": plan_rows, "mean_gold_box_to_close": mean_g2c,
        "n_leaks": len(leak_hits), "leak_sample": leak_hits[:6],
        "n_submit_ok": n_submit_ok, "n_questions": len(plan_rows),
    }


# ------------------------------------------------ 腿 C：生产链现场（零金标）

def _prod_leg(slug: str, mark: str) -> dict[str, Any]:
    case = _case(mark)
    print(f"=== 腿C 生产链现场 {slug}（零金标） ===", flush=True)
    questions = _questions_from_conclusions(case)
    rows_out: list[dict[str, Any]] = []
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        d = load_official_case(case)
        d.question = question
        out = build_test_tree_surface(d, case_slug=slug)
        gold, _ = gold_paras_for_question(case, qid)
        gold_ids = {str(loc) if "#" in str(loc) else f"{doc}#{loc}"
                    for doc, loc in gold}
        box = out["box"]
        n_gold = sum(1 for g in gold_ids if g in box)
        rows_out.append({
            "qid": qid, "k": out["k"], "n_gold": n_gold,
            "gold_density": round(n_gold / out["k"] if out["k"] else 0, 4),
            "route": out["route"], "embed": out["embed"]["status"],
            "n_pairs": out["n_pairs"],
        })
        print(f"  {qid} k={out['k']} dens={rows_out[-1]['gold_density']:.0%} "
              f"route={out['route']} embed={out['embed']['status']}",
              flush=True)
    sum_g = sum(r["n_gold"] for r in rows_out)
    sum_k = sum(r["k"] for r in rows_out)
    return {
        "rows": rows_out,
        "micro_gold_density": round(sum_g / sum_k, 4) if sum_k else 0.0,
    }


def _flag(ok: bool) -> str:
    return "OK" if ok else "RED"


def main() -> int:
    t0 = time.perf_counter()
    tip = _git_tip()
    coeff, names = test_tree_coeff()
    print(f"系数键数={len(coeff)}（只进一筛）｜tip={tip}", flush=True)
    cases: list[dict[str, Any]] = []
    anomalies: list[str] = []
    total_leaks = 0
    all_submit_ok = True
    for slug, mark in CASE_MARKS.items():
        exp = EXPECT[slug]
        dens = _eval_case(slug, mark, coeff, names,
                          prefer_gold=(exp["role"] == "regression"))
        extra = _plan_cite_and_leak(
            slug, mark, coeff, names,
            prefer_gold=(exp["role"] == "regression"))
        prod = _prod_leg(slug, mark)
        dens.update(extra)
        dens["prod_leg"] = prod
        total_leaks += int(extra["n_leaks"])
        if extra["n_submit_ok"] != extra["n_questions"]:
            all_submit_ok = False
        dens_ok = (dens["micro_gold_density"] + 1e-12
                   >= float(exp["micro_min"]) - DROP_EPS)
        at7_ok = int(dens["cut_hits"]["7"]) == int(exp["at7"]) \
            if slug == "liuxiang" \
            else int(dens["cut_hits"]["7"]) >= int(exp["at7"])
        if slug == "wanghong":
            q2 = next(r for r in dens["density_rows"] if r["qid"] == "q_002")
            if q2["gold_density"] + 1e-12 < float(exp["q002_min"]):
                dens_ok = False
                anomalies.append(
                    f"wanghong q_002 密度 {q2['gold_density']:.0%} < 期望 67%")
        if (dens["mean_gold_box_to_close"] is not None
                and abs(dens["mean_gold_box_to_close"] - 1.0) > 1e-9):
            anomalies.append(
                f"{slug} 计划层金标→细读 {dens['mean_gold_box_to_close']:.0%}"
                " ≠ 100%")
        if not dens_ok:
            anomalies.append(
                f"{slug} 微密度 {dens['micro_gold_density']:.0%} < 期望 "
                f"{float(exp['micro_min']):.0%}")
        if not at7_ok:
            anomalies.append(
                f"{slug} @7={dens['cut_hits']['7']} 期望 {exp['at7']}")
        dens["gate_ok"] = dens_ok and at7_ok and extra["n_leaks"] == 0
        cases.append(dens)

    holdouts = [c for c in cases
                if EXPECT[c["slug"]]["role"] == "holdout"]
    gate1 = (
        all(c["micro_gold_density"] + 1e-12 >= GATE_DENS for c in holdouts)
        and all(c["micro_gold_density"] + 1e-12
                >= float(EXPECT[c["slug"]]["micro_min"]) - DROP_EPS
                for c in cases)
        and next(c for c in cases if c["slug"] == "liuxiang")[
            "cut_hits"]["7"] == 12
    )
    gate2 = all(c.get("mean_gold_box_to_close") is not None
                and abs(float(c["mean_gold_box_to_close"]) - 1.0) < 1e-9
                for c in cases)
    gate3 = total_leaks == 0 and all_submit_ok
    ready = gate1 and gate2 and gate3 and not anomalies

    report = {
        "ticket": "C-125-six-case-gate",
        "tip": tip,
        "branch": "qoder/c125-test-tree-port",
        "wall_s": round(time.perf_counter() - t0, 1),
        "coeff_names_n": len(names),
        "forbidden_keys_n": len(FORBIDDEN_PACK_KEYS),
        "gate": {"gate1": gate1, "gate2": gate2, "gate3": gate3,
                 "n_leaks": total_leaks, "all_submit_ok": all_submit_ok,
                 "ready": ready},
        "expect": EXPECT,
        "anomalies": anomalies,
        "cases": cases,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "C125_six_case_gate.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# C-125 六案门控（主仓端口后现场复测）", ""]
    for c in cases:
        exp = EXPECT[c["slug"]]
        lines.append(
            f"- {c['slug']}（{exp['role']}）：微密度 "
            f"{c['micro_gold_density']:.0%}（期望≥{exp['micro_min']:.0%}）"
            f"｜@7={c['cut_hits']['7']}（期望 {exp['at7']}）"
            f"｜金标→细读 {c['mean_gold_box_to_close']}"
            f"｜泄漏={c['n_leaks']}｜生产链现场微密度="
            f"{c['prod_leg']['micro_gold_density']:.0%}"
            f"｜闸={_flag(c['gate_ok'])}")
    lines += [
        "",
        f"门槛①（holdout≥2/3＋不掉＋刘翔@7=12）={_flag(gate1)}；"
        f"门槛②（金标→细读全1.0）={_flag(gate2)}；"
        f"门槛③（零泄漏）={_flag(gate3)}；"
        f"READY={'YES' if ready else 'NO'}。",
        f"墙钟 {report['wall_s']}s｜异常 {'；'.join(anomalies) if anomalies else '（无）'}",
        "",
    ]
    (OUT / "C125_six_case_gate.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)
    print(f"READY={'YES' if ready else 'NO'} G1={gate1} G2={gate2} "
          f"G3={gate3} wall={report['wall_s']}s", flush=True)
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
