"""C-107：分析师 R44／R42 交卷窄面——主线只借鉴、禁整包灌系数。

薄适配自 veritas-obsidian-kg-exp ``app/kg_lab/layer_boundary.py``。
主线接法：``pack_hints_from_submit`` → 只给
``priority_segment_ids``／``focus_segment_ids``／``max_segments``；
``pack_material`` 签名零改、不吃系数向量。

实验旗 ``VERITAS_KG_SUBMIT_SURFACE`` 默认关；旗关＝现主线行为。
"""

from __future__ import annotations

import os
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
    "DEFAULT_WEIGHTS",
    "r21_coeff",
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

# pack_material(**kwargs) 禁止出现的参数名（禁键泄漏闸）
FORBIDDEN_PACK_PARAM_NAMES = frozenset(FORBIDDEN_PACK_KEYS) | frozenset({
    "priority_segment_ids",  # 走 answer_slots／accounting，不进 pack kwargs
    "focus_segment_ids",     # 走分析师提示词，不进 pack kwargs
    "conflict_pairs",
})


def kg_submit_surface_enabled(settings: Any | None = None) -> bool:
    """C-108 默认开。settings 优先；env＝0 回退关。"""
    if settings is not None and hasattr(settings, "kg_submit_surface"):
        return bool(getattr(settings, "kg_submit_surface"))
    v = (os.environ.get("VERITAS_KG_SUBMIT_SURFACE") or "").strip().lower()
    if v in ("0", "false", "off", "no"):
        return False
    if v in ("1", "true", "on", "yes"):
        return True
    return True


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


