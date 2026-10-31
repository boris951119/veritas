#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-87b：在 C-87 吉隆产物上只量三件事（不重打全库标）。

  A) 打标约束能救多少：实体必须原文子串；切面启发式纠偏；对照金标段
  B) 扩写约束：丢掉假实体／纯热词扩写，substance 不够则回退 path+真实体
  C) 双检索：原文 BM25 ∥ 标签伪文档 BM25 → RRF 融合，对照单路

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c87b_constrain_dual.py \\
      --c87-dir /tmp/c87_jilong --out-dir /tmp/c87b_constrain \\
      --k 120 --bm25-k 60
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from scripts.probe_c62_rerank_arms import _bm25_table  # noqa: E402
from scripts.probe_c66_multi_box import selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_c87_bilateral_tag_expand import (  # noqa: E402
    GATE_HOTWORD_MAX,
    GATE_SUBSTANCE_MIN,
    _bm25_over_docs,
    _has_substance,
    _hot_terms,
    _hotword_overlap,
    _rrf_fuse,
    _ENTITY_RE,
)
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

FACET_WORDS = {
    "成因": ("冰川", "断裂", "冰岩", "崩塌", "溃决", "冰湖", "失稳", "成因", "引发"),
    "时点": ("时", "分", "许", "左右"),
    "伤亡": ("遇难", "失联", "伤亡", "死亡", "救出", "遇难者"),
    "量值": ("米", "平方米", "万", "面积", "海拔", "公里", "立方米"),
    "救援": ("救援", "搜救", "消防", "驰援", "物资"),
    "处置": ("应急", "响应", "指挥部", "处置", "抢通"),
    "地质": ("堰塞", "滑坡", "地质", "遥感"),
    "交通": ("道路", "中断", "通行", "口岸", "航班"),
}


def _gold_sids(dossier: Dossier, gold: set[tuple[str, str]]) -> set[str]:
    text_ids = {
        seg.id for src in dossier.sources for seg in src.segments
    }
    out = set()
    for sid in text_ids:
        if selected_locs(dossier, {sid}) & gold:
            out.add(sid)
    return out


def _facet_of(path: str) -> str:
    parts = [p for p in (path or "").split("/") if p]
    return parts[-1] if parts else ""


def _best_facet(text: str) -> str | None:
    scores = {}
    for facet, words in FACET_WORDS.items():
        scores[facet] = sum(1 for w in words if w in text)
    # 时点：要有明确时刻形态才加分
    if re.search(r"\d{1,2}\s*时", text):
        scores["时点"] = scores.get("时点", 0) + 2
    best = max(scores, key=scores.get)
    if scores[best] <= 0:
        return None
    # 多切面：成因/时点优先于笼统伤亡（正文仅有「伤亡」二字时）
    if scores.get("成因", 0) >= 2 and scores.get("时点", 0) >= 2:
        return "时点" if scores["时点"] >= scores["成因"] else "成因"
    if scores.get("成因", 0) >= 2 and best == "伤亡" and scores["伤亡"] <= 1:
        return "成因"
    return best


