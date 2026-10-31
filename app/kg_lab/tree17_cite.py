"""R28 树17 引用规则试点（L3）：盒交给分析师后的细读／采信层。

与树13～16「进盒／密度」分开记分。本模块只读盒序＋问句锚点＋段文，
不改盒、不读金标 id、无案名硬编码。

规则草案（可测、可审计）：
1. 冲突成对必读：support／oppose（option_a／option_b）禁止只引一边
2. 可核验优先：时间／数额／主体通报 > 综述评论
3. rank 带宽：默认前 k 细读（close_read）
4. 输出标签：采信／存疑／对立
"""

from __future__ import annotations

import re
from typing import Any

from app.kg_lab.intent_routes import (
    anchor_hits,
    is_claim_conflict_route,
    route_option_anchors,
)

# 标签枚举（对外稳定）
LABEL_ACCEPT = "采信"
LABEL_SUSPECT = "存疑"
LABEL_OPPOSE = "对立"

DEFAULT_CLOSE_K = 4  # 细读带宽默认；盒短于此时取全盒

# 可核验线索（通用，非案名）
_TIME_CUES = re.compile(
    r"(?:"
    r"\d{4}年\d{1,2}月\d{1,2}日"
    r"|\d{4}年\d{1,2}月"
    r"|\d{1,2}月\d{1,2}日"
    r"|\d{1,2}时\d{1,2}分"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r")"
)
_AMOUNT_CUES = re.compile(
    r"(?:"
    r"\d+(?:\.\d+)?\s*(?:万|亿)?(?:元|人|名|例|次|米|公里|%)"
    r"|\d{3,}"
    r")"
)
_BULLETIN_CUES = (
    "发言人", "新闻发布会", "发布会", "声明", "例行记者会", "通报",
    "秘书长", "外交部", "官方", "确认", "宣布",
)
_COMMENT_CUES = (
    "专家认为", "有分析", "评论称", "网友", "业内人士", "综合认为",
    "据悉或", "或将", "可能意味着", "值得注意",
)


def verifiability_score(text: str) -> dict[str, Any]:
    """段级可核验分（0～1）＋分项；综述评论降权。"""
    body = text or ""
    time_n = len(_TIME_CUES.findall(body))
    amount_n = len(_AMOUNT_CUES.findall(body[:400]))
    bulletin_n = sum(1 for c in _BULLETIN_CUES if c in body[:220])
    comment_n = sum(1 for c in _COMMENT_CUES if c in body[:220])
    raw = (
        0.28 * min(time_n, 2)
        + 0.22 * min(amount_n, 3)
        + 0.30 * min(bulletin_n, 3)
        - 0.18 * min(comment_n, 3)
    )
    score = max(0.0, min(1.0, 0.12 + raw))
    return {
        "score": round(score, 4),
        "time_n": time_n,
        "amount_n": amount_n,
        "bulletin_n": bulletin_n,
        "comment_n": comment_n,
    }


def _side_of(
    pid: str,
    *,
    metas: dict[str, dict[str, Any]],
    anchors: dict[str, list[str]] | None,
) -> str:
    text = str((metas.get(pid) or {}).get("text") or "")
    hits = anchor_hits(text, anchors)
    return str(hits.get("side") or "") or "none"


def _label_for(
    side: str,
    *,
    conflict: bool,
    ver: float,
    in_close: bool,
) -> str:
    """采信／存疑／对立标签（不读金标）。

    - 冲突题：option_a → 采信候选；option_b → 对立（须成对细读）；both → 存疑
    - 非冲突／无侧：可核验高且进细读 → 采信；否则存疑
    """
    if not in_close:
        return LABEL_SUSPECT
    if conflict:
        if side == "option_a":
            return LABEL_ACCEPT if ver >= 0.35 else LABEL_SUSPECT
        if side == "option_b":
            return LABEL_OPPOSE
        if side == "both":
            return LABEL_SUSPECT
        return LABEL_ACCEPT if ver >= 0.45 else LABEL_SUSPECT
    if side in {"option_a", "option_b"}:
        return LABEL_ACCEPT if ver >= 0.35 else LABEL_SUSPECT
    return LABEL_ACCEPT if ver >= 0.50 else LABEL_SUSPECT