def assert_clean_pack_kwargs(kwargs: dict[str, Any]) -> None:
    """装箱 kwargs 禁键／禁参名闸——泄漏＝0。"""
    if not isinstance(kwargs, dict):
        raise TypeError("pack kwargs must be dict")
    bad_names = sorted(set(kwargs) & FORBIDDEN_PACK_PARAM_NAMES)
    if bad_names:
        raise ValueError(f"forbidden pack kwargs names: {bad_names}")
    # 只允许 pack_material 已知可选面
    allowed = {
        "budget_chars", "exclude_seg_ids", "max_segments",
        "fill_zero_score", "min_bm25",
    }
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise ValueError(f"unknown pack kwargs: {unknown}")
    leaks = audit_forbidden_keys(kwargs)
    if leaks:
        raise ValueError(f"forbidden keys inside pack kwargs: {leaks}")


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
    dens = (authority_out.get("density")
            if isinstance(authority_out.get("density"), dict) else {})
    top = list(authority_out.get("top_ids") or [])
    if not top and dens:
        top = list(dens.get("submission") or [])
    k = int(authority_out.get("k") or dens.get("k") or len(top) or 0)
    box = list(top[:k] if k else top)
    raw_pairs = authority_out.get("conflict_pairs")
    clean_pairs: dict[str, Any] = {
        "options": [],
        "support": [],
        "oppose": [],
        "conflicts": [],
    }
    if isinstance(raw_pairs, dict):
        clean_pairs["options"] = [
            str(x) for x in (raw_pairs.get("options") or [])]
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
    intent = (authority_out.get("intent")
              if isinstance(authority_out.get("intent"), dict) else {})
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
        pairs_out = {
            "options": [], "support": [], "oppose": [], "conflicts": [],
        }
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

    - priority_segment_ids → 议题槽优先入箱（answer_slots 覆盖）
    - focus_segment_ids → 分析师提示词焦点（树17细读优先，否则整盒序）
    - max_segments → C-81 段数硬顶
    - conflict_pairs → 报告／质证冲突节（dict 洗净面，不 list 化）
    """
    order = [
        str(x) for x in (surface.get("rank_order") or []) if str(x).strip()
    ]
    t17 = (surface.get("tree17")
           if isinstance(surface.get("tree17"), dict) else {})
    close = [
        str(x) for x in (t17.get("close_read_ids") or []) if str(x).strip()
    ]
    raw_pairs = surface.get("conflict_pairs")
    if isinstance(raw_pairs, dict):
        pairs_out: Any = raw_pairs
    elif isinstance(raw_pairs, list):
        pairs_out = list(raw_pairs)
    else:
        pairs_out = {
            "options": [], "support": [], "oppose": [], "conflicts": [],
        }
    hints = {
        "priority_segment_ids": list(order),
        "focus_segment_ids": list(close or order),
        "max_segments": int(surface.get("k") or len(order) or 0) or None,
        "conflict_pairs": pairs_out,
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


def resolve_submit_surface(dossier: Any) -> dict[str, Any] | None:
    """从 accounting 取交卷窄面（``kg_submit`` 或 ``submit_surface``）。"""
    acc = getattr(dossier, "accounting", None) or {}
    for key in ("kg_submit", "submit_surface"):
        raw = acc.get(key)
        if isinstance(raw, dict) and raw:
            return raw
    return None


def apply_kg_submit_surface(
    dossier: Any,
    surface: dict[str, Any] | None = None,
    *,
    enabled: bool | None = None,
) -> dict[str, Any] | None:
    """旗开且有窄面输入时写入 accounting／accounting；否则零行为。

    返回 hints；无输入或旗关返回 None（不写 kg_submit_active）。
    """
    if enabled is None:
        enabled = kg_submit_surface_enabled()
    if not enabled:
        return None
    surf = surface if isinstance(surface, dict) else resolve_submit_surface(dossier)
    if not surf:
        return None
    assert_submit_no_coeff(surf)
    hints = pack_hints_from_submit(surf)
    acc = getattr(dossier, "accounting", None)
    if acc is None:
        dossier.accounting = {}
        acc = dossier.accounting
    acc["kg_submit"] = dict(surf)
    acc["kg_pack_hints"] = {
        "priority_segment_ids": list(hints["priority_segment_ids"]),
        "focus_segment_ids": list(hints["focus_segment_ids"]),
        "max_segments": hints["max_segments"],
    }
    acc["kg_conflict_pairs"] = hints["conflict_pairs"]
    acc["kg_focus_segment_ids"] = list(hints["focus_segment_ids"])
    acc["kg_priority_segment_ids"] = list(hints["priority_segment_ids"])
    t17 = surf.get("tree17") if isinstance(surf.get("tree17"), dict) else {}
    acc["tree17_cite"] = dict(t17)
    acc["kg_submit_active"] = True
    return hints


def kg_priority_override(dossier: Any) -> list[str] | None:
    """旗开且已 apply 时返回 rank_order；否则 None＝走现产 priority。"""
    acc = getattr(dossier, "accounting", None) or {}
    if not acc.get("kg_submit_active"):
        return None
    ids = acc.get("kg_priority_segment_ids") or []
    out = [str(x) for x in ids if str(x).strip()]
    return out if out else None


def kg_focus_segment_ids(dossier: Any) -> list[str] | None:
    """旗开且已 apply 时返回 focus；否则 None。"""
    acc = getattr(dossier, "accounting", None) or {}
    if not acc.get("kg_submit_active"):
        return None
    ids = acc.get("kg_focus_segment_ids") or []
    out = [str(x) for x in ids if str(x).strip()]
    return out if out else None


def pack_kwargs_for_kg(dossier: Any) -> dict[str, Any]:
    """仅 max_segments；禁系数键。旗关／未 apply → {}。

    C-108：默认不硬顶（``kg_cap_segments`` 假）——密度盒序只走
    priority；预算尾仍可填。``VERITAS_KG_CAP_SEGMENTS=1`` 才写入
    max_segments=k。
    """
    acc = getattr(dossier, "accounting", None) or {}
    if not acc.get("kg_submit_active"):
        return {}
    hints = acc.get("kg_pack_hints") or {}
    out: dict[str, Any] = {}
    ms = hints.get("max_segments")
    cap = bool(acc.get("kg_cap_segments"))
    if cap and ms is not None and int(ms) > 0:
        out["max_segments"] = int(ms)
    assert_clean_pack_kwargs(out)
    return out


def borrowable_checklist() -> list[dict[str, str]]:
    """可借鉴清单（C-107 第 1 步只接 pairs／树17／k＋rank；密度下一步）。"""
    return [
        {
            "item": "可变 k＋密度约束（TARGET≥2/3，k∈[3,7]）",
            "layer": "stage2／density_submit",
            "module": "exp:density_submit（本步不迁）",
            "mainline_hook": (
                "交卷只带 rank_order＋k；主线 max_segments=k 或 "
                "priority_segment_ids=rank_order；勿塞密度扫描系数"
            ),
            "c107_step1": "接 k／rank；不迁 density_submit 整段",
        },
        {
            "item": "conflict_pairs（support vs oppose 成对）",
            "layer": "submit",
            "module": "app/core/kg_submit_surface.py",
            "mainline_hook": (
                "accounting['kg_conflict_pairs'] → 报告冲突节；"
                "装箱只消费 segment id"
            ),
            "c107_step1": "已接",
        },
        {
            "item": "树17 引用纪律（细读／成对标签）",
            "layer": "submit／L3",
            "module": "app/core/kg_submit_surface.py::tree17_signal_export",
            "mainline_hook": (
                "accounting['tree17_cite']＋focus_segment_ids；"
                "零改 pack_material 签名"
            ),
            "c107_step1": "已接",
        },
        {
            "item": "一筛多维系数（R9／R21）",
            "layer": "stage1_pool 内部",
            "module": "exp only",
            "mainline_hook": "禁止整包进 pack_material",
            "c107_step1": "不借鉴",
        },
        {
            "item": "二筛权威权重（DEFAULT_WEIGHTS）",
            "layer": "stage2 内部",
            "module": "exp only",
            "mainline_hook": "主线接盒序，不接 weights dict",
            "c107_step1": "不借鉴",
        },
    ]


def describe_boundaries() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "flag": "VERITAS_KG_SUBMIT_SURFACE",
        "flag_default": False,
        "layers": {
            "submit": {
                "owns": ["rank_order", "conflict_pairs", "tree17", "k"],
                "forbids_out": sorted(FORBIDDEN_PACK_KEYS),
                "modules": ["app/core/kg_submit_surface.py"],
            },
            "mainline_pack": {
                "function": "app/core/material.py::pack_material",
                "accepts_from_lab": [
                    "priority_segment_ids (via answer_slots override)",
                    "focus_segment_ids (analyst prompt)",
                    "max_segments (optional hard cap)",
                ],
                "must_not_accept": sorted(FORBIDDEN_PACK_KEYS),
            },
        },
        "borrowable": borrowable_checklist(),
    }
