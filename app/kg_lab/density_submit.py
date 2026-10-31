"""R22：盒内密度约束的可变交卷 k（3～7）。

优先保证「核心段」占比 ≥ 2/3；不够则缩小 k。
高相关非核心只补位，不回填稀释。不读金标 id。
"""

from __future__ import annotations

from typing import Any

from app.kg_lab.intent_routes import (
    core_rank_score,
    is_core_candidate,
    related_filler,
)
from app.kg_lab.source_role import _norm

TARGET_DENSITY = 2.0 / 3.0
K_MIN = 3
K_MAX = 7


def _text_fp(metas: dict[str, dict[str, Any]], pid: str) -> str:
    return _norm(str((metas.get(pid) or {}).get("text") or ""))[:96]


def pack_core_first(
    order: list[str],
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    route: str,
    pool_pos: dict[str, int] | None = None,
    anchors: dict[str, list[str]] | None = None,
    url_of: dict[str, str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """核心按 rank 分排序；近同文去重后再拼补位／其余。"""
    scored_cores: list[tuple[float, str]] = []
    fillers: list[str] = []
    rest: list[str] = []
    seen: set[str] = set()
    for pid in order:
        if not pid or pid in seen:
            continue
        seen.add(pid)
        if is_core_candidate(
            pid, feats=feats, metas=metas, route=route,
            pool_pos=pool_pos, anchors=anchors, url_of=url_of,
        ):
            sc = core_rank_score(
                pid, feats=feats, metas=metas, route=route,
                pool_pos=pool_pos, anchors=anchors, url_of=url_of,
            )
            scored_cores.append((sc, pid))
        elif related_filler(
            pid, feats=feats, metas=metas, route=route,
            anchors=anchors, pool_pos=pool_pos, url_of=url_of,
        ):
            fillers.append(pid)
        else:
            rest.append(pid)

    scored_cores.sort(key=lambda x: (-x[0], x[1]))
    # 只保留分数靠前的核心，避免假核心灌满 k=7（宁少勿滥）
    if scored_cores:
        top_sc = scored_cores[0][0]
        floor = max(0.42, top_sc - 0.38)
        scored_cores = [x for x in scored_cores if x[0] + 1e-12 >= floor][:6]
    # 近同文：同指纹只留分最高的 1 条（宁少勿滥；部委镜像不重复占盒）
    cores: list[str] = []
    fp_seen: set[str] = set()
    for sc, pid in scored_cores:
        fp = _text_fp(metas, pid)
        if fp in fp_seen:
            continue
        fp_seen.add(fp)
        cores.append(pid)

    # 补位也按核心分轻排
    fillers_scored = sorted(
        fillers,
        key=lambda p: -core_rank_score(
            p, feats=feats, metas=metas, route=route,
            pool_pos=pool_pos, anchors=anchors, url_of=url_of,
        ),
    )
    packed = cores + fillers_scored + rest
    return packed, cores, fillers_scored


def choose_density_k(
    packed: list[str],
    cores: set[str],
    fillers: set[str],
    *,
    k_min: int = K_MIN,
    k_max: int = K_MAX,
    target: float = TARGET_DENSITY,
) -> dict[str, Any]:
    """在 [k_min,k_max] 选交卷长度。

    策略：
    1. 先构造「不稀释」前缀：只放核心，再按 核心:补位 ≤ 2:1 补位（密度≥2/3）。
    2. 若前缀长度 < k_min，允许用补位凑到 k_min（可能暂时 <2/3）。
    3. 在最终候选序上扫 k：优先密度≥target 的方案，取核心数最多，其次密度，再次较小 k（宁少勿滥）。
    """
    core_list = [p for p in packed if p in cores]
    fill_list = [p for p in packed if p in fillers]
    budget_fill = max(0, len(core_list) // 2)
    kept = list(core_list)
    for f in fill_list[:budget_fill]:
        kept.append(f)
    if len(kept) < k_min:
        for f in fill_list:
            if f in kept:
                continue
            kept.append(f)
            if len(kept) >= k_min:
                break
    if len(kept) < k_min:
        for p in packed:
            if p in kept:
                continue
            kept.append(p)
            if len(kept) >= k_min:
                break

    tail = [p for p in packed if p not in set(kept)]
    cand = kept + tail

    # 达标键：密度优先，其次较小 k（宁少勿滥），再次核心数
    best_ok: tuple[float, int, float, int] | None = None  # (dens, -k, n_core, n_f)
    best_fallback: tuple[float, int, int] | None = None  # (dens, -k, n_core)

    rows = []
    for k in range(k_min, min(k_max, len(cand)) + 1):
        box = cand[:k]
        n_c = sum(1 for p in box if p in cores)
        n_f = sum(1 for p in box if p in fillers)
        dens = n_c / k if k else 0.0
        rows.append({"k": k, "n_core": n_c, "n_filler": n_f, "density": round(dens, 4)})
        if dens + 1e-12 >= target:
            key = (dens, -k, float(n_c))
            if best_ok is None or key > best_ok[:3]:
                best_ok = (dens, -k, float(n_c), n_f)
        fb = (dens, -k, n_c)
        if best_fallback is None or fb > best_fallback:
            best_fallback = fb

    if best_ok is not None:
        dens = float(best_ok[0])
        k_sel = int(-best_ok[1])
        n_c = int(best_ok[2])
        n_f = int(best_ok[3])
        met = True
    else:
        dens_f, neg_k, n_c = best_fallback if best_fallback else (0.0, -k_min, 0)
        k_sel = int(-neg_k) if best_fallback else k_min
        dens = float(dens_f)
        box = cand[:k_sel]
        n_f = sum(1 for p in box if p in fillers)
        met = dens + 1e-12 >= target

    submission = cand[:k_sel]
    return {
        "k": k_sel,
        "submission": submission,
        "n_core": sum(1 for p in submission if p in cores),
        "n_filler": sum(1 for p in submission if p in fillers),
        "n_other": sum(1 for p in submission if p not in cores and p not in fillers),
        "density": round(
            sum(1 for p in submission if p in cores) / k_sel if k_sel else 0.0, 4,
        ),
        "target": target,
        "met_target": met,
        "packed": cand,
        "scan": rows,
        "n_core_available": len(core_list),
        "n_filler_available": len(fill_list),
    }


def density_constrained_submit(
    order: list[str],
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    route: str,
    k_min: int = K_MIN,
    k_max: int = K_MAX,
    target: float = TARGET_DENSITY,
    gold_ids: set[str] | None = None,
    pool_pos: dict[str, int] | None = None,
    anchors: dict[str, list[str]] | None = None,
    url_of: dict[str, str] | None = None,
) -> dict[str, Any]:
    """主入口。gold_ids 仅评测披露真实金标密度，不参与选段。"""
    packed, core_list, fill_list = pack_core_first(
        order, feats=feats, metas=metas, route=route,
        pool_pos=pool_pos, anchors=anchors, url_of=url_of,
    )
    cores = set(core_list)
    fillers = set(fill_list)
    chosen = choose_density_k(
        packed, cores, fillers, k_min=k_min, k_max=k_max, target=target,
    )
    sub = chosen["submission"]
    out = {
        **chosen,
        "route": route,
        "core_ids": [p for p in sub if p in cores],
        "filler_ids": [p for p in sub if p in fillers],
    }
    if gold_ids is not None:
        ghit = [p for p in sub if p in gold_ids]
        out["gold_in_box"] = ghit
        out["n_gold"] = len(ghit)
        out["gold_density"] = round(len(ghit) / len(sub), 4) if sub else 0.0
    return out
