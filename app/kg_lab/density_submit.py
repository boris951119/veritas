"""R22：盒内密度约束的可变交卷 k（3～7）。

优先保证「核心段」占比 ≥ 2/3；不够则缩小 k。
高相关非核心只补位，不回填稀释。不读金标 id。

R24：通稿／近同文簇内只留代表；裁决题软保对立侧／双侧入盒。
"""

from __future__ import annotations

from typing import Any

from app.kg_lab.intent_routes import (
    _CLOCK_KEY,
    anchor_hits,
    core_rank_score,
    is_core_candidate,
    related_filler,
)
from app.kg_lab.source_role import _norm, jaccard_containment, longest_shared_span

TARGET_DENSITY = 2.0 / 3.0
K_MIN = 3
K_MAX = 7

# 近同文／通稿茎簇：Jaccard／包含度／最长共茎任一过阈即并簇
_NEAR_JAC = 0.52
_NEAR_CONT = 0.86
_NEAR_SPAN = 26


def _text_fp(metas: dict[str, dict[str, Any]], pid: str) -> str:
    return _norm(str((metas.get(pid) or {}).get("text") or ""))[:96]


def _norm_body(metas: dict[str, dict[str, Any]], pid: str) -> str:
    return _norm(str((metas.get(pid) or {}).get("text") or ""))


def _near_dup(na: str, nb: str) -> bool:
    """通稿近同文：短通报改写／镜像转载。

    长段只按高 Jaccard／强包含并簇——共引同一句查明结论不算整段近同文，
    否则对立查明金标会被互相挤掉。
    """
    if not na or not nb:
        return False
    if na[:96] == nb[:96]:
        return True
    a, b = na[:180], nb[:180]
    jac, cont = jaccard_containment(a, b)
    short = min(len(na), len(nb)) < 110
    if short:
        if jac >= _NEAR_JAC or cont >= _NEAR_CONT:
            return True
        return longest_shared_span(a, b, min_len=18) >= _NEAR_SPAN
    # 长段：近全文转载才并
    return jac >= 0.68 or (cont >= 0.92 and jac >= 0.50)


def _side_of(
    pid: str,
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    anchors: dict[str, list[str]] | None,
) -> str:
    text = str((metas.get(pid) or {}).get("text") or "")
    hits = anchor_hits(text, anchors)
    if hits["side"]:
        return str(hits["side"])
    return str((feats.get(pid) or {}).get("option_side") or "") or "other"


def _cluster_wire_keep_one(
    scored_cores: list[tuple[float, str]],
    metas: dict[str, dict[str, Any]],
) -> list[tuple[float, str]]:
    """通稿／近同文簇：已按分降序，簇内只留最先（最高分）一条。"""
    kept: list[tuple[float, str]] = []
    norms: list[str] = []
    for sc, pid in scored_cores:
        body = _norm_body(metas, pid)
        if any(_near_dup(body, kn) for kn in norms):
            continue
        kept.append((sc, pid))
        norms.append(body)
    return kept


def _soft_side_pack(
    cores: list[str],
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    route: str,
    anchors: dict[str, list[str]] | None,
) -> tuple[list[str], list[str]]:
    """裁决题软保位，返回 (有侧核心, 降为补位的无侧核心)。

    1) 双侧主张段优先于单侧通稿（同侧独占至多 1）；
    2) 无侧别权威段不占核心槽，改补位（防挤对立金标近似段）。
    """
    if route != "adjudicate" or not cores:
        return cores, []
    # 仅钟点对撞题启用双侧优先／同侧封顶；其它对立题只做近同文簇（防伤 us）
    clock_route = any(
        _CLOCK_KEY.search(k or "")
        for k in list((anchors or {}).get("side_a") or [])
        + list((anchors or {}).get("side_b") or [])
    )
    if not clock_route:
        return cores, []
    sided: list[str] = []
    unsided: list[str] = []
    for pid in cores:
        side = _side_of(pid, feats=feats, metas=metas, anchors=anchors)
        if side in {"option_a", "option_b", "both"}:
            sided.append(pid)
        else:
            unsided.append(pid)
    boths: list[str] = []
    excl: list[str] = []
    deferred: list[str] = []
    side_n = {"option_a": 0, "option_b": 0}
    for pid in sided:
        side = _side_of(pid, feats=feats, metas=metas, anchors=anchors)
        if side == "both":
            boths.append(pid)
            continue
        if side in side_n:
            if side_n[side] >= 1:
                deferred.append(pid)
                continue
            side_n[side] += 1
            excl.append(pid)
    return boths + excl + deferred, unsided


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
    """核心按 rank 分排序；近同文／通稿茎簇去重后再拼补位／其余。"""
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
    # R24：通稿／近同文簇内留代表（比精确指纹更宽）
    scored_cores = _cluster_wire_keep_one(scored_cores, metas)
    # 精确指纹兜底（同文不同空白）
    cores: list[str] = []
    fp_seen: set[str] = set()
    for sc, pid in scored_cores:
        fp = _text_fp(metas, pid)
        if fp in fp_seen:
            continue
        fp_seen.add(fp)
        cores.append(pid)
    cores, demoted = _soft_side_pack(
        cores, feats=feats, metas=metas, route=route, anchors=anchors,
    )

    # 自然补位优先；无侧降档段垫后（不抢对立补位槽）
    fillers_scored = sorted(
        fillers,
        key=lambda p: -core_rank_score(
            p, feats=feats, metas=metas, route=route,
            pool_pos=pool_pos, anchors=anchors, url_of=url_of,
        ),
    )
    fill_kept: list[str] = []
    fill_norms = [_norm_body(metas, p) for p in cores]
    for pid in fillers_scored + demoted:
        if pid in cores or pid in fill_kept:
            continue
        body = _norm_body(metas, pid)
        if any(_near_dup(body, kn) for kn in fill_norms):
            continue
        fill_kept.append(pid)
        fill_norms.append(body)
    packed = cores + fill_kept + rest
    return packed, cores, fill_kept


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
