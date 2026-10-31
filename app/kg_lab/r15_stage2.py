"""R15 二筛：大盒里重拟合加权和，踢掉之后再缩到交卷前 7。不读金标 id。"""

from __future__ import annotations

from typing import Any

from app.kg_lab.inbox_rerank import _swallows
from app.kg_lab.r14_stages import STAGE2_GRID, stage2_features, stage2_score
from app.kg_lab.r8_fit import l2

R15_EXTRA: tuple[str, ...] = ("roundup", "stage1_norm", "stitch_host")
R15_DIMS: tuple[str, ...] = (
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
    "roundup",
    "stage1_norm",
    "stitch_host",
)


def _roundup(pid: str, bundle: dict[str, Any]) -> float:
    feat = bundle["feats"].get(pid) or {}
    meta = bundle["metas"].get(pid) or {}
    cmt = str(feat.get("r9_comment") or "")
    role = str(meta.get("fine_role") or "")
    if cmt in {"mixed_roundup", "pure_opinion"} or role == "mixed_summary":
        return 1.0
    return 0.0


def mark_stitch_hosts(bundle: dict[str, Any], pool_ids: list[str]) -> None:
    """池内谁把另一段整句吞进去。不看金标。"""
    texts = {pid: str((bundle["metas"].get(pid) or {}).get("text") or "") for pid in pool_ids}
    hosts = set()
    for host in pool_ids:
        for piece in pool_ids:
            if host != piece and _swallows(texts[host], texts[piece]):
                hosts.add(host)
                break
    for pid, feat in bundle["feats"].items():
        feat["stitch_host"] = 1.0 if pid in hosts else 0.0


def r15_features(pid: str, bundle: dict[str, Any], stage1_norm: float) -> dict[str, float]:
    feat = stage2_features(pid, bundle)
    raw = bundle["feats"].get(pid) or {}
    feat["roundup"] = _roundup(pid, bundle)
    feat["stage1_norm"] = float(stage1_norm)
    feat["stitch_host"] = float(raw.get("stitch_host") or 0.0)
    feat["identity_resume"] = float(raw.get("identity_resume") or feat.get("identity_resume") or 0.0)
    return feat


def pool_rows(
    bundles: list[dict[str, Any]],
    ranked: dict[str, list[tuple[str, float]]],
    pool: int,
) -> list[dict[str, Any]]:
    rows = []
    for b in bundles:
        order = ranked[b["qid"]][:pool]
        scores = [sc for _pid, sc in order]
        lo, hi = min(scores), max(scores)
        span = hi - lo if hi > lo else 1.0
        mark_stitch_hosts(b, [pid for pid, _ in order])
        l2 = set(b["l2"])
        for rank, (pid, sc) in enumerate(order, 1):
            rows.append({
                "qid": b["qid"],
                "id": pid,
                "gold": pid in l2,
                "rank": rank,
                "feat": r15_features(pid, b, (sc - lo) / span),
            })
    return rows


def cut_question(rows: list[dict[str, Any]], coeff: dict[str, float], names: tuple[str, ...], k: int) -> list[dict[str, Any]]:
    """分数 < 0 踢掉，剩下按分数再缩到 k。被踢的不补回。"""
    alive = []
    for row in rows:
        score = stage2_score(row["feat"], coeff, names)
        if score >= 0.0:
            alive.append((score, row["rank"], row))
    alive.sort(key=lambda x: (-x[0], x[1], x[2]["id"]))
    return [row for _s, _r, row in alive[:k]]


def evaluate_r15(
    rows: list[dict[str, Any]],
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    k: int = 7,
) -> dict[str, Any]:
    by_q: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_q.setdefault(row["qid"], []).append(row)
    gold_kept = 0
    nongold_kept = 0
    detail = {}
    for qid, group in by_q.items():
        chosen = cut_question(group, coeff, names, k)
        detail[qid] = [r["id"] for r in chosen]
        gold_kept += sum(1 for r in chosen if r["gold"])
        nongold_kept += sum(1 for r in chosen if not r["gold"])
    return {
        "gold_kept": gold_kept,
        "nongold_kept": nongold_kept,
        "l2": round(l2({n: coeff.get(n, 0.0) for n in names}), 4),
        "by_q": detail,
    }


def _better(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (a["gold_kept"], -a["nongold_kept"], -a["l2"]) > (
        b["gold_kept"], -b["nongold_kept"], -b["l2"],
    )


def fit_r15(
    rows: list[dict[str, Any]],
    *,
    names: tuple[str, ...] = R15_DIMS,
    grid: tuple[float, ...] = STAGE2_GRID,
    laps: int = 2,
    k: int = 7,
) -> tuple[dict[str, float], list[dict[str, Any]], dict[str, Any]]:
    hi, lo = max(grid), min(grid)
    w = {n: 0.0 for n in names}
    best = evaluate_r15(rows, w, names, k=k)
    trace = [{"step": "init", "gold_kept": best["gold_kept"], "nongold_kept": best["nongold_kept"], "l2": best["l2"]}]
    for lap in range(laps):
        for name in names:
            chosen = w[name]
            chosen_ev = best
            for value in grid:
                trial = dict(w)
                trial[name] = value
                ev = evaluate_r15(rows, trial, names, k=k)
                if _better(ev, chosen_ev):
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
            ev = evaluate_r15(rows, trial, names, k=k)
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
