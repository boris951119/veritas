#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-83：金标分类器 · 案级 hold-out 只量（生产零 diff／默认不动）。

原理：用可见案金标训「问句+段落 → 是否支撑证据」的逻辑回归（字 n-gram TF-IDF
＋BM25＋log 长度）；装箱时用 predict_proba 替换 rank_segments，再走同一
pack_material。

协议（Boyu 拍）：
  · 案级切分（整案不进训练）
  · 主读数＝留一案（LOO，6 折；每题恰好测一次 ⇒ 可对分母 105）
  · 辅读数＝全部 C(6,2)＝15 组「训 4／测 2」宏平均（方差披露）
  · 对照臂 A0＝现行 BM25 密度；GC＝分类器分
  · 金标只在本探针构造／判分；不写进 app/ 生产路径

判据（不过线⇒逃逸）：
  a  全量 A0 复现 48/105（尺没漂）
  b  LOO 池化：GC L2 ≥ A0 L2＋6 且 lost_vs_a0＝0
     （与精排门槛同族；达不到就老实说泛化不够）

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c83_gold_classifier.py \\
      --run-dir /tmp/six2 --run --out /tmp/c83_gold_clf.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bm25 import rank_segments  # noqa: E402
from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material, pack_search_queries  # noqa: E402
from app.export.official import _segment_locator  # noqa: E402
from scripts.probe_c62_rerank_arms import _pack_with_scores  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD,
    discover_reports,
    gold_paras_for_question,
)

TARGET_A0 = 48
TARGET_DENOM = 105
TARGET_LIFT = 6  # GC 比 A0 至少 +6 段且不丢 A0 已命中


def _budget(rep: dict) -> int:
    b = ((rep.get("accounting") or {}).get("pack_window") or {}).get("budget")
    if b is None:
        raise ValueError("缺 pack_window.budget")
    return int(b)


def _query(dossier: Dossier) -> str:
    qs = pack_search_queries(dossier)
    return str(qs[0]).strip() if qs else (dossier.question or "").strip()


def load_jobs(run_dir: Path, gold_dir: Path) -> list[dict]:
    """构造侧仍可读金标——本票明确是「金标监督学习」只量票。"""
    jobs = []
    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(rep)
        gold_map, _sk = gold_paras_for_question(gold_dir / case, qid)
        gold = set(gold_map.keys())
        if not gold:
            continue
        queries = pack_search_queries(dossier)
        bm25 = dict(
            rank_segments(dossier, queries=queries)
            if queries else rank_segments(dossier))
        rows = []
        for src in dossier.sources:
            for seg in src.segments:
                loc = _segment_locator(dossier, seg.id)
                if loc is None:
                    continue
                key = (str(loc[0]), str(loc[1]))
                rows.append({
                    "seg_id": str(seg.id),
                    "text": seg.text or "",
                    "bm25": float(bm25.get(seg.id, 0.0)),
                    "label": 1 if key in gold else 0,
                    "gold_key": key,
                })
        jobs.append({
            "case": case,
            "qid": qid,
            "budget": _budget(rep),
            "report": str(rp.resolve()),
            "query": _query(dossier),
            "gold": gold,
            "denom": len(gold),
            "rows": rows,
        })
    return jobs


def _pair_corpus(jobs: list[dict]) -> tuple[list[str], np.ndarray, np.ndarray]:
    texts, y, bm25s = [], [], []
    for job in jobs:
        q = job["query"]
        for r in job["rows"]:
            texts.append(f"{q}\n{r['text']}")
            y.append(r["label"])
            bm25s.append(r["bm25"])
    return texts, np.asarray(y, dtype=np.int32), np.asarray(bm25s, dtype=np.float64)


