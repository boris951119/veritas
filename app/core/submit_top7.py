"""C-140：交卷硬 Top-7＋冲突成对保位（只动分析师焦点面）。

Boyu 工单件①：交卷窄面交给分析师的段＝``min(7, 候选长)`` 按 rank／
二筛分取前段；扫描 conflict_pairs——任一侧进 Top-7、对侧在候选但
不在 Top-7 ⇒ **追加**对侧（保位；不占前 7 名额，可 8／9…）。
追加后仍整盒通读（focus 渲染本就整名单呈现，零「后段轻扫」）。

边界（工单钉死）：
- 只改 ``kg_focus_segment_ids``（分析师可见焦点面）；盒 rank_order、
  tree17_cite、dens 公式、pack kwargs、续盒核心一概不动；
- 禁止改 dens 公式目标；禁止灌 pack 系数；禁止动 MULTI_BOX 默认；
- 不碰 tree17_accept／引用打回环（C-139 会话 2 并行线）；
- 金标不读本模块任何输入；accounting 只记 id／计数（``k_top``／
  ``reserve_added``／``final_n``＋回放面），零案名、零系数键
  （整体过 ``audit_forbidden_keys``）。

候选池＝测试树二筛显式序（``kg_test_tree.rerank_order``，C-140 起随
``ensure_test_tree_submit`` 落账；序尾补盒内缺员，与二筛
``build_conflict_pairs`` 同一补法）。候选池缺席＝回退 rank_order
（Top-7 退化为整盒＋保位，旧形状不改坏）。

旗：settings ``submit_top7`` 优先；env ``VERITAS_SUBMIT_TOP7`` 默认开；
显式 0/false/off/no ＝关回旧可变 k（焦点面与改前逐字相同、
accounting 无 ``submit_top7`` 键）。
"""

from __future__ import annotations

import os
from typing import Any

_ENV = "VERITAS_SUBMIT_TOP7"
TOP_K = 7


def submit_top7_enabled(settings: Any | None = None) -> bool:
    """默认开。settings 优先；env 显式关＝回退旧可变 k。"""
    if settings is not None and hasattr(settings, "submit_top7"):
        return bool(getattr(settings, "submit_top7"))
    v = (os.environ.get(_ENV) or "").strip().lower()
    if v in ("0", "false", "off", "no"):
        return False
    return True


def _clean_ids(raw: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in raw or []:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _pair_rows(conflict_pairs: Any) -> list[tuple[str, str]]:
    """conflict_pairs（dict 洗净面或 list）→ (support_id, oppose_id) 行。"""
    if isinstance(conflict_pairs, dict):
        raw = conflict_pairs.get("conflicts") or []
    elif isinstance(conflict_pairs, list):
        raw = conflict_pairs
    else:
        raw = []
    rows: list[tuple[str, str]] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        s = str(p.get("support_id") or "").strip()
        o = str(p.get("oppose_id") or "").strip()
        if s and o and s != o:
            rows.append((s, o))
    return rows


def build_top7_face(
    candidates: list[str],
    conflict_pairs: Any,
    *,
    top_k: int = TOP_K,
) -> dict[str, Any] | None:
    """硬 Top-7＋成对保位（纯函数；零金标、零案名、零系数）。

    候选空 → None（零行为）。回放面逐位给：top_ids／reserve_ids／
    final_ids／cut_ids／pair_replay（每组成对行记两侧是否入 Top-7 与
    追加了谁）。
    """
    cand = _clean_ids(candidates)
    if not cand:
        return None
    k_top = min(max(1, int(top_k)), len(cand))
    top = cand[:k_top]
    face_set = set(top)
    reserve_ids: list[str] = []
    pair_replay: list[dict[str, Any]] = []
    for s_id, o_id in _pair_rows(conflict_pairs):
        s_top = s_id in face_set
        o_top = o_id in face_set
        added: str | None = None
        if s_top and not o_top and o_id in set(cand):
            added = o_id
        elif o_top and not s_top and s_id in set(cand):
            added = s_id
        if added and added not in face_set:
            face_set.add(added)
            reserve_ids.append(added)
        pair_replay.append({
            "support_id": s_id, "oppose_id": o_id,
            "support_in_top": s_top, "oppose_in_top": o_top,
            "reserve_added": added,
        })
    final = top + list(reserve_ids)
    cut = [c for c in cand if c not in face_set]
    return {
        "enabled": True,
        "top_k": int(top_k),
        "k_top": k_top,
        "reserve_added": len(reserve_ids),
        "final_n": len(final),
        "candidates_n": len(cand),
        "top_ids": top,
        "reserve_ids": reserve_ids,
        "final_ids": final,
        "cut_ids": cut,
        "pair_rows": pair_replay,
        "n_pair_rows": len(pair_replay),
        "n_pair_reserve": sum(
            1 for r in pair_replay if r["reserve_added"]),
    }


def apply_submit_top7(
    dossier: Any,
    *,
    enabled: bool | None = None,
) -> dict[str, Any] | None:
    """旗开且有交卷面时重写焦点面并落账；否则零行为（None）。

    只写三处：``kg_focus_segment_ids``／``kg_pack_hints.focus_segment_ids``
    （两处同步）＋新披露键 ``submit_top7``。盒／tree17／dens／pack
    kwargs 不动。未 apply 交卷面（``kg_submit_active`` 缺）→ None。
    """
    if enabled is None:
        enabled = submit_top7_enabled()
    if not enabled:
        return None
    acc = getattr(dossier, "accounting", None) or {}
    if not acc.get("kg_submit_active"):
        return None
    ttree = acc.get("kg_test_tree") or {}
    rerank = ttree.get("rerank_order") if isinstance(ttree, dict) else None
    source = "rerank_order"
    cand = _clean_ids(rerank)
    if not cand:
        surf = acc.get("kg_submit") or {}
        cand = _clean_ids(surf.get("rank_order"))
        source = "rank_order_fallback"
    if not cand:
        return None
    pairs = acc.get("kg_conflict_pairs")
    face = build_top7_face(cand, pairs)
    if not face:
        return None
    face["candidates_source"] = source
    acc["kg_focus_segment_ids"] = list(face["final_ids"])
    hints = acc.get("kg_pack_hints")
    if isinstance(hints, dict) and "focus_segment_ids" in hints:
        hints["focus_segment_ids"] = list(face["final_ids"])
    acc["submit_top7"] = face
    from app.core.kg_submit_surface import audit_forbidden_keys

    leaks = audit_forbidden_keys(face)
    if leaks:
        raise ValueError(f"submit_top7 accounting leaked: {leaks}")
    return face