def repair_tags(
    tags: dict[str, dict],
    text_of: dict[str, str],
) -> tuple[dict[str, dict], dict[str, Any]]:
    """A) 实体子串闸 + 切面启发式。返回新 tags 与账。"""
    out: dict[str, dict] = {}
    stats = Counter()
    examples: list[dict] = []

    for sid, rec in tags.items():
        text = text_of.get(sid) or ""
        old_p = str(rec.get("p") or "")
        old_e = [str(x) for x in (rec.get("e") or [])]
        src = rec.get("src") or "?"

        # 实体：只留原文子串；全灭则用正则从原文抽
        kept = [e for e in old_e if e and e in text]
        if old_e and not kept:
            stats["ents_all_fake"] += 1
        elif old_e and len(kept) < len(old_e):
            stats["ents_partial_fake"] += 1
        if not kept:
            kept = list(dict.fromkeys(_ENTITY_RE.findall(text)))[:4]
            if kept:
                stats["ents_regex_fill"] += 1

        new_p = old_p
        facet = _facet_of(old_p)
        want = _best_facet(text)
        changed_facet = False
        if want and facet and want != facet:
            # 仅当旧切面与正文线索冲突时改
            old_score = sum(1 for w in FACET_WORDS.get(facet, ()) if w in text)
            new_score = sum(1 for w in FACET_WORDS.get(want, ()) if w in text)
            conflict = (
                (facet == "伤亡" and new_score >= 2 and old_score <= 1)
                or (kept != old_e and want in ("成因", "时点") and facet == "伤亡")
                or (new_score >= old_score + 2)
            )
            if conflict:
                parts = old_p.split("/")
                if len(parts) >= 4:
                    parts[-1] = want
                    new_p = "/".join(parts)
                elif len(parts) == 3:
                    new_p = "/".join(parts + [want])
                else:
                    new_p = f"未归类/事件片段/未知/{want}"
                changed_facet = True
                stats["facet_fixed"] += 1

        changed_ents = kept != old_e
        if changed_ents:
            stats["ents_fixed"] += 1
        if changed_ents or changed_facet:
            stats["seg_repaired"] += 1
            if len(examples) < 12:
                examples.append({
                    "sid": sid,
                    "old_p": old_p,
                    "new_p": new_p,
                    "old_e": old_e,
                    "new_e": kept,
                    "src": src,
                })
        else:
            stats["seg_unchanged"] += 1

        out[sid] = {
            "p": new_p,
            "e": kept,
            "src": f"repaired:{src}" if (changed_ents or changed_facet) else src,
            "_changed_ents": changed_ents,
            "_changed_facet": changed_facet,
        }

    stats["n"] = len(tags)
    return out, {"counts": dict(stats), "examples": examples}


def repair_label_expansions(
    tags: dict[str, dict],
    old_exp: dict[str, dict],
    questions: list[str],
) -> tuple[dict[str, dict], dict[str, Any]]:
    """B) 扩写约束：假实体句丢掉；热词过高／无 substance → 回退 path+真实体。"""
    hot: set[str] = set()
    for q in questions:
        hot |= _hot_terms(q)

    # path → 真实体样例
    by_path: dict[str, list[str]] = defaultdict(list)
    for rec in tags.values():
        p = str(rec.get("p") or "")
        for e in rec.get("e") or []:
            if e and e not in by_path[p]:
                by_path[p].append(str(e))

    paths = sorted({str(r.get("p") or "") for r in tags.values()})
    out: dict[str, dict] = {}
    stats = Counter()
    for p in paths:
        ents = by_path[p][:8]
        parts = [x for x in p.split("/") if x and x not in ("未知", "其他", "未归类")]
        base = {
            "expand": (ents[:3] or parts[:3] or [p]),
            "keywords": list(dict.fromkeys(parts + ents))[:12],
            "src": "rule_constrained",
        }
        old = old_exp.get(p) or {}
        exp_terms = [str(x).strip() for x in (old.get("expand") or []) if str(x).strip()]
        kw_terms = [str(x).strip() for x in (old.get("keywords") or []) if str(x).strip()]

        def _ok_term(t: str) -> bool:
            # 含假日期串且不在 ents／path 里的长句：若含实体样貌但实体不在本 path ents，仍可留
            # 硬约束：整句不得「只热词」；须有 substance
            return _has_substance([t]) and _hotword_overlap([t], hot) <= 0.85

        kept_e = [t for t in exp_terms if _ok_term(t)]
        kept_k = [t for t in kw_terms if _ok_term(t) or t in ents or t in parts]
        if kept_e or kept_k:
            # 若整体热词过高或 substance 不够 → 回退
            terms = kept_e + kept_k
            hot_r = _hotword_overlap(terms, hot)
            if _has_substance(terms) and hot_r <= GATE_HOTWORD_MAX + 0.15:
                out[p] = {
                    "expand": kept_e[:8] or base["expand"],
                    "keywords": kept_k[:12] or base["keywords"],
                    "src": "llm_filtered",
                }
                stats["kept_filtered"] += 1
            else:
                out[p] = base
                stats["fallback_hot_or_thin"] += 1
        else:
            out[p] = base
            stats["fallback_empty"] += 1

    # 门
    substance_hit = 0
    hot_rates = []
    for p, exp in out.items():
        terms = list(exp.get("expand") or []) + list(exp.get("keywords") or [])
        if _has_substance(terms):
            substance_hit += 1
        hot_rates.append(_hotword_overlap(terms, hot))
    n = max(1, len(out))
    gates = {
        "gate_substance": {
            "value": round(substance_hit / n, 4),
            "threshold_min": GATE_SUBSTANCE_MIN,
            "ok": substance_hit / n >= GATE_SUBSTANCE_MIN,
        },
        "gate_hotword": {
            "value": round(sum(hot_rates) / max(1, len(hot_rates)), 4),
            "threshold_max": GATE_HOTWORD_MAX,
            "ok": (sum(hot_rates) / max(1, len(hot_rates))) <= GATE_HOTWORD_MAX,
        },
    }
    return out, {"counts": dict(stats), "gates": gates, "n_paths": len(out)}