def plan_close_read(
    box: list[str],
    *,
    metas: dict[str, dict[str, Any]],
    question: str,
    anchors: dict[str, list[str]] | None = None,
    close_k: int = DEFAULT_CLOSE_K,
) -> dict[str, Any]:
    """对盒内段做树17引用计划：细读带宽＋标签＋冲突成对检查。

    不改 box 顺序；只产出分析师前的引用指令面。
    """
    box = [str(p) for p in (box or []) if p]
    anchors = anchors or route_option_anchors(question or "")
    conflict = is_claim_conflict_route(anchors)
    k = max(1, min(int(close_k), len(box))) if box else 0

    # 按可核验分在盒内重排「细读候选」，但最终 close_read 仍须覆盖冲突两侧
    scored: list[tuple[float, int, str, dict[str, Any], str]] = []
    for i, pid in enumerate(box):
        text = str((metas.get(pid) or {}).get("text") or "")
        ver = verifiability_score(text)
        side = _side_of(pid, metas=metas, anchors=anchors)
        # 盒序靠前轻抬（rank 带宽）：名次分 + 可核验
        rank_b = max(0.0, (len(box) - i) / max(len(box), 1)) * 0.25
        priority = float(ver["score"]) + rank_b
        scored.append((priority, i, pid, ver, side))
    scored.sort(key=lambda t: (-t[0], t[1]))

    close: list[str] = []
    close_set: set[str] = set()

    def _add(pid: str) -> None:
        if pid not in close_set and pid in box:
            close.append(pid)
            close_set.add(pid)

    # 1) 冲突成对：两侧各至少 1 条进细读（若盒内有该侧）
    sides_in_box = {
        "option_a": [p for p in box if _side_of(p, metas=metas, anchors=anchors) == "option_a"],
        "option_b": [p for p in box if _side_of(p, metas=metas, anchors=anchors) == "option_b"],
        "both": [p for p in box if _side_of(p, metas=metas, anchors=anchors) == "both"],
    }
    pair_required = bool(
        conflict and sides_in_box["option_a"] and sides_in_box["option_b"]
    )
    if pair_required:
        # 各侧取可核验最高者
        for side_key in ("option_a", "option_b"):
            cands = [
                (verifiability_score(str((metas.get(p) or {}).get("text") or ""))["score"],
                 box.index(p), p)
                for p in sides_in_box[side_key]
            ]
            cands.sort(key=lambda t: (-t[0], t[1]))
            if cands:
                _add(cands[0][2])

    # 2) 可核验优先填满带宽
    for _pri, _i, pid, _ver, _side in scored:
        if len(close) >= k:
            break
        _add(pid)

    # 若成对必需但带宽不够，强制扩到至少覆盖两侧（披露超带宽）
    bandwidth_expanded = False
    if pair_required:
        for side_key in ("option_a", "option_b"):
            if not any(
                _side_of(p, metas=metas, anchors=anchors) == side_key for p in close
            ):
                cands = sides_in_box[side_key]
                if cands:
                    _add(cands[0])
                    bandwidth_expanded = True

    items: list[dict[str, Any]] = []
    for rank, pid in enumerate(box, 1):
        text = str((metas.get(pid) or {}).get("text") or "")
        ver = verifiability_score(text)
        side = _side_of(pid, metas=metas, anchors=anchors)
        in_close = pid in close_set
        label = _label_for(side, conflict=conflict, ver=float(ver["score"]), in_close=in_close)
        items.append({
            "para_id": pid,
            "box_rank": rank,
            "side": side,
            "in_close_read": in_close,
            "label": label,
            "verifiability": ver,
            "stance": (
                "support" if side == "option_a"
                else ("oppose" if side == "option_b"
                      else ("both" if side == "both" else "neutral"))
            ),
        })

    close_sides = {
        _side_of(p, metas=metas, anchors=anchors) for p in close
    }
    both_sides_cited = (not pair_required) or (
        "option_a" in close_sides and "option_b" in close_sides
    )
    # 违规：冲突盒内有两侧，但细读只覆盖一侧
    pair_violation = pair_required and not both_sides_cited

    label_counts = {
        LABEL_ACCEPT: 0,
        LABEL_SUSPECT: 0,
        LABEL_OPPOSE: 0,
    }
    for it in items:
        if it["in_close_read"]:
            label_counts[it["label"]] = label_counts.get(it["label"], 0) + 1

    return {
        "question": question,
        "conflict_route": conflict,
        "pair_required": pair_required,
        "pair_violation": pair_violation,
        "both_sides_cited": both_sides_cited,
        "close_k_requested": int(close_k),
        "close_k_effective": len(close),
        "bandwidth_expanded": bandwidth_expanded,
        "box": box,
        "close_read": close,
        "items": items,
        "label_counts_close": label_counts,
        "sides_in_box": {k: len(v) for k, v in sides_in_box.items()},
        "anchors": {
            "side_a": list(anchors.get("side_a") or [])[:8],
            "side_b": list(anchors.get("side_b") or [])[:8],
            "soft": list(anchors.get("soft") or [])[:8],
        },
    }


