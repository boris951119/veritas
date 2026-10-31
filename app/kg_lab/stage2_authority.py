"""R20：二筛权威重排——交卷保 R19/inbox 骨干，权威只裁决对立冲突并轻量注入池内段。

硬约束：
- 不做「更像问句」第二层（无问句 BM25／向量相似重排）
- 高相似对立口径：权威／可核验优先（成对暴露）
- 交卷 schema 含 conflict_pairs（support vs oppose）
- 一筛 pool_ranked 能力保留；不写案情专名死锁
"""

from __future__ import annotations

from typing import Any

from app.kg_lab.event_frame import EventFrame, extract_event_frame, option_side
from app.kg_lab.inbox_rerank import inbox_rerank
from app.kg_lab.portable_tags import portable_features
from app.kg_lab.question_intent import classify_intent

DEFAULT_WEIGHTS: dict[str, float] = {
    "authority": 0.40,
    "verifiability": 0.30,
    "option_align": 0.20,
    "time_nail": 0.12,
    "publish_recency": 0.12,
    "title_option": 0.10,
    "primary_role": 0.20,
}

_PRIMARY_ROLES = frozenset({
    "official_primary", "party_primary", "institution_def", "official_reprint",
})


def _auth_tuple(feat: dict[str, Any], meta: dict[str, Any]) -> tuple:
    role = str(meta.get("fine_role") or "")
    auth = float(feat.get("authority_unit") or 0.0)
    ver = float(feat.get("verifiability") or 0.0)
    rec = float(feat.get("publish_recency") or 0.0)
    time_n = float(feat.get("has_time_nail") or 0.0)
    primary = 0 if role in _PRIMARY_ROLES else 1
    return (-auth, -ver, -rec, -time_n, primary)