def train_classifier(train_jobs: list[dict]):
    from scipy import sparse
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    texts, y, bm25s = _pair_corpus(train_jobs)
    n_pos = int(y.sum())
    if n_pos < 3 or len(y) < 20:
        raise RuntimeError(f"训练集过瘦：n={len(y)} pos={n_pos}")
    vec = TfidfVectorizer(
        analyzer="char", ngram_range=(2, 4),
        min_df=2, max_features=25000, sublinear_tf=True,
    )
    Xt = vec.fit_transform(texts)
    extra = np.column_stack([
        bm25s,
        np.log1p(np.asarray([len(t) for t in texts], dtype=np.float64)),
    ])
    X = sparse.hstack([Xt, sparse.csr_matrix(extra)])
    clf = LogisticRegression(
        max_iter=800, class_weight="balanced", solver="liblinear",
        random_state=0,
    )
    clf.fit(X, y)
    return {"vec": vec, "clf": clf}


def score_job(model: dict, job: dict) -> dict[str, float]:
    from scipy import sparse

    vec, clf = model["vec"], model["clf"]
    q = job["query"]
    texts = [f"{q}\n{r['text']}" for r in job["rows"]]
    if not texts:
        return {}
    Xt = vec.transform(texts)
    bm25s = np.asarray([r["bm25"] for r in job["rows"]], dtype=np.float64)
    extra = np.column_stack([
        bm25s,
        np.log1p(np.asarray([len(t) for t in texts], dtype=np.float64)),
    ])
    X = sparse.hstack([Xt, sparse.csr_matrix(extra)])
    proba = clf.predict_proba(X)[:, 1]
    return {r["seg_id"]: float(p) for r, p in zip(job["rows"], proba)}


def eval_jobs(jobs: list[dict], scores_by_key: dict[tuple[str, str], dict[str, float]] | None,
              *, use_clf: bool) -> dict[str, Any]:
    """对给定题集装箱；use_clf 时用外部分数表，否则 A0。"""
    tot = Counter()
    per = []
    for job in jobs:
        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        budget = job["budget"]
        gold = job["gold"]
        if use_clf:
            assert scores_by_key is not None
            sc = scores_by_key[(job["case"], job["qid"])]
            # 未出现在训练特征里的段（无 locator）给 0
            full = {seg.id: 0.0 for src in dossier.sources for seg in src.segments}
            full.update(sc)
            sel = _pack_with_scores(dossier, budget, full)
        else:
            pack = pack_material(dossier, budget_chars=budget)
            sel = {str(x) for x in (pack.get("selected") or [])}
        locs = selected_locs(dossier, sel)
        hits = l2_hits(gold, locs)
        tot["hits"] += hits
        tot["denom"] += job["denom"]
        tot["n_sel"] += len(sel)
        per.append({
            "case": job["case"], "qid": job["qid"],
            "hits": hits, "denom": job["denom"], "n_sel": len(sel),
            "selected": sorted(sel),
            "hit_keys": sorted(gold & locs),
        })
    return {
        "l2_hits": int(tot["hits"]),
        "denom": int(tot["denom"]),
        "n_selected": int(tot["n_sel"]),
        "precision": round(tot["hits"] / tot["n_sel"], 4) if tot["n_sel"] else 0.0,
        "recall": round(tot["hits"] / tot["denom"], 4) if tot["denom"] else 0.0,
        "per": per,
    }


def lost_gained(a0: dict, gc: dict) -> tuple[int, int]:
    """题对齐后，相对 A0 的金标 lost／gained（按 hit_keys）。"""
    by_a = {(r["case"], r["qid"]): set(map(tuple, r["hit_keys"])) for r in a0["per"]}
    lost = gained = 0
    for r in gc["per"]:
        key = (r["case"], r["qid"])
        ga = by_a.get(key, set())
        gg = set(map(tuple, r["hit_keys"]))
        lost += len(ga - gg)
        gained += len(gg - ga)
    return lost, gained


