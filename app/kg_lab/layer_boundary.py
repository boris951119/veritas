"""R42：低耦合拆装边界——禁整套召回系数进 pack_material。

三层契约（只出窄面，不泄漏多维系数／feats／weights）：

1. Stage1＝进池：``pool_ids``／``pool_ranked``（id＋可选序分，无 coeff）
2. Stage2／装箱＝少而密＋冲突成对：``box_ids``／``k``／``conflict_pairs``
3. 交卷＝rank＋树17引用信号：``rank_order``／``conflict_pairs``／``tree17``

主线接法：``pack_hints_from_submit`` → 只给
``priority_segment_ids``／``focus_segment_ids``／``max_segments``；
``pack_material`` 本身不吃系数向量。本模块证明「拆得开、接得住」，
不把整包实验栈并入主线。
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "r42.v1"

# 交卷／pack 提示面禁止出现的键（递归审计）
FORBIDDEN_PACK_KEYS = frozenset({
    "coeff",
    "coeffs",
    "weights",
    "w_eff",
    "feats",
    "features",
    "feature_vector",
    "multidim",
    "stage1_coeff",
    "r8_coeff",
    "r9_coeff",
    "names",
    "portable_authority_weights",
})

# 交卷窄面允许的顶层键
ALLOWED_SUBMIT_TOP = frozenset({
    "schema_version",
    "layer",
    "rank_order",
    "k",
    "conflict_pairs",
    "tree17",
    "density_public",
    "route",
})


def audit_forbidden_keys(obj: Any, *, path: str = "$") -> list[str]:
    """递归扫键名；命中 FORBIDDEN_PACK_KEYS 则记路径。"""
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k)
            here = f"{path}.{key}"
            if key in FORBIDDEN_PACK_KEYS:
                hits.append(here)
            hits.extend(audit_forbidden_keys(v, path=here))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            hits.extend(audit_forbidden_keys(v, path=f"{path}[{i}]"))
    return hits


def stage1_pool_export(
    pool_ranked: list[tuple[str, float]] | list[list[Any]],
    *,
    pool_n: int = 20,
) -> dict[str, Any]:
    """一筛出口：只进池。保留 id 序；分数仅作池内相对序披露，不外泄系数。"""
    rows: list[dict[str, Any]] = []
    for i, item in enumerate(pool_ranked[: max(0, int(pool_n))], 1):
        if isinstance(item, (list, tuple)) and len(item) >= 1:
            pid = str(item[0])
            sc = float(item[1]) if len(item) > 1 else 0.0
        else:
            continue
        rows.append({"id": pid, "pool_rank": i, "pool_score": round(sc, 6)})
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "stage1_pool",
        "pool_n": int(pool_n),
        "pool_ids": [r["id"] for r in rows],
        "pool_ranked": rows,
    }


def stage2_box_export(authority_out: dict[str, Any]) -> dict[str, Any]:
    """二筛／密度出口：少而密盒＋冲突成对。剥掉 scores／feats／weights。"""
    dens = authority_out.get("density") if isinstance(authority_out.get("density"), dict) else {}
    top = list(authority_out.get("top_ids") or [])
    if not top and dens:
        top = list(dens.get("submission") or [])
    k = int(authority_out.get("k") or dens.get("k") or len(top) or 0)
    box = list(top[:k] if k else top)
    raw_pairs = authority_out.get("conflict_pairs")
    # authority 出口是 dict（options／conflicts／…）；只留 id 侧别，剥掉 authority 浮点
    clean_pairs: dict[str, Any] = {
        "options": [],
        "support": [],
        "oppose": [],
        "conflicts": [],
    }
    if isinstance(raw_pairs, dict):
        clean_pairs["options"] = [str(x) for x in (raw_pairs.get("options") or [])]
        clean_pairs["support"] = [
            {"id": str(x.get("id") or ""), "option": str(x.get("option") or "")}
            for x in (raw_pairs.get("support") or [])
            if isinstance(x, dict)
        ]
        clean_pairs["oppose"] = [
            {"id": str(x.get("id") or ""), "option": str(x.get("option") or "")}
            for x in (raw_pairs.get("oppose") or [])
            if isinstance(x, dict)
        ]
        for p in raw_pairs.get("conflicts") or []:
            if not isinstance(p, dict):
                continue
            clean_pairs["conflicts"].append({
                "support_id": str(p.get("support_id") or ""),
                "oppose_id": str(p.get("oppose_id") or ""),
                "support_option": str(p.get("support_option") or ""),
                "oppose_option": str(p.get("oppose_option") or ""),
                "preferred": str(p.get("preferred") or ""),
                "reason": str(p.get("reason") or "authority_over_similarity"),
            })
    elif isinstance(raw_pairs, list):
        for p in raw_pairs:
            if not isinstance(p, dict):
                continue
            clean_pairs["conflicts"].append({
                "support_id": str(p.get("support_id") or p.get("a") or ""),
                "oppose_id": str(p.get("oppose_id") or p.get("b") or ""),
                "reason": str(p.get("kind") or p.get("reason") or "option_conflict"),
            })
    intent = authority_out.get("intent") if isinstance(authority_out.get("intent"), dict) else {}
    route = str(intent.get("route") or authority_out.get("route") or "")
    dens_public = {
        "k": dens.get("k"),
        "n_core": dens.get("n_core"),
        "n_filler": dens.get("n_filler"),
        "proxy_density": dens.get("proxy_density"),
        "met_target": dens.get("met_target"),
        "route": dens.get("route") or route,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "stage2_box",
        "box_ids": box,
        "k": k,
        "conflict_pairs": clean_pairs,
        "route": route,
        "density_public": dens_public,
        "swallowed_n": len(authority_out.get("swallowed") or []),
        "near_dup_dropped_n": len(authority_out.get("near_dup_dropped") or []),
    }


def tree17_signal_export(plan: dict[str, Any] | None) -> dict[str, Any]:
    """树17交卷信号：细读 id／成对／标签——无 feats、无系数。"""
    if not plan:
        return {
            "close_read_ids": [],
            "pair_required": False,
            "conflict_route": False,
            "labels": [],
        }
    items = list(plan.get("items") or [])
    labels = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if not it.get("in_close_read"):
            continue
        labels.append({
            "id": str(it.get("para_id") or ""),
            "label": str(it.get("label") or ""),
            "side": str(it.get("side") or ""),
            "stance": str(it.get("stance") or ""),
        })
    return {
        "close_read_ids": [str(x) for x in (plan.get("close_read") or [])],
        "pair_required": bool(plan.get("pair_required")),
        "conflict_route": bool(plan.get("conflict_route")),
        "labels": labels,
    }


def build_submit_surface(
    box_export: dict[str, Any],
    *,
    tree17_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """交卷窄面：rank 序＋conflict_pairs＋树17信号。"""
    order = list(box_export.get("box_ids") or [])
    k = int(box_export.get("k") or len(order))
    raw_pairs = box_export.get("conflict_pairs")
    if isinstance(raw_pairs, dict):
        pairs_out: Any = raw_pairs
    elif isinstance(raw_pairs, list):
        pairs_out = raw_pairs
    else:
        pairs_out = {"options": [], "support": [], "oppose": [], "conflicts": []}
    surface = {
        "schema_version": SCHEMA_VERSION,
        "layer": "submit",
        "rank_order": order[:k],
        "k": k,
        "conflict_pairs": pairs_out,
        "tree17": tree17_signal_export(tree17_plan),
        "density_public": dict(box_export.get("density_public") or {}),
        "route": str(box_export.get("route") or ""),
    }
    extra = set(surface) - ALLOWED_SUBMIT_TOP
    if extra:
        raise ValueError(f"submit surface leaked keys: {sorted(extra)}")
    leaks = audit_forbidden_keys(surface)
    if leaks:
        raise ValueError(f"submit surface forbidden keys: {leaks}")
    return surface


def pack_hints_from_submit(surface: dict[str, Any]) -> dict[str, Any]:
    """主线 pack_material 可接提示——仅 id 序与硬顶，绝不含系数。

    - priority_segment_ids → 议题槽优先入箱（answer_slots）
    - focus_segment_ids → 分析师提示词焦点（树17细读优先，否则整盒序）
    - max_segments → C-81 段数硬顶（可选；默认关的生产路径可不传）
    """
    order = [str(x) for x in (surface.get("rank_order") or []) if str(x).strip()]
    t17 = surface.get("tree17") if isinstance(surface.get("tree17"), dict) else {}
    close = [str(x) for x in (t17.get("close_read_ids") or []) if str(x).strip()]
    hints = {
        "priority_segment_ids": list(order),
        "focus_segment_ids": list(close or order),
        "max_segments": int(surface.get("k") or len(order) or 0) or None,
        "conflict_pairs": list(surface.get("conflict_pairs") or []),
    }
    leaks = audit_forbidden_keys(hints)
    if leaks:
        raise ValueError(f"pack hints forbidden keys: {leaks}")
    return hints


def assert_submit_no_coeff(surface: dict[str, Any]) -> None:
    leaks = audit_forbidden_keys(surface)
    if leaks:
        raise AssertionError(f"coeff/feats leaked into submit: {leaks}")
    bad_top = set(surface) - ALLOWED_SUBMIT_TOP
    if bad_top:
        raise AssertionError(f"unexpected submit top keys: {sorted(bad_top)}")


def borrowable_checklist() -> list[dict[str, str]]:
    """可借鉴清单：每项挂哪一层、主线怎么接。"""
    return [
        {
            "item": "可变 k＋密度约束（TARGET≥2/3，k∈[3,7]）",
            "layer": "stage2／density_submit",
            "module": "app/kg_lab/density_submit.py::density_constrained_submit",
            "mainline_hook": (
                "交卷只带 rank_order＋k；主线可用 max_segments=k 或 "
                "priority_segment_ids=rank_order；勿把密度扫描系数塞进 pack_material"
            ),
        },
        {
            "item": "conflict_pairs（support vs oppose 成对）",
            "layer": "stage2／authority_rerank 出口",
            "module": "app/kg_lab/stage2_authority.py::build_conflict_pairs",
            "mainline_hook": (
                "SubmitSurface.conflict_pairs → 报告冲突节／质证；"
                "装箱只消费 id，不消费权威权重"
            ),
        },
        {
            "item": "通稿／近同文簇 keep-one（抗挤）",
            "layer": "stage2／density_submit 簇内代表",
            "module": "app/kg_lab/density_submit.py::_cluster_wire_keep_one",
            "mainline_hook": (
                "留在二筛；主线 pack_material 已有 duplicate_map，"
                "勿再灌实验簇系数；接盒结果即可"
            ),
        },
        {
            "item": "繁简对照折叠（近同判定用，不改原文）",
            "layer": "stage2／density_submit 指纹归一",
            "module": "app/kg_lab/density_submit.py::_TRAD_TO_SIMP",
            "mainline_hook": (
                "属二筛簇判据；主线若复用只进近同检测，不进 pack 参数面"
            ),
        },
        {
            "item": "树17 引用纪律（细读带宽／成对／采信·对立标签）",
            "layer": "submit／L3（盒后）",
            "module": "app/kg_lab/tree17_cite.py::apply_tree17_cite / attach_tree17_plan",
            "mainline_hook": (
                "accounting['tree17_cite']＋focus_segment_ids=close_read；"
                "提示词注入，零改 pack_material 签名"
            ),
        },
        {
            "item": "一筛多维系数（R9／R21）",
            "layer": "stage1_pool 内部",
            "module": "app/kg_lab/r8_fit.py::evaluate + r21_coeff",
            "mainline_hook": (
                "系数只活在一筛打分；出口仅 pool_ids。"
                "若动系数须整套重拟合 ±0.08；禁止整包进 pack_material"
            ),
        },
        {
            "item": "二筛权威权重（DEFAULT_WEIGHTS）",
            "layer": "stage2 内部 portable_authority_unit",
            "module": "app/kg_lab/stage2_authority.py::DEFAULT_WEIGHTS",
            "mainline_hook": (
                "权重只服务盒内裁决；交卷只留 rank／pairs。"
                "主线接盒序，不接 weights dict"
            ),
        },
    ]


def describe_boundaries() -> dict[str, Any]:
    """接口／模块边界说明（报告用）。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "layers": {
            "stage1_pool": {
                "owns": ["pool_ids", "pool_ranked"],
                "forbids_out": sorted(FORBIDDEN_PACK_KEYS),
                "modules": ["app/kg_lab/stage1_pool.py", "app/kg_lab/r8_fit.py"],
            },
            "stage2_box": {
                "owns": ["box_ids", "k", "conflict_pairs", "density_public"],
                "forbids_out": sorted(FORBIDDEN_PACK_KEYS),
                "modules": [
                    "app/kg_lab/stage2_authority.py",
                    "app/kg_lab/density_submit.py",
                ],
            },
            "submit": {
                "owns": ["rank_order", "conflict_pairs", "tree17"],
                "forbids_out": sorted(FORBIDDEN_PACK_KEYS),
                "modules": ["app/kg_lab/layer_boundary.py", "app/kg_lab/tree17_cite.py"],
            },
            "mainline_pack": {
                "function": "app/core/material.py::pack_material",
                "accepts_from_lab": [
                    "priority_segment_ids (via answer_slots / hints)",
                    "focus_segment_ids (analyst prompt)",
                    "max_segments (optional hard cap)",
                ],
                "must_not_accept": sorted(FORBIDDEN_PACK_KEYS),
            },
        },
        "borrowable": borrowable_checklist(),
    }