def portable_authority_unit(
    feat: dict[str, Any],
    meta: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> float:
    """纯权威／可核验分（无 stage1／无问句相似）。"""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    role = str(meta.get("fine_role") or "")
    primary = 1.0 if role in _PRIMARY_ROLES else 0.0
    return (
        w["authority"] * float(feat.get("authority_unit") or 0.0)
        + w["verifiability"] * float(feat.get("verifiability") or 0.0)
        + w["option_align"] * float(feat.get("option_align") or feat.get("frame_align") or 0.0)
        + w["time_nail"] * float(feat.get("has_time_nail") or 0.0)
        + w["publish_recency"] * float(feat.get("publish_recency") or 0.0)
        + w["title_option"] * float(feat.get("title_option_hit") or 0.0)
        + w["primary_role"] * primary
    )


def ensure_portable_on_ids(
    ids: list[str],
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    url_of: dict[str, str],
    question: str,
    frame: EventFrame,
    publish_of: dict[str, str] | None = None,
) -> None:
    publish_of = publish_of or {}
    for pid in ids:
        meta = metas.get(pid) or {}
        feat = feats.setdefault(pid, {})
        if "verifiability" in feat and "option_align" in feat and "authority_unit" in feat:
            # 仍刷新 option_side（近义规则可能已改）
            if "option_side" in feat and feat.get("option_side") not in {"", None}:
                continue
        pub = publish_of.get(str(meta.get("doc_id") or ""), "") or str(meta.get("publish_time") or "")
        tags = portable_features(
            question=question,
            title=str(meta.get("title") or ""),
            text=str(meta.get("text") or ""),
            fine_role=str(meta.get("fine_role") or ""),
            url=url_of.get(str(meta.get("doc_id") or ""), ""),
            frame=frame,
            publish_time=pub,
        )
        for k in (
            "frame_align", "option_align", "authority_unit", "has_time_nail",
            "scope_hit", "publish_recency", "title_option_hit", "verifiability",
        ):
            feat[k] = float(tags[k])
        feat["has_amount_nail"] = float(tags["has_amount"])
        feat["authority_band"] = tags["authority_band"]  # type: ignore[assignment]
        feat["option_side"] = tags["option_side"]  # type: ignore[assignment]
        feat["applicability"] = tags["applicability"]  # type: ignore[assignment]
        feat["publish_time"] = tags["publish_time"]  # type: ignore[assignment]


def merge_candidate_box(
    stage1_ranked: list[tuple[str, float]],
    pool_ranked: list[tuple[str, float]],
    *,
    pool: int = 20,
) -> list[str]:
    s1 = [pid for pid, sc in stage1_ranked[:pool] if float(sc) > 0]
    pr = [pid for pid, sc in pool_ranked[:pool] if float(sc) > 0]
    seen = set(s1)
    out = list(s1)
    for pid in pr:
        if pid not in seen:
            out.append(pid)
            seen.add(pid)
    return out


def build_conflict_pairs(
    ids: list[str],
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    frame: EventFrame,
    *,
    top_n: int = 12,
) -> dict[str, Any]:
    if len(frame.options) < 2:
        return {
            "options": list(frame.options),
            "support": [],
            "oppose": [],
            "conflicts": [],
            "by_side": {},
        }
    opt_a, opt_b = frame.options[0], frame.options[1]
    side_a: list[str] = []
    side_b: list[str] = []
    both: list[str] = []
    for pid in ids:
        feat = feats.get(pid) or {}
        side = str(feat.get("option_side") or "")
        if not side:
            side = option_side(str((metas.get(pid) or {}).get("text") or ""), frame)
            feat["option_side"] = side  # type: ignore[assignment]
        if side == "option_a":
            side_a.append(pid)
        elif side == "option_b":
            side_b.append(pid)
        elif side == "both":
            both.append(pid)

    def _sort_auth(pids: list[str]) -> list[str]:
        return sorted(pids, key=lambda p: _auth_tuple(feats.get(p) or {}, metas.get(p) or {}))

    side_a = _sort_auth(side_a)[:top_n]
    side_b = _sort_auth(side_b)[:top_n]
    conflicts = []
    for a in side_a[:4]:
        for b in side_b[:4]:
            prefer_a = _auth_tuple(feats.get(a) or {}, metas.get(a) or {}) <= _auth_tuple(
                feats.get(b) or {}, metas.get(b) or {}
            )
            conflicts.append({
                "support_id": a,
                "oppose_id": b,
                "support_option": opt_a,
                "oppose_option": opt_b,
                "support_authority": float((feats.get(a) or {}).get("authority_unit") or 0),
                "oppose_authority": float((feats.get(b) or {}).get("authority_unit") or 0),
                "preferred": a if prefer_a else b,
                "reason": "authority_over_similarity",
            })
    return {
        "options": [opt_a, opt_b],
        "support": [{"id": p, "option": opt_a} for p in side_a[:5]],
        "oppose": [{"id": p, "option": opt_b} for p in side_b[:5]],
        "both": both[:5],
        "conflicts": conflicts[:8],
        "by_side": {"option_a": side_a, "option_b": side_b},
    }


def _apply_authority_among_conflicts(
    order: list[str],
    pairs: dict[str, Any],
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    *,
    k: int,
    protect_head: int = 4,
) -> list[str]:
    """若 top-k 内同时出现对立两侧，把更权威的一侧前移（不靠问句相似）。

    前 protect_head 名骨干不因交换被挤出保护位。
    """
    if not pairs.get("conflicts"):
        return order
    out = list(order)
    top = set(out[:k])
    for c in pairs["conflicts"]:
        a, b = c["support_id"], c["oppose_id"]
        if a not in top or b not in top:
            continue
        prefer = c["preferred"]
        other = b if prefer == a else a
        ia, ib = out.index(prefer), out.index(other)
        if ia > ib:
            # 若 other 在保护头、prefer 在头外：只把 prefer 插到保护头之后，不挤出头
            if ib < protect_head <= ia:
                out.pop(ia)
                out.insert(protect_head, prefer)
            else:
                out[ia], out[ib] = out[ib], out[ia]
    return out


def _inject_pool_authority(
    order: list[str],
    pool_ranked: list[tuple[str, float]],
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    *,
    pool: int,
    k: int,
    max_inject: int = 3,
    head_keep: int = 4,
) -> list[str]:
    """仅用池内独有高权威段替换 Top-k 尾部更弱者；前 head_keep 不动。"""
    if k <= head_keep:
        return order
    # 只相对 Top-k 判「未进交卷」——池内金标常在骨干长尾，仍应可注入
    present = set(order[:k])
    pool_only = [
        pid for pid, sc in pool_ranked[:pool]
        if float(sc) > 0 and pid not in present
    ]
    if not pool_only:
        return order

    def _ok(pid: str) -> bool:
        feat = feats.get(pid) or {}
        return (
            float(feat.get("authority_unit") or 0) >= 0.40
            or float(feat.get("verifiability") or 0) >= 0.25
            or float(feat.get("option_align") or feat.get("frame_align") or 0) >= 0.35
            or float(feat.get("has_time_nail") or 0) >= 1.0
            or str(feat.get("option_side") or "") in {"option_a", "option_b"}
        )

    def _promote_score(pid: str) -> float:
        feat = feats.get(pid) or {}
        meta = metas.get(pid) or {}
        # 跨案：可核验＋选项对齐＋时点 比细角色更稳（R18：金标常被标 commentary）
        # R21：portable_role 抬出的可核验转述额外加分，不改一筛 fine_role
        portable = str(meta.get("portable_role") or "")
        return (
            portable_authority_unit(feat, meta)
            + 0.35 * float(feat.get("option_align") or feat.get("frame_align") or 0)
            + 0.25 * float(feat.get("has_time_nail") or 0)
            + 0.30 * float(feat.get("verifiability") or 0)
            + (0.20 if str(feat.get("option_side") or "") in {"option_a", "option_b"} else 0.0)
            + (0.15 if portable == "media_relay" and float(feat.get("verifiability") or 0) >= 0.67 else 0.0)
        )

    inject = sorted(
        [pid for pid in pool_only if _ok(pid)],
        key=lambda p: (-_promote_score(p), p),
    )[:max_inject]
    if not inject:
        return order

    out = list(order)
    # R21：高权威／可核验池内段插到保护头之后（进入 Top-k 前段），
    # 而不是只置换尾部弱段（否则 @7 看不见）。
    insert_at = max(0, int(head_keep))
    for new_pid in inject:
        new_sc = _promote_score(new_pid)
        # 保护头内已有则不动；已在 Top-k 前段也不重复插
        if new_pid in out[: max(insert_at + 3, 7)]:
            continue
        gate = out[insert_at] if insert_at < len(out) else None
        gate_sc = _promote_score(gate) if gate else -1.0
        margin = -0.08 if float((feats.get(new_pid) or {}).get("verifiability") or 0) >= 0.67 else 0.0
        if gate is not None and new_sc <= gate_sc + margin:
            # 仍尝试置换 Top-k 内最弱者
            slots = out[insert_at:k]
            if not slots:
                continue
            victim = min(slots, key=lambda p: (_promote_score(p), p))
            if new_sc <= _promote_score(victim) + margin:
                continue
            if new_pid in out:
                out.remove(new_pid)
            vi = out.index(victim)
            out[vi] = new_pid
            out.append(victim)
            continue
        if new_pid in out:
            out.remove(new_pid)
        out.insert(insert_at, new_pid)
    return out


def authority_rerank(
    stage1_ranked: list[tuple[str, float]],
    pool_ranked: list[tuple[str, float]],
    *,
    texts: dict[str, str],
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    question: str,
    frame: EventFrame | None = None,
    url_of: dict[str, str] | None = None,
    publish_of: dict[str, str] | None = None,
    pool: int = 20,
    k: int = 7,
    weights: dict[str, float] | None = None,
    use_inbox_dedup: bool = True,
    head_keep: int = 7,
    max_inject: int = 3,
) -> dict[str, Any]:
    del weights  # 注入／冲突用 DEFAULT_WEIGHTS；骨干不走加权重排
    frame = frame or extract_event_frame(question)
    intent = classify_intent(question, frame)
    url_of = url_of or {}
    publish_of = publish_of or {}
    box = merge_candidate_box(stage1_ranked, pool_ranked, pool=pool)
    ensure_portable_on_ids(box, feats, metas, url_of, question, frame, publish_of)
    for pid in box:
        texts.setdefault(pid, str((metas.get(pid) or {}).get("text") or ""))
        feat = feats.setdefault(pid, {})
        feat["option_side"] = option_side(  # type: ignore[assignment]
            str((metas.get(pid) or {}).get("text") or ""), frame,
        )

    # —— 骨干：与 R19 相同的 inbox 路径（交卷序），不做问句相似度重打分 ——
    if use_inbox_dedup:
        inbox = inbox_rerank(
            stage1_ranked,
            texts=texts,
            feats=feats,
            metas=metas,
            pool=pool,
            k=max(k, pool),
            question=question,
            refill=True,
        )
        order = [row["id"] for row in inbox["order"]]
        swallowed = list(inbox.get("swallowed") or [])
        near_dup = list(inbox.get("near_dup_dropped") or [])
    else:
        order = [pid for pid, sc in stage1_ranked[:pool] if float(sc) > 0]
        swallowed, near_dup = [], []

    pairs = build_conflict_pairs(
        order + [p for p in box if p not in set(order)], feats, metas, frame,
    )
    # 刘翔回归：head_keep≥7；冒烟可降到 3～4 让池内权威段进 Top-k
    order = _inject_pool_authority(
        order, pool_ranked, feats, metas,
        pool=pool, k=max(k, 7), max_inject=max_inject, head_keep=head_keep,
    )
    pairs = build_conflict_pairs(order[: max(k, 20)] + box, feats, metas, frame)
    # 去重保序
    seen: set[str] = set()
    final: list[str] = []
    for pid in order:
        if pid in seen:
            continue
        seen.add(pid)
        final.append(pid)

    ranked_rows = [
        {
            "id": pid,
            "rank": i,
            "score": round(portable_authority_unit(feats.get(pid) or {}, metas.get(pid) or {}), 6),
            "penalty": 0.0,
            "option_side": str((feats.get(pid) or {}).get("option_side") or ""),
            "authority_band": str((feats.get(pid) or {}).get("authority_band") or ""),
        }
        for i, pid in enumerate(final, 1)
    ]
    s1_pos = {pid: i for i, (pid, _) in enumerate(stage1_ranked, 1)}
    pool_pos = {pid: i for i, (pid, _) in enumerate(pool_ranked, 1)}
    return {
        "pool_ids": box,
        "top_ids": final[:k],
        "submission": [
            {
                "id": row["id"],
                "rank": row["rank"],
                "score": row["score"],
                "option_side": row["option_side"],
                "authority_band": row["authority_band"],
            }
            for row in ranked_rows[:k]
        ],
        "conflict_pairs": pairs,
        "intent": intent.to_dict(),
        "order": ranked_rows,
        "scores": {row["id"]: row["score"] for row in ranked_rows[:k]},
        "swallowed": swallowed,
        "near_dup_dropped": near_dup,
        "pool": len(box),
        "k": k,
        "n_final": min(k, len(final)),
        "n_from_pool_only": sum(
            1 for pid in box
            if pool_pos.get(pid, 10**9) <= pool and s1_pos.get(pid, 10**9) > pool
        ),
        "no_query_likeness": True,
        "backbone": "inbox_stage1",
    }


# 兼容旧测试名
def portable_stage2_score(*, feat, meta, stage1_unit=0.0, weights=None):
    return portable_authority_unit(feat, meta, weights) + 0.01 * float(stage1_unit)