def run_loo(jobs: list[dict]) -> dict[str, Any]:
    by_case: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        by_case[j["case"]].append(j)
    cases = sorted(by_case)
    fold_rows = []
    # 池化：每题测一次
    pool_a0_per, pool_gc_per = [], []
    for hold in cases:
        train = [j for c, js in by_case.items() if c != hold for j in js]
        test = by_case[hold]
        model = train_classifier(train)
        scores = {(j["case"], j["qid"]): score_job(model, j) for j in test}
        a0 = eval_jobs(test, None, use_clf=False)
        gc = eval_jobs(test, scores, use_clf=True)
        lost, gained = lost_gained(a0, gc)
        fold_rows.append({
            "hold_case": hold,
            "a0": {k: a0[k] for k in ("l2_hits", "denom", "n_selected", "precision", "recall")},
            "gc": {k: gc[k] for k in ("l2_hits", "denom", "n_selected", "precision", "recall")},
            "lost": lost, "gained": gained,
        })
        pool_a0_per.extend(a0["per"])
        pool_gc_per.extend(gc["per"])

    def _pool(per):
        hits = sum(r["hits"] for r in per)
        denom = sum(r["denom"] for r in per)
        n_sel = sum(r["n_sel"] for r in per)
        return {
            "l2_hits": hits, "denom": denom, "n_selected": n_sel,
            "precision": round(hits / n_sel, 4) if n_sel else 0.0,
            "recall": round(hits / denom, 4) if denom else 0.0,
            "per": per,
        }

    a0_pool = _pool(pool_a0_per)
    gc_pool = _pool(pool_gc_per)
    lost, gained = lost_gained(a0_pool, gc_pool)
    return {
        "folds": fold_rows,
        "pooled_a0": {k: a0_pool[k] for k in ("l2_hits", "denom", "n_selected", "precision", "recall")},
        "pooled_gc": {k: gc_pool[k] for k in ("l2_hits", "denom", "n_selected", "precision", "recall")},
        "pooled_lost": lost,
        "pooled_gained": gained,
    }


