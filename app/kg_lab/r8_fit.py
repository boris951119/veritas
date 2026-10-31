"""R8：多维标签系数拟合。

score = rrf + Σ w_d · x_d，w 可正可负，|w| 限制在网格内。
金标只进目标函数和去重留 id，不进特征。
"""

from __future__ import annotations

import math
from typing import Any

from app.kg_lab.channel_tier import TIERS, channel_tier
from app.kg_lab.multidim_weight import DIMS as _BASE_DIMS
from app.kg_lab.multidim_weight import ROLE_UNIT
from app.kg_lab.source_role import FINE_ROLES

# 问句相关的连续维 + 可信度 + 角色独热 + 渠道层级独热 + 本人渠道
BASE_DIMS: tuple[str, ...] = (
    "subject_match",
    "claim_align",
    "amount_status",
    "time_anchor",
    "credibility",
    "channel_self",
)
ROLE_DIMS: tuple[str, ...] = tuple(f"role_{r}" for r in FINE_ROLES)
TIER_DIMS: tuple[str, ...] = tuple(f"tier_{t}" for t in TIERS)
FEATURE_NAMES: tuple[str, ...] = BASE_DIMS + ROLE_DIMS + TIER_DIMS

# 幅度约束：相邻 RRF 分差约 0.002～0.01，±0.08 已能搬动中部名次
GRID: tuple[float, ...] = (-0.08, -0.04, -0.02, 0.0, 0.02, 0.04, 0.08)
# R6 的 source_role 系数，用来把角色单位分摊回独热初值
_R6_ROLE = 0.015


def r6_init() -> dict[str, float]:
    w = {n: 0.0 for n in FEATURE_NAMES}
    w["subject_match"] = 0.08
    w["claim_align"] = 0.08
    w["time_anchor"] = 0.03
    for role, unit in ROLE_UNIT.items():
        w[f"role_{role}"] = round(_R6_ROLE * float(unit), 4)
    return w


def l2(coeff: dict[str, float]) -> float:
    return math.sqrt(sum(float(v) ** 2 for v in coeff.values()))


def augment_features(
    feats: dict[str, dict[str, float]],
    metas: dict[str, dict[str, Any]],
    url_of: dict[str, str],
) -> dict[str, str]:
    """把渠道层级和角色独热写进已有特征。返回 para_id → tier。"""
    tiers: dict[str, str] = {}
    for pid, meta in metas.items():
        feat = feats.setdefault(pid, {})
        role = str(meta.get("fine_role") or "commentary")
        url = url_of.get(str(meta.get("doc_id") or ""), "")
        tier = channel_tier(url, str(meta.get("title") or ""))
        tiers[pid] = tier
        cred = meta.get("credibility")
        feat["credibility"] = float(cred) if isinstance(cred, (int, float)) else 0.0
        ch = str(meta.get("channel") or "")
        feat["channel_self"] = 1.0 if ch in {"weibo_self", "self_post"} else 0.0
        for r in FINE_ROLES:
            feat[f"role_{r}"] = 1.0 if role == r else 0.0
        for t in TIERS:
            feat[f"tier_{t}"] = 1.0 if tier == t else 0.0
    return tiers


def score_of(
    rrf: float,
    feats: dict[str, float],
    coeff: dict[str, float],
    names: tuple[str, ...] | None = None,
) -> float:
    total = float(rrf)
    for name in (names or FEATURE_NAMES):
        total += float(coeff.get(name) or 0.0) * float(feats.get(name) or 0.0)
    return total


def rank_questions(
    bundles: list[dict[str, Any]],
    coeff: dict[str, float],
    names: tuple[str, ...] | None = None,
) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    for b in bundles:
        scores: dict[str, float] = {}
        for pid, rrf in b["rrf"].items():
            scores[pid] = score_of(rrf, b["feats"].get(pid) or {}, coeff, names)
        best: dict[str, float] = {}
        for rep, members in b["groups"].items():
            vals = [scores[m] for m in members if m in scores]
            if vals:
                best[rep] = max(vals)
        ranked = sorted(best.items(), key=lambda x: (-x[1], x[0]))
        out[b["qid"]] = [(pid, round(sc, 6)) for pid, sc in ranked]
    return out


def _hits(ranked: list[tuple[str, float]], l2: list[str], k: int) -> list[str]:
    top = {pid for pid, _ in ranked[:k]}
    return [g for g in l2 if g in top]