def build_synth(tags: dict[str, dict], expansions: dict[str, dict]) -> dict[str, str]:
    synth = {}
    for sid, rec in tags.items():
        p = str(rec.get("p") or "")
        exp = expansions.get(p) or {}
        parts = [p]
        parts.extend(rec.get("e") or [])
        parts.extend(exp.get("expand") or [])
        parts.extend(exp.get("keywords") or [])
        synth[sid] = " ".join(str(x) for x in parts if x)
    return synth


def eval_pools(
    *,
    dossier: Dossier,
    gold: set[tuple[str, str]],
    label_ranking: list[tuple[str, float]],
    bm25_ranking: list[tuple[str, float]],
    k: int,
    bm25_k: int,
) -> dict[str, Any]:
    gids = _gold_sids(dossier, gold)
    label_pool = {sid for sid, _ in label_ranking[:k]}
    bm25_pool = {sid for sid, _ in bm25_ranking[:bm25_k]}
    # dual: RRF of the two full rankings, take top k
    dual = _rrf_fuse([label_ranking, bm25_ranking])
    dual_pool = {sid for sid, _ in dual[:k]}

    def hit(pool: set[str]) -> int:
        return len(selected_locs(dossier, pool) & gold)

    gold_bm25 = selected_locs(dossier, bm25_pool) & gold
    gold_label = selected_locs(dossier, label_pool) & gold
    gold_dual = selected_locs(dossier, dual_pool) & gold

    return {
        "n_gold_segs": len(gids),
        "denom": len(gold),
        "bm25": {
            "k": bm25_k,
            "gold_hit": hit(bm25_pool),
            "pool": len(bm25_pool),
        },
        "label": {
            "k": k,
            "gold_hit": hit(label_pool),
            "pool": len(label_pool),
            "unique_gold": len(gold_label - gold_bm25),
        },
        "dual": {
            "k": k,
            "gold_hit": hit(dual_pool),
            "pool": len(dual_pool),
            "unique_vs_bm25": len(gold_dual - gold_bm25),
            "unique_vs_label": len(gold_dual - gold_label),
            "covers_bm25_gold": gold_bm25 <= gold_dual,
            "covers_label_gold": gold_label <= gold_dual,
        },
        # 名次：金标在三路上的中位名次（越小越好）
        "median_rank": {
            "bm25": _median_rank(gids, bm25_ranking),
            "label": _median_rank(gids, label_ranking),
            "dual": _median_rank(gids, dual),
        },
    }