def run_train4_test2(jobs: list[dict]) -> dict[str, Any]:
    by_case: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        by_case[j["case"]].append(j)
    cases = sorted(by_case)
    folds = []
    for hold in combinations(cases, 2):
        hold_set = set(hold)
        train = [j for c, js in by_case.items() if c not in hold_set for j in js]
        test = [j for c in hold for j in by_case[c]]
        model = train_classifier(train)
        scores = {(j["case"], j["qid"]): score_job(model, j) for j in test}
        a0 = eval_jobs(test, None, use_clf=False)
        gc = eval_jobs(test, scores, use_clf=True)
        lost, gained = lost_gained(a0, gc)
        folds.append({
            "hold_cases": list(hold),
            "a0_l2": a0["l2_hits"], "a0_denom": a0["denom"],
            "a0_prec": a0["precision"],
            "gc_l2": gc["l2_hits"], "gc_denom": gc["denom"],
            "gc_prec": gc["precision"],
            "delta_l2": gc["l2_hits"] - a0["l2_hits"],
            "lost": lost, "gained": gained,
        })
    deltas = [f["delta_l2"] for f in folds]
    return {
        "n_folds": len(folds),
        "macro_delta_l2": round(float(np.mean(deltas)), 3),
        "macro_delta_l2_std": round(float(np.std(deltas)), 3),
        "n_delta_pos": sum(1 for d in deltas if d > 0),
        "n_delta_neg": sum(1 for d in deltas if d < 0),
        "n_delta_zero": sum(1 for d in deltas if d == 0),
        "folds": folds,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="/tmp/c83_gold_clf.json")
    ap.add_argument("--skip-c42", action="store_true",
                    help="只跑 LOO，跳过 15 组训4测2（更快）")
    args = ap.parse_args()
    if not args.run and not args.dry_run:
        args.dry_run = True

    print("======== C-83 金标分类器（案级 hold-out）========")
    if args.dry_run and not args.run:
        print("将：字 n-gram TF-IDF＋BM25＋loglen → LogisticRegression")
        print("主尺＝留一案 LOO 池化 105；辅尺＝训4测2 ×15 宏平均")
        print("判据 a＝全量 A0 48/105；b＝LOO GC≥A0+6 且 lost=0")
        print("本 dry-run 未训模型、未装箱。")
        return 0

    try:
        import sklearn  # noqa: F401
        import scipy  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "需要 scikit-learn 与 scipy：.venv/bin/pip install scikit-learn"
        ) from exc

    jobs = load_jobs(Path(args.run_dir), Path(args.gold_dir))
    cases = sorted({j["case"] for j in jobs})
    print(f"题数＝{len(jobs)}｜案数＝{len(cases)}｜正例＝"
          f"{sum(r['label'] for j in jobs for r in j['rows'])}")

    # 尺漂检查：全量 A0
    a0_all = eval_jobs(jobs, None, use_clf=False)
    print(f"全量 A0 L2＝{a0_all['l2_hits']}/{a0_all['denom']} "
          f"纯度＝{a0_all['precision']:.4f}")
    a_ok = a0_all["l2_hits"] == TARGET_A0 and a0_all["denom"] == TARGET_DENOM

    print("\n—— 留一案 LOO ——")
    loo = run_loo(jobs)
    print(
        f"池化 A0 {loo['pooled_a0']['l2_hits']}/{loo['pooled_a0']['denom']} "
        f"纯度 {loo['pooled_a0']['precision']:.4f}"
    )
    print(
        f"池化 GC {loo['pooled_gc']['l2_hits']}/{loo['pooled_gc']['denom']} "
        f"纯度 {loo['pooled_gc']['precision']:.4f} "
        f"lost＝{loo['pooled_lost']} gained＝{loo['pooled_gained']}"
    )
    for fr in loo["folds"]:
        print(
            f"  hold={fr['hold_case'][:14]} "
            f"A0 {fr['a0']['l2_hits']}/{fr['a0']['denom']} "
            f"GC {fr['gc']['l2_hits']}/{fr['gc']['denom']} "
            f"Δ={fr['gc']['l2_hits']-fr['a0']['l2_hits']:+d} "
            f"lost={fr['lost']}"
        )

    c42 = None
    if not args.skip_c42:
        print("\n—— 训4／测2（15 折）——")
        c42 = run_train4_test2(jobs)
        print(
            f"宏平均 ΔL2＝{c42['macro_delta_l2']}±{c42['macro_delta_l2_std']} "
            f"（＋{c42['n_delta_pos']}／0 {c42['n_delta_zero']}／−{c42['n_delta_neg']}）"
        )
        # 最差／最好各 3
        ranked = sorted(c42["folds"], key=lambda f: f["delta_l2"])
        print("最差 3 折：")
        for f in ranked[:3]:
            print(
                f"  hold={f['hold_cases']} Δ={f['delta_l2']:+d} "
                f"A0 {f['a0_l2']}/{f['a0_denom']} GC {f['gc_l2']}/{f['gc_denom']} "
                f"lost={f['lost']}"
            )
        print("最好 3 折：")
        for f in ranked[-3:]:
            print(
                f"  hold={f['hold_cases']} Δ={f['delta_l2']:+d} "
                f"A0 {f['a0_l2']}/{f['a0_denom']} GC {f['gc_l2']}/{f['gc_denom']} "
                f"lost={f['lost']}"
            )

    b_ok = (
        loo["pooled_gc"]["l2_hits"] >= TARGET_A0 + TARGET_LIFT
        and loo["pooled_lost"] == 0
        and loo["pooled_gc"]["denom"] == TARGET_DENOM
    )
    print("\n判据 a", "✅" if a_ok else "❌",
          f"A0={a0_all['l2_hits']}/{a0_all['denom']}")
    print(
        "判据 b", "✅" if b_ok else "❌（逃逸＝泛化不够／默认不动）",
        f"GC={loo['pooled_gc']['l2_hits']} "
        f"want≥{TARGET_A0 + TARGET_LIFT} lost={loo['pooled_lost']}"
    )

    out = {
        "a0_all": {k: a0_all[k] for k in (
            "l2_hits", "denom", "n_selected", "precision", "recall")},
        "loo": {k: v for k, v in loo.items() if k != "folds"} | {
            "folds": [
                {**{k: fr[k] for k in fr if k not in ()}}
                for fr in loo["folds"]
            ],
        },
        "train4_test2": c42,
        "judge": {"a_ok": a_ok, "b_ok": b_ok},
        "model": "char-ngram(2-4) TF-IDF + bm25 + loglen → LogisticRegression(balanced)",
    }
    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"落盘 {args.out}")
    return 0 if a_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