def evaluate(
    bundles: list[dict[str, Any]],
    coeff: dict[str, float],
    *,
    k7: int,
    k15: int,
    names: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    ranked = rank_questions(bundles, coeff, names)
    per = []
    for b in bundles:
        order = ranked[b["qid"]]
        h7 = _hits(order, b["l2"], k7)
        h15 = _hits(order, b["l2"], k15)
        pos = {pid: i for i, (pid, _) in enumerate(order, 1)}
        cap = len(order) + 1
        capped = [pos.get(g) or cap for g in b["l2"]]
        per.append({
            "qid": b["qid"],
            "at7": h7,
            "at15": h15,
            "n7": len(h7),
            "n15": len(h15),
            "mean_capped": round(sum(capped) / len(capped), 2) if capped else None,
            "top7": [pid for pid, _ in order[:k7]],
            "ranks": {g: pos.get(g) for g in b["l2"]},
        })
    return {
        "sum7": sum(p["n7"] for p in per),
        "sum15": sum(p["n15"] for p in per),
        "mean_capped": round(sum(p["mean_capped"] or 0 for p in per) / len(per), 2) if per else None,
        "l2": round(l2(coeff), 4),
        "questions": per,
        "ranked": ranked,
    }


def _better(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """先 @7，再 @15，再金标名次，最后更小的 L2。"""
    return (
        a["sum7"],
        a["sum15"],
        -(a["mean_capped"] or 0),
        -a["l2"],
    ) > (
        b["sum7"],
        b["sum15"],
        -(b["mean_capped"] or 0),
        -b["l2"],
    )


def fit_coefficients(
    bundles: list[dict[str, Any]],
    *,
    k7: int,
    k15: int,
    init: dict[str, float] | None = None,
    laps: int = 2,
    names: tuple[str, ...] | None = None,
    grid: tuple[float, ...] | None = None,
    protect_mean: bool = False,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """坐标上升 + 向后消元。网格外的幅度直接丢掉。"""
    names = names or FEATURE_NAMES
    grid = grid or GRID
    hi, lo = max(grid), min(grid)
    w = dict(init or r6_init())
    for name in names:
        w.setdefault(name, 0.0)
        w[name] = max(min(w[name], hi), lo)
    trace: list[dict[str, Any]] = []
    best = evaluate(bundles, w, k7=k7, k15=k15, names=names)
    trace.append({"step": "init", "sum7": best["sum7"], "sum15": best["sum15"], "l2": best["l2"]})
    for lap in range(laps):
        for name in names:
            chosen = w[name]
            chosen_ev = best
            for value in grid:
                trial = dict(w)
                trial[name] = value
                ev = evaluate(bundles, trial, k7=k7, k15=k15, names=names)
                if _better(ev, chosen_ev):
                    chosen = value
                    chosen_ev = ev
            w[name] = chosen
            best = chosen_ev
        trace.append({
            "step": f"lap{lap + 1}",
            "sum7": best["sum7"],
            "sum15": best["sum15"],
            "l2": best["l2"],
        })
    # 向后消元：去掉不影响 @7/@15 的系数
    changed = True
    while changed:
        changed = False
        for name in names:
            if abs(w.get(name) or 0.0) < 1e-12:
                continue
            trial = dict(w)
            trial[name] = 0.0
            ev = evaluate(bundles, trial, k7=k7, k15=k15, names=names)
            mean_ok = (not protect_mean) or (ev["mean_capped"] or 0) <= (best["mean_capped"] or 0) + 1e-9
            if ev["sum7"] >= best["sum7"] and ev["sum15"] >= best["sum15"] and mean_ok:
                w = trial
                best = ev
                changed = True
                break
    trace.append({"step": "eliminate", "sum7": best["sum7"], "sum15": best["sum15"], "l2": best["l2"]})
    return w, trace


def sensitivity(
    bundles: list[dict[str, Any]],
    coeff: dict[str, float],
    *,
    k7: int,
    k15: int,
    names: tuple[str, ...] | None = None,
    cap: float = 0.08,
) -> list[dict[str, Any]]:
    """每个非零系数置零 / 减半 / 放大 1.5 倍（仍夹在封顶内）。"""
    names = names or FEATURE_NAMES
    base = evaluate(bundles, coeff, k7=k7, k15=k15, names=names)
    rows = []
    for name in names:
        val = float(coeff.get(name) or 0.0)
        if abs(val) < 1e-12:
            continue
        for label, factor in (("zero", 0.0), ("half", 0.5), ("x1.5", 1.5)):
            trial = dict(coeff)
            nudged = val * factor
            trial[name] = max(min(nudged, cap), -cap)
            ev = evaluate(bundles, trial, k7=k7, k15=k15, names=names)
            rows.append({
                "dim": name,
                "probe": label,
                "value": round(trial[name], 4),
                "sum7": ev["sum7"],
                "sum15": ev["sum15"],
                "d7": ev["sum7"] - base["sum7"],
                "d15": ev["sum15"] - base["sum15"],
            })
    return rows


# 确认基础维名字没有和 R6 漂移
assert set(_BASE_DIMS).issuperset({"subject_match", "claim_align", "amount_status", "time_anchor"})