def _median_rank(gids: set[str], ranking: list[tuple[str, float]]) -> float | None:
    rank = {sid: i + 1 for i, (sid, _) in enumerate(ranking)}
    rs = sorted(rank[s] for s in gids if s in rank)
    if not rs:
        return None
    mid = len(rs) // 2
    if len(rs) % 2:
        return float(rs[mid])
    return (rs[mid - 1] + rs[mid]) / 2.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--c87-dir", default="/tmp/c87_jilong")
    ap.add_argument("--out-dir", default="/tmp/c87b_constrain")
    ap.add_argument("--gold-dir", default="")
    ap.add_argument("--k", type=int, default=120)
    ap.add_argument("--bm25-k", type=int, default=60)
    args = ap.parse_args()

    c87 = Path(args.c87_dir)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gold_dir = Path(args.gold_dir) if args.gold_dir else DEFAULT_GOLD

    tags_old = json.loads((c87 / "tags.json").read_text(encoding="utf-8"))
    segs_blob = json.loads((c87 / "segments.json").read_text(encoding="utf-8"))
    text_of = {s["id"]: s.get("text") or "" for s in segs_blob["segs"]}
    qjobs = json.loads((c87 / "question_jobs.json").read_text(encoding="utf-8"))
    q_exp = json.loads((c87 / "question_expansions.json").read_text(encoding="utf-8"))
    old_lab_exp = json.loads((c87 / "label_expansions.json").read_text(encoding="utf-8"))

    # ---- A 修标 ----
    tags_new, tag_report = repair_tags(tags_old, text_of)
    (out / "tags_repaired.json").write_text(
        json.dumps(tags_new, ensure_ascii=False), encoding="utf-8")

    # 金标段对照
    dossier = Dossier.from_dict(
        json.loads(Path(qjobs[0]["report"]).read_text(encoding="utf-8")))
    gold_repair_rows = []
    for job in qjobs:
        gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
        gids = _gold_sids(dossier, gold)
        before = after = facet_fix = ents_fix = 0
        details = []
        for sid in sorted(gids):
            o, n = tags_old[sid], tags_new[sid]
            fake_before = bool(o.get("e")) and not any(
                e in text_of.get(sid, "") for e in (o.get("e") or []))
            fake_after = bool(n.get("e")) and not any(
                e in text_of.get(sid, "") for e in (n.get("e") or []))
            if fake_before:
                before += 1
            if not fake_after and n.get("e"):
                after += 1
            if n.get("_changed_facet"):
                facet_fix += 1
            if n.get("_changed_ents"):
                ents_fix += 1
            details.append({
                "sid": sid,
                "old_p": o.get("p"),
                "new_p": n.get("p"),
                "old_e": o.get("e"),
                "new_e": n.get("e"),
                "fake_ents_before": fake_before,
                "changed_facet": n.get("_changed_facet"),
                "changed_ents": n.get("_changed_ents"),
            })
        gold_repair_rows.append({
            "qid": job["qid"],
            "n_gold": len(gids),
            "fake_ents_before": before,
            "has_real_ents_after": after,
            "facet_fix": facet_fix,
            "ents_fix": ents_fix,
            "details": details,
        })

    print("======== A 打标约束能救多少 ========", flush=True)
    print(json.dumps(tag_report["counts"], ensure_ascii=False, indent=2), flush=True)
    for row in gold_repair_rows:
        print(
            f"  金标 {row['qid']}: n={row['n_gold']} "
            f"假实体段 {row['fake_ents_before']}→修后真实体段 {row['has_real_ents_after']} "
            f"切面改 {row['facet_fix']} 实体改 {row['ents_fix']}",
            flush=True,
        )
        for d in row["details"]:
            if d["changed_facet"] or d["changed_ents"] or d["fake_ents_before"]:
                print(
                    f"    {d['sid']}: {d['old_p']} → {d['new_p']} | "
                    f"{d['old_e']} → {d['new_e']}",
                    flush=True,
                )

    # ---- B 扩写约束 ----
    questions = [j["query"] for j in qjobs]
    lab_exp, exp_report = repair_label_expansions(tags_new, old_lab_exp, questions)
    # 议题扩写：滤掉纯热词／无 substance；年份明显乱编的弱化（简单：含 2023 且议题无 2023 则丢）
    q_exp_new = {}
    for job in qjobs:
        key = f"{job['case']}::{job['qid']}"
        old = q_exp.get(key) or {}
        hot = _hot_terms(job["query"])
        year_ok = "2023" in job["query"]

        def _q_ok(t: str) -> bool:
            if (not year_ok) and "2023" in t:
                return False
            return _has_substance([t])

        qs = [q for q in (old.get("queries") or []) if _q_ok(str(q))]
        if job["query"] not in qs:
            qs = [job["query"]] + qs
        kws = [k for k in (old.get("keywords") or []) if _q_ok(str(k)) or str(k) in job["query"]]
        shapes = [s for s in (old.get("answer_shape") or []) if _has_substance([str(s)])]
        q_exp_new[key] = {
            "queries": list(dict.fromkeys(qs))[:10],
            "keywords": list(dict.fromkeys(kws))[:16],
            "answer_shape": shapes[:6],
            "src": "constrained",
        }
    (out / "label_expansions_repaired.json").write_text(
        json.dumps(lab_exp, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "question_expansions_repaired.json").write_text(
        json.dumps(q_exp_new, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n======== B 扩写约束 ========", flush=True)
    print(json.dumps(exp_report, ensure_ascii=False, indent=2), flush=True)

    synth = build_synth(tags_new, lab_exp)
    (out / "synth_docs.json").write_text(
        json.dumps(synth, ensure_ascii=False), encoding="utf-8")
    docs = list(synth.items())
    bm25_ranking = _bm25_table(dossier)

    # ---- C 三路召回 ----
    rows = []
    print("\n======== C 双检索对照 ========", flush=True)
    for job in qjobs:
        key = f"{job['case']}::{job['qid']}"
        gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
        exp = q_exp_new.get(key) or {}
        queries = [str(q).strip() for q in (exp.get("queries") or []) if str(q).strip()]
        if not queries:
            queries = [job["query"]]
        extra = list(exp.get("keywords") or []) + list(exp.get("answer_shape") or [])
        if extra:
            queries = list(dict.fromkeys(queries + [" ".join(extra[:12])]))
        label_ranking = _rrf_fuse([_bm25_over_docs(docs, q) for q in queries])
        # 对照：用「修标前」synth？这里只报修后标签路；旧标签路从 c87 score_input 的 gate 已有
        ev = eval_pools(
            dossier=dossier, gold=gold,
            label_ranking=label_ranking,
            bm25_ranking=bm25_ranking,
            k=args.k, bm25_k=args.bm25_k,
        )
        ev["qid"] = job["qid"]
        ev["denom"] = denom
        rows.append(ev)
        print(
            f"  {job['qid']}: BM25@{args.bm25_k}金={ev['bm25']['gold_hit']}/{denom}  "
            f"标签@{args.k}金={ev['label']['gold_hit']}(独有{ev['label']['unique_gold']})  "
            f"双路@{args.k}金={ev['dual']['gold_hit']}"
            f"(相对BM25多{ev['dual']['unique_vs_bm25']}, "
            f"盖住BM25金={ev['dual']['covers_bm25_gold']})  "
            f"中位名次 bm25/label/dual="
            f"{ev['median_rank']['bm25']}/{ev['median_rank']['label']}/{ev['median_rank']['dual']}",
            flush=True,
        )

    # 汇总
    tot = {
        "bm25_gold": sum(r["bm25"]["gold_hit"] for r in rows),
        "label_gold": sum(r["label"]["gold_hit"] for r in rows),
        "dual_gold": sum(r["dual"]["gold_hit"] for r in rows),
        "label_unique_gold": sum(r["label"]["unique_gold"] for r in rows),
        "dual_unique_vs_bm25": sum(r["dual"]["unique_vs_bm25"] for r in rows),
        "denom": sum(r["denom"] for r in rows),
        "dual_covers_all_bm25_gold": all(r["dual"]["covers_bm25_gold"] for r in rows),
    }
    # 与 C-87 旧标签路对照（从 retrieve_meta）
    old_meta_path = c87 / "retrieve_meta.json"
    old_label = None
    if old_meta_path.is_file():
        old = json.loads(old_meta_path.read_text(encoding="utf-8"))
        old_label = {
            "gold_in_label": (old.get("gates") or {}).get("gate_unique_gold", {}).get(
                "gold_in_label"),
            "unique_gold": (old.get("gates") or {}).get("gate_unique_gold", {}).get(
                "value"),
            "gold_in_bm25": (old.get("gates") or {}).get("gate_unique_gold", {}).get(
                "gold_in_bm25"),
        }

    verdict = {
        "tag_repair_helps_gold": any(
            r["ents_fix"] or r["facet_fix"] for r in gold_repair_rows),
        "label_after_repair_beats_old": (
            old_label is not None
            and tot["label_gold"] > (old_label.get("gold_in_label") or 0)
        ),
        "dual_beats_bm25": tot["dual_gold"] > tot["bm25_gold"],
        "dual_beats_label": tot["dual_gold"] > tot["label_gold"],
        "dual_preserves_bm25": tot["dual_covers_all_bm25_gold"],
        "worth_keep_dual": (
            tot["dual_covers_all_bm25_gold"]
            and tot["dual_gold"] >= tot["bm25_gold"]
        ),
        "note": (
            "双检索值得留：至少盖住原文BM25金标且总命中≥BM25；"
            "若只是持平BM25、标签独有金仍0＝约束+双路没买到新覆盖。"
        ),
    }

    payload = {
        "tag_repair": tag_report,
        "gold_repair_rows": gold_repair_rows,
        "expand_repair": exp_report,
        "retrieve_rows": rows,
        "totals": tot,
        "c87_old_label": old_label,
        "verdict": verdict,
        "k": args.k,
        "bm25_k": args.bm25_k,
    }
    (out / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n======== 汇总 ========", flush=True)
    print(json.dumps({"totals": tot, "c87_old_label": old_label, "verdict": verdict},
                     ensure_ascii=False, indent=2), flush=True)
    print(f"落盘 {out / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
