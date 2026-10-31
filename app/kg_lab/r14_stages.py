"""R14 二筛：另一套加权和，目标是在一筛前 7 里踢非金标。不读金标 id，不从后面补人。"""

from __future__ import annotations

from typing import Any

from app.kg_lab.inbox_rerank import (
    is_fake_gloss,
    is_offtopic_money,
    is_section_bait,
    is_title_bait,
    _on_topic_body,
)
from app.kg_lab.r8_fit import l2

STAGE2_DIMS: tuple[str, ...] = (
    "identity_synonym",
    "resume_noise",
    "identity_resume",
    "on_topic",
    "claim_full",
    "claim_keyword",
    "title_bait",
    "section_bait",
    "offtopic_money",
    "fake_gloss",
)
STAGE2_GRID: tuple[float, ...] = (-0.12, -0.08, -0.04, -0.02, 0.0, 0.02, 0.04, 0.08, 0.12)


def stage2_features(pid: str, bundle: dict[str, Any]) -> dict[str, float]:
    meta = bundle["metas"].get(pid) or {}
    feat = bundle["feats"].get(pid) or {}
    question = str(bundle.get("question") or "")
    text = str(meta.get("text") or "")
    title = str(meta.get("title") or "")
    return {
        "identity_synonym": float(feat.get("identity_synonym") or 0.0),
        "resume_noise": float(feat.get("resume_noise") or 0.0),
        "identity_resume": float(feat.get("identity_resume") or 0.0),
        "on_topic": 1.0 if _on_topic_body(text, question) else 0.0,
        "claim_full": float(feat.get("claim_full") or 0.0),
        "claim_keyword": float(feat.get("claim_keyword") or 0.0),
        "title_bait": 1.0 if is_title_bait(title, text, question) else 0.0,
        "section_bait": 1.0 if is_section_bait(text, question) else 0.0,
        "offtopic_money": 1.0 if is_offtopic_money(text, feat, meta, question) else 0.0,
        "fake_gloss": 1.0 if is_fake_gloss(feat, meta) else 0.0,
    }


def stage2_score(feat: dict[str, float], coeff: dict[str, float], names: tuple[str, ...]) -> float:
    return sum(float(coeff.get(n) or 0.0) * float(feat.get(n) or 0.0) for n in names)


def _slate_rows(
    bundles: list[dict[str, Any]],
    ranked: dict[str, list[tuple[str, float]]],
    k: int,
) -> list[dict[str, Any]]:
    rows = []
    for b in bundles:
        l2 = set(b["l2"])
        for pid, _sc in ranked[b["qid"]][:k]:
            rows.append({
                "qid": b["qid"],
                "id": pid,
                "gold": pid in l2,
                "feat": stage2_features(pid, b),
            })
    return rows


def evaluate_stage2(
    rows: list[dict[str, Any]],
    coeff: dict[str, float],
    names: tuple[str, ...],
) -> dict[str, Any]:
    """score >= 0 留下。先保金标，再少留非金标。"""
    kept_gold = 0
    kept_non = 0
    by_q: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        bucket = by_q.setdefault(row["qid"], {"kept": [], "kicked": []})
        keep = stage2_score(row["feat"], coeff, names) >= 0.0
        (bucket["kept"] if keep else bucket["kicked"]).append(row["id"])
        if keep and row["gold"]:
            kept_gold += 1
        elif keep and not row["gold"]:
            kept_non += 1
    return {
        "gold_kept": kept_gold,
        "nongold_kept": kept_non,
        "l2": round(l2(coeff), 4),
        "by_q": by_q,
    }


def _better_stage2(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        a["gold_kept"],
        -a["nongold_kept"],
        -a["l2"],
    ) > (
        b["gold_kept"],
        -b["nongold_kept"],
        -b["l2"],
    )


def fit_stage2(
    bundles: list[dict[str, Any]],
    ranked: dict[str, list[tuple[str, float]]],
    *,
    k: int = 7,
    names: tuple[str, ...] = STAGE2_DIMS,
    grid: tuple[float, ...] = STAGE2_GRID,
    laps: int = 2,
) -> tuple[dict[str, float], list[dict[str, Any]], dict[str, Any]]:
    rows = _slate_rows(bundles, ranked, k)
    hi, lo = max(grid), min(grid)
    w = {n: 0.0 for n in names}
    trace = []
    best = evaluate_stage2(rows, w, names)
    trace.append({"step": "init", "gold_kept": best["gold_kept"], "nongold_kept": best["nongold_kept"], "l2": best["l2"]})
    for lap in range(laps):
        for name in names:
            chosen = w[name]
            chosen_ev = best
            for value in grid:
                trial = dict(w)
                trial[name] = value
                ev = evaluate_stage2(rows, trial, names)
                if _better_stage2(ev, chosen_ev):
                    chosen = value
                    chosen_ev = ev
            w[name] = max(min(chosen, hi), lo)
            best = chosen_ev
        trace.append({
            "step": f"lap{lap + 1}",
            "gold_kept": best["gold_kept"],
            "nongold_kept": best["nongold_kept"],
            "l2": best["l2"],
        })
    changed = True
    while changed:
        changed = False
        for name in names:
            if abs(w.get(name) or 0.0) < 1e-12:
                continue
            trial = dict(w)
            trial[name] = 0.0
            ev = evaluate_stage2(rows, trial, names)
            if ev["gold_kept"] >= best["gold_kept"] and ev["nongold_kept"] <= best["nongold_kept"]:
                w = trial
                best = ev
                changed = True
                break
    trace.append({
        "step": "eliminate",
        "gold_kept": best["gold_kept"],
        "nongold_kept": best["nongold_kept"],
        "l2": round(l2(w), 4),
    })
    best["l2"] = round(l2(w), 4)
    return w, trace, best


def apply_stage2(
    bundle: dict[str, Any],
    ranked: list[tuple[str, float]],
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    k: int = 7,
) -> dict[str, Any]:
    """一筛前 k 里，二筛分数 >= 0 的留下，顺序不变。后面的不补。"""
    l2 = set(bundle["l2"])
    final = []
    kicked = []
    for pid, _sc in ranked[:k]:
        feat = stage2_features(pid, bundle)
        score = stage2_score(feat, coeff, names)
        row = {"id": pid, "score": round(score, 4), "gold": pid in l2, "feat": feat}
        if score >= 0.0:
            final.append(row)
        else:
            kicked.append(row)
    return {
        "final": [r["id"] for r in final],
        "kicked": kicked,
        "n_final": len(final),
        "hits": [r["id"] for r in final if r["gold"]],
        "n_hits": sum(1 for r in final if r["gold"]),
        "nongold": [r["id"] for r in final if not r["gold"]],
    }
