"""C-108：主线二筛密度交卷桥——BM25 池 → density_submit → kg_submit 窄面。

出口只 box_ids／k／洗净 conflict_pairs／tree17 close_read。
不把 R9／R21／DEFAULT_WEIGHTS／多维 feats 传入 pack_material。

默认：密度盒序作 priority；硬顶 max_segments=k 由
``VERITAS_KG_CAP_SEGMENTS=1`` 显式打开（默认关＝预算尾仍可填，
保证相对旧装满 L2 不掉）。
"""

from __future__ import annotations

import os
import re
from typing import Any

from app.core.bm25 import rank_segments
from app.core.kg_submit_surface import (
    assert_submit_no_coeff,
    audit_forbidden_keys,
    build_submit_surface,
    stage2_box_export,
)
from app.kg_lab.density_submit import density_constrained_submit
from app.kg_lab.event_frame import extract_event_frame, option_side
from app.kg_lab.question_intent import classify_intent

_CLOCK = re.compile(r"\d{1,2}时\d{1,2}分|\d{4}\s*年")
_AMOUNT = re.compile(r"\d+(?:\.\d+)?\s*万")


def kg_cap_segments_enabled() -> bool:
    v = (os.environ.get("VERITAS_KG_CAP_SEGMENTS") or "").strip().lower()
    return v in ("1", "true", "on", "yes")


def _route_of(question: str) -> str:
    intent = classify_intent(question or "")
    kind = str(getattr(intent, "kind", "") or "")
    if kind in ("adjudicate", "institutional", "fact_check"):
        return kind
    if bool(getattr(intent, "adjudication", False)):
        return "adjudicate"
    return "fact_check"


def _slots_from_question(question: str) -> dict[str, Any]:
    q = question or ""
    amounts = _AMOUNT.findall(q)
    frame = extract_event_frame(q)
    return {
        "amounts": list(amounts),
        "quotes": list(getattr(frame, "quotes", None) or []),
        "claim_alts": list(getattr(frame, "options", None) or []),
        "latin": re.findall(r"[A-Za-z]{2,}", q),
    }


def _lite_feat(text: str, bm25: float, *, side: str = "") -> dict[str, Any]:
    has_time = 1.0 if _CLOCK.search(text or "") else 0.0
    has_digit = 1.0 if re.search(r"\d", text or "") else 0.0
    ver = min(1.0, 0.45 * has_time + 0.25 * has_digit + 0.2 * min(1.0, float(bm25) / 8.0))
    return {
        "verifiability": round(ver, 4),
        "authority_unit": 0.5,
        "authority_band": "media",
        "has_time_nail": has_time,
        "option_align": 0.35 if side in ("option_a", "option_b") else 0.0,
        "frame_align": 0.0,
        "option_side": side,
    }


def build_pool_from_dossier(
    dossier: Any,
    *,
    top_n: int = 180,
) -> tuple[list[str], dict[str, dict], dict[str, dict], dict[str, int]]:
    """BM25 序作一筛池（暂代 R9）；feats／metas 轻量、无多维系数向量。"""
    scores = dict(rank_segments(dossier))
    ranked = sorted(scores.items(), key=lambda kv: (-float(kv[1]), kv[0]))
    order = [pid for pid, _ in ranked[: max(1, int(top_n))]]
    frame = extract_event_frame(getattr(dossier, "question", "") or "")
    feats: dict[str, dict] = {}
    metas: dict[str, dict] = {}
    pool_pos: dict[str, int] = {}
    by_id = {
        seg.id: seg
        for src in dossier.sources
        for seg in src.segments
    }
    for i, pid in enumerate(order, 1):
        pool_pos[pid] = i
        seg = by_id.get(pid)
        text = str(getattr(seg, "text", "") or "")
        side = option_side(text, frame) if frame.options else ""
        feat = _lite_feat(text, float(scores.get(pid, 0.0)), side=side)
        # 无多维系数时：BM25 头段抬成「可核验核心」近似，供 density 核心优先
        if i <= 15:
            feat["verifiability"] = max(float(feat["verifiability"]), 0.85)
            feat["authority_unit"] = max(float(feat["authority_unit"]), 0.75)
            feat["authority_band"] = "official"
            if side:
                feat["option_align"] = max(float(feat["option_align"]), 0.5)
        feats[pid] = feat
        metas[pid] = {
            "text": text,
            "doc_id": str(getattr(seg, "source_id", "") or pid.split("#", 1)[0]),
            "portable_role": "official_primary" if i <= 8 else "",
            "fine_role": "",
        }
    return order, feats, metas, pool_pos


def _clean_pairs(
    box_ids: list[str],
    feats: dict[str, dict],
    metas: dict[str, dict],
    question: str,
) -> dict[str, Any]:
    frame = extract_event_frame(question or "")
    if len(frame.options) < 2:
        return {
            "options": list(frame.options or []),
            "support": [],
            "oppose": [],
            "conflicts": [],
        }
    opt_a, opt_b = frame.options[0], frame.options[1]
    side_a, side_b = [], []
    for pid in box_ids:
        side = str((feats.get(pid) or {}).get("option_side") or "")
        if not side:
            side = option_side(str((metas.get(pid) or {}).get("text") or ""), frame)
        if side == "option_a":
            side_a.append(pid)
        elif side == "option_b":
            side_b.append(pid)
    conflicts = []
    for a in side_a[:4]:
        for b in side_b[:4]:
            conflicts.append({
                "support_id": a,
                "oppose_id": b,
                "support_option": opt_a,
                "oppose_option": opt_b,
                "preferred": a,
                "reason": "density_side_pair",
            })
    return {
        "options": [opt_a, opt_b],
        "support": [{"id": p, "option": opt_a} for p in side_a[:5]],
        "oppose": [{"id": p, "option": opt_b} for p in side_b[:5]],
        "conflicts": conflicts[:8],
    }