def measure_l3_against_refs(
    plan: dict[str, Any],
    *,
    gold_ids: set[str] | list[str] | None = None,
    support_ids: set[str] | list[str] | None = None,
) -> dict[str, Any]:
    """L3 读数：引用覆盖／冲突两侧／与金标·支撑表对照。

    对照只作披露，不回写规则、不改盒。
    """
    box = list(plan.get("box") or [])
    close = list(plan.get("close_read") or [])
    gold = set(gold_ids or [])
    support = set(support_ids or [])
    refs = gold | support

    def _hits(ids: list[str], pool: set[str]) -> dict[str, Any]:
        hit = [p for p in ids if p in pool]
        return {
            "hits": len(hit),
            "total_in_scope": len([p for p in pool if p in (set(box) | set(ids))]),
            "hit_ids": hit,
            "pool_size": len(pool),
            "coverage_of_box": round(len(hit) / len(ids), 4) if ids else 0.0,
            "recall_of_pool_in_box": round(
                len([p for p in pool if p in set(ids)]) / len(pool), 4,
            ) if pool else None,
        }

    gold_in_box = [g for g in gold if g in set(box)]
    gold_in_close = [g for g in gold if g in set(close)]
    support_in_box = [s for s in support if s in set(box)]
    support_in_close = [s for s in support if s in set(close)]

    return {
        "box_size": len(box),
        "close_size": len(close),
        "close_coverage_of_box": round(len(close) / len(box), 4) if box else 0.0,
        "both_sides_cited": bool(plan.get("both_sides_cited")),
        "pair_required": bool(plan.get("pair_required")),
        "pair_violation": bool(plan.get("pair_violation")),
        "label_counts_close": dict(plan.get("label_counts_close") or {}),
        "gold": {
            "in_box": len(gold_in_box),
            "in_close": len(gold_in_close),
            "gold_total": len(gold),
            "box_ids": gold_in_box,
            "close_ids": gold_in_close,
            "close_recall": round(len(gold_in_close) / len(gold), 4) if gold else None,
        },
        "support": {
            "in_box": len(support_in_box),
            "in_close": len(support_in_close),
            "support_total": len(support),
            "box_ids": support_in_box,
            "close_ids": support_in_close,
            "close_recall": (
                round(len(support_in_close) / len(support), 4) if support else None
            ),
        },
        "ref_union_close_recall": (
            round(len([p for p in refs if p in set(close)]) / len(refs), 4)
            if refs else None
        ),
        # 辅助：盒内金标有多少进了细读
        "gold_in_box_to_close": (
            round(len(gold_in_close) / len(gold_in_box), 4) if gold_in_box else None
        ),
    }


def apply_tree17_cite(
    box: list[str],
    *,
    metas: dict[str, dict[str, Any]],
    question: str,
    anchors: dict[str, list[str]] | None = None,
    close_k: int = DEFAULT_CLOSE_K,
    gold_ids: set[str] | list[str] | None = None,
    support_ids: set[str] | list[str] | None = None,
) -> dict[str, Any]:
    """一站式：引用计划 + L3 对照读数。"""
    plan = plan_close_read(
        box, metas=metas, question=question, anchors=anchors, close_k=close_k,
    )
    l3 = measure_l3_against_refs(plan, gold_ids=gold_ids, support_ids=support_ids)
    return {"plan": plan, "l3": l3}