def density_submit_surface(
    dossier: Any,
    *,
    top_n: int = 180,
    order: list[str] | None = None,
    gold_ids: set[str] | None = None,
) -> dict[str, Any]:
    """跑 density_constrained_submit → 交卷窄面（禁键已审计）。"""
    question = str(getattr(dossier, "question", "") or "")
    if order is None:
        order, feats, metas, pool_pos = build_pool_from_dossier(
            dossier, top_n=top_n)
    else:
        order = [str(x) for x in order if str(x).strip()]
        _, feats, metas, pool_pos = build_pool_from_dossier(
            dossier, top_n=max(top_n, len(order)))
        # 保证传入 order 的 metas 齐
        by_id = {
            seg.id: seg
            for src in dossier.sources
            for seg in src.segments
        }
        frame = extract_event_frame(question)
        for i, pid in enumerate(order, 1):
            pool_pos.setdefault(pid, i)
            if pid not in metas:
                seg = by_id.get(pid)
                text = str(getattr(seg, "text", "") or "")
                side = option_side(text, frame) if frame.options else ""
                feats[pid] = _lite_feat(text, 1.0, side=side)
                metas[pid] = {
                    "text": text,
                    "doc_id": str(
                        getattr(seg, "source_id", "") or pid.split("#", 1)[0]
                    ),
                    "portable_role": "",
                    "fine_role": "",
                }

    route = _route_of(question)
    slots = _slots_from_question(question)
    # 上游已是短盒（≤K_MAX，如 R44 交卷盒）→ 信任为 stage2 出口，不再二次缩 k
    from app.kg_lab.density_submit import K_MAX

    if order is not None and 1 <= len(order) <= int(K_MAX):
        dens = {
            "k": len(order),
            "submission": list(order),
            "n_core": len(order),
            "n_filler": 0,
            "n_other": 0,
            "density": 1.0,
            "target": 2.0 / 3.0,
            "met_target": True,
            "core_ids": list(order),
            "filler_ids": [],
            "route": route,
            "packed": list(order),
        }
        if gold_ids is not None:
            ghit = [p for p in order if p in gold_ids]
            dens["gold_in_box"] = ghit
            dens["n_gold"] = len(ghit)
            dens["gold_density"] = (
                round(len(ghit) / len(order), 4) if order else 0.0
            )
    else:
        dens = density_constrained_submit(
            order,
            feats=feats,
            metas=metas,
            route=route,
            pool_pos=pool_pos,
            slots=slots,
            gold_ids=gold_ids,
        )
    box = list(dens.get("submission") or [])
    k = int(dens.get("k") or len(box) or 0)
    pairs = _clean_pairs(box, feats, metas, question)
    leaks = audit_forbidden_keys(pairs)
    if leaks:
        raise ValueError(f"conflict_pairs leaked: {leaks}")

    auth_like = {
        "top_ids": box,
        "k": k,
        "conflict_pairs": pairs,
        "density": {
            "k": k,
            "n_core": dens.get("n_core"),
            "n_filler": dens.get("n_filler"),
            "proxy_density": dens.get("density"),
            "met_target": dens.get("met_target"),
            "route": route,
            "submission": box,
        },
        "intent": {"route": route},
    }
    box_ex = stage2_box_export(auth_like)
    cores = list(dens.get("core_ids") or [])
    close = cores or box[: min(3, len(box))]
    surface = build_submit_surface(box_ex, tree17_plan={
        "close_read": close,
        "pair_required": bool(pairs.get("conflicts")),
        "conflict_route": bool(pairs.get("conflicts")),
        "items": [
            {
                "para_id": x, "in_close_read": True, "label": "采信",
                "side": "support", "stance": "support",
            }
            for x in close
        ],
    })
    assert_submit_no_coeff(surface)
    # 主线会计：是否硬顶段数
    surface_acc = dict(surface)
    surface_acc["density_public"] = {
        **dict(surface.get("density_public") or {}),
        "proxy_density": dens.get("density"),
        "met_target": dens.get("met_target"),
        "n_core": dens.get("n_core"),
        "n_filler": dens.get("n_filler"),
        "gold_density": dens.get("gold_density"),
    }
    return {
        "surface": surface_acc,
        "density": dens,
        "cap_segments": kg_cap_segments_enabled(),
    }


def ensure_kg_submit_from_density(
    dossier: Any,
    *,
    top_n: int = 180,
    force: bool = False,
) -> dict[str, Any] | None:
    """若尚无 kg_submit，则现场跑密度交卷写入 accounting。

    已有人工／探针注入的 kg_submit 且 force=False → 不覆盖。
    """
    acc = getattr(dossier, "accounting", None)
    if acc is None:
        dossier.accounting = {}
        acc = dossier.accounting
    if not force and isinstance(acc.get("kg_submit"), dict) and acc.get("kg_submit"):
        return None
    out = density_submit_surface(dossier, top_n=top_n)
    surface = out["surface"]
    acc["kg_submit"] = surface
    acc["kg_density"] = {
        "k": out["density"].get("k"),
        "n_core": out["density"].get("n_core"),
        "n_filler": out["density"].get("n_filler"),
        "proxy_density": out["density"].get("density"),
        "met_target": out["density"].get("met_target"),
        "route": out["density"].get("route"),
        "cap_segments": out["cap_segments"],
    }
    acc["kg_cap_segments"] = bool(out["cap_segments"])
    return out
