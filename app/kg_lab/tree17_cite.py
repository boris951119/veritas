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

# 可核验线索（通用，非案名；R41 补英文时点／数额／声明）
_TIME_CUES = re.compile(
    r"(?:"
    r"\d{4}年\d{1,2}月\d{1,2}日"
    r"|\d{4}年\d{1,2}月"
    r"|\d{1,2}月\d{1,2}日"
    r"|\d{1,2}时\d{1,2}分"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s*\d{4}"
    r"|\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?"
    r")"
)
_AMOUNT_CUES = re.compile(
    r"(?:"
    r"\d+(?:\.\d+)?\s*(?:万|亿)?(?:元|人|名|例|次|米|公里|%)"
    r"|\d{3,}"
    r"|(?:killed|killing|deaths?|casualties|on board)\s+\d+"
    r"|\d+\s+(?:people|passengers|killed|dead)"
    r")"
)
_BULLETIN_CUES = (
    "发言人", "新闻发布会", "发布会", "声明", "例行记者会", "通报",
    "秘书长", "外交部", "官方", "确认", "宣布",
    # R41 英文声明／调查声部（可迁移）
    "preliminary report", "said on", "announced", "confirmed",
    "official", "ministry", "AAIB", "according to",
)
_COMMENT_CUES = (
    "专家认为", "有分析", "评论称", "网友", "业内人士", "综合认为",
    "据悉或", "或将", "可能意味着", "值得注意",
    "experts say", "analysts believe", "it is believed",
)


def verifiability_score(text: str) -> dict[str, Any]:
    """段级可核验分（0～1）＋分项；综述评论降权。"""
    body = text or ""
    tl = body.lower()
    time_n = len(_TIME_CUES.findall(body))
    amount_n = len(_AMOUNT_CUES.findall(body[:400]))
    def _cue_hit(c: str) -> bool:
        if c.isascii():
            return c.lower() in tl[:280]
        return c in body[:220]

    bulletin_n = sum(1 for c in _BULLETIN_CUES if _cue_hit(c))
    comment_n = sum(1 for c in _COMMENT_CUES if _cue_hit(c))
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
    align_to_box: bool = False,
) -> dict[str, Any]:
    """对盒内段做树17引用计划：细读带宽＋标签＋冲突成对检查。

    不改 box 顺序；只产出分析师前的引用指令面。
    R30：align_to_box=True 时细读带宽与盒 k 对齐（少而密盒＝整盒可引）。
    """
    box = [str(p) for p in (box or []) if p]
    anchors = anchors or route_option_anchors(question or "")
    conflict = is_claim_conflict_route(anchors)
    req_k = int(close_k) if close_k is not None else DEFAULT_CLOSE_K
    if align_to_box and box:
        k = len(box)
    else:
        k = max(1, min(req_k, len(box))) if box else 0

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

    # R41：细读对外顺序按可核验＋盒序优先（成对成员已在集内；利于「优先引靠前」）
    pri_of = {pid: float(pri) for pri, _i, pid, _ver, _side in scored}
    close.sort(
        key=lambda p: (-pri_of.get(p, 0.0), box.index(p) if p in box else 10**9),
    )

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
        "close_k_requested": req_k,
        "close_k_effective": len(close),
        "align_to_box": bool(align_to_box),
        "bandwidth_expanded": bandwidth_expanded or (
            bool(align_to_box) and len(close) == len(box) and len(box) > 0
        ),
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
    align_to_box: bool = False,
    gold_ids: set[str] | list[str] | None = None,
    support_ids: set[str] | list[str] | None = None,
) -> dict[str, Any]:
    """一站式：引用计划 + L3 对照读数。"""
    plan = plan_close_read(
        box, metas=metas, question=question, anchors=anchors,
        close_k=close_k, align_to_box=align_to_box,
    )
    l3 = measure_l3_against_refs(plan, gold_ids=gold_ids, support_ids=support_ids)
    return {"plan": plan, "l3": l3}


# ---------------------------------------------------------------------------
# R29：注入分析师提示词 + 引用合规率
# ---------------------------------------------------------------------------

ACCOUNTING_KEY = "tree17_cite"


def render_cite_prompt_block(plan: dict[str, Any] | None) -> str:
    """把细读集／成对／标签渲染为分析师可见纪律块。无计划 → 空串。"""
    if not plan:
        return ""
    close = list(plan.get("close_read") or [])
    items = list(plan.get("items") or [])
    by = {str(it.get("para_id")): it for it in items}
    aligned = bool(plan.get("align_to_box")) and len(close) == len(list(plan.get("box") or []))
    lines = [
        "",
        "【树17 引用纪律】（程序从盒内导出；违反则本轮引用不合规）",
        "1. 细读带宽：结论证据的 segment_id【只许】使用下列细读集；不得引用细读集以外的编号；",
        "2. 冲突成对：若标注「成对必读」，support 与 oppose 两侧都须至少引用 1 条；",
        "3. 标签：采信＝可支撑主张；对立＝须正面回应的对侧；存疑＝勿单独当铁证；",
        "4. 优先序：细读集已按可核验（时间／数额／声明）与盒内排名排好——"
        "请优先引用列表靠前且标签为采信／对立的段落；存疑勿单独当铁证；",
        "5. 禁止编造资料清单／细读集以外的 segment_id。",
    ]
    if aligned:
        lines.append("★ 本盒已与细读带宽对齐：盒内段落均属可引用细读集；仍须按优先序引用。")
    if plan.get("pair_required"):
        lines.append(
            "★ 本题为冲突成对必读：证据中须同时出现 option_a（support）与 "
            "option_b（oppose）侧各至少一条。"
        )
    if close:
        lines.append("细读集（按优先序；唯一允许引用的 segment_id）：")
        for pid in close:
            it = by.get(pid) or {}
            label = it.get("label") or LABEL_SUSPECT
            stance = it.get("stance") or "neutral"
            side = it.get("side") or "none"
            ver = ((it.get("verifiability") or {}).get("score"))
            ver_s = f"{float(ver):.2f}" if ver is not None else "?"
            nail = ""
            vv = it.get("verifiability") or {}
            if int(vv.get("time_n") or 0) or int(vv.get("amount_n") or 0):
                nail = "｜钉=时点/数额"
            lines.append(
                f"- {pid}｜标签={label}｜stance={stance}｜side={side}"
                f"｜可核验={ver_s}{nail}"
            )
    # 盒内其余：对齐模式下不应出现；未对齐时仅披露、禁止引用
    rest = [str(it.get("para_id")) for it in items if not it.get("in_close_read")]
    if rest:
        lines.append(
            "盒内非细读（【禁止】作为 evidence.segment_id）：" + "、".join(rest)
        )
    lines.append("")
    return "\n".join(lines)


def tree17_prompt_from_dossier(dossier: Any) -> str:
    """从 dossier.accounting 取树17计划并渲染；缺席 → 空串（提示词与改前相同）。"""
    acc = getattr(dossier, "accounting", None) or {}
    blob = acc.get(ACCOUNTING_KEY)
    if not isinstance(blob, dict):
        return ""
    plan = blob.get("plan") if isinstance(blob.get("plan"), dict) else blob
    return render_cite_prompt_block(plan)


def attach_tree17_plan(dossier: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """写入 accounting，供 render_segments_block 注入。返回同一计划。"""
    if getattr(dossier, "accounting", None) is None:
        dossier.accounting = {}
    rec = {
        "plan": plan,
        "close_read": list(plan.get("close_read") or []),
        "pair_required": bool(plan.get("pair_required")),
        "conflict_route": bool(plan.get("conflict_route")),
    }
    dossier.accounting[ACCOUNTING_KEY] = rec
    return rec


def measure_cite_compliance(
    plan: dict[str, Any],
    cited_ids: list[str] | set[str] | None,
    *,
    metas: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """分析师实际引用 vs 树17计划 → 合规率三轴。

    1. 冲突两侧是否都引（仅 pair_required）
    2. 是否越出 rank 带宽（引用了非细读）
    3. 可核验优先是否遵守（细读内引用的可核验均值 ≥ 带宽外）
    """
    cited = [str(x) for x in (cited_ids or []) if str(x).strip()]
    cited_set = set(cited)
    close = list(plan.get("close_read") or [])
    close_set = set(close)
    box = list(plan.get("box") or [])
    box_set = set(box)
    items = {str(it.get("para_id")): it for it in (plan.get("items") or [])}

    # —— 1) 冲突成对 ——
    pair_required = bool(plan.get("pair_required"))
    side_of = {
        pid: str((items.get(pid) or {}).get("side") or "none") for pid in box
    }
    cited_sides = {side_of.get(p, "none") for p in cited_set if p in box_set}
    both_sides = (not pair_required) or (
        "option_a" in cited_sides and "option_b" in cited_sides
    )
    pair_ok = both_sides

    # —— 2) rank 带宽 ——
    in_close = [p for p in cited if p in close_set]
    out_of_band = [p for p in cited if p in box_set and p not in close_set]
    outside_box = [p for p in cited if p not in box_set]
    n_cited = len(cited_set)
    in_band_rate = (
        round(len(set(in_close)) / n_cited, 4) if n_cited else None
    )
    band_ok = (n_cited == 0) or (len(out_of_band) == 0 and len(outside_box) == 0)

    # —— 3) 可核验优先 ——
    def _ver(pid: str) -> float:
        it = items.get(pid) or {}
        v = it.get("verifiability")
        if isinstance(v, dict) and "score" in v:
            return float(v["score"])
        if metas and pid in metas:
            return float(verifiability_score(str((metas[pid] or {}).get("text") or ""))["score"])
        return 0.0

    ver_close = [_ver(p) for p in in_close]
    ver_oob = [_ver(p) for p in out_of_band]
    mean_close = sum(ver_close) / len(ver_close) if ver_close else None
    mean_oob = sum(ver_oob) / len(ver_oob) if ver_oob else None
    # 无带宽外引用 → 视为遵守；有带宽外则细读均值须 ≥ 带宽外均值
    if not out_of_band:
        ver_ok = True
    elif mean_close is None:
        ver_ok = False  # 只引带宽外、细读一条都没有
    else:
        ver_ok = mean_close + 1e-9 >= (mean_oob or 0.0)

    axes_ok = int(pair_ok) + int(band_ok) + int(ver_ok)
    # R41：可用引用密度——带宽内且（采信／对立 或 可核验≥0.45）的引用数 ÷ 盒长
    usable_ids: list[str] = []
    for p in in_close:
        it = items.get(p) or {}
        lab = str(it.get("label") or "")
        if lab in {LABEL_ACCEPT, LABEL_OPPOSE} or _ver(p) + 1e-12 >= 0.45:
            usable_ids.append(p)
    usable_cite_density = (
        round(len(set(usable_ids)) / len(box), 4) if box else 0.0
    )
    return {
        "n_cited": n_cited,
        "cited_ids": sorted(cited_set),
        "pair_required": pair_required,
        "pair_ok": pair_ok,
        "cited_sides": sorted(s for s in cited_sides if s and s != "none"),
        "band_ok": band_ok,
        "in_band_rate": in_band_rate,
        "in_close": in_close,
        "out_of_band": out_of_band,
        "outside_box": outside_box,
        "ver_ok": ver_ok,
        "mean_ver_close": round(mean_close, 4) if mean_close is not None else None,
        "mean_ver_oob": round(mean_oob, 4) if mean_oob is not None else None,
        "axes_ok": axes_ok,
        "axes_total": 3,
        "compliance_rate": round(axes_ok / 3.0, 4),
        "ok": axes_ok == 3,
        "n_usable_cited": len(set(usable_ids)),
        "usable_cite_density": usable_cite_density,
    }


def extract_cited_segment_ids(payload: dict[str, Any] | None) -> list[str]:
    """从分析师 JSON（conclusions[].evidence[].segment_id）抽引用 id。"""
    data = payload or {}
    cons = data.get("conclusions")
    if not isinstance(cons, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for con in cons:
        if not isinstance(con, dict):
            continue
        for ev in con.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            sid = str(ev.get("segment_id") or "").strip()
            if sid and sid not in seen:
                seen.add(sid)
                out.append(sid)
    return out


def build_analyst_user_prompt(
    question: str,
    *,
    plan: dict[str, Any],
    metas: dict[str, dict[str, Any]],
    per_segment_chars: int = 480,
    include_non_close: bool = False,
) -> str:
    """kg_lab 冒烟用：议题 + 树17纪律 + 细读段文。

    R30：默认只渲染细读集（与「只许引用细读」一致）；include_non_close
    仅用于对照实验。
    """
    lines = [f"研判议题：{question}", render_cite_prompt_block(plan).rstrip(), "", "资料清单："]
    ordered = list(plan.get("close_read") or [])
    if include_non_close:
        seen = set(ordered)
        for pid in plan.get("box") or []:
            if pid not in seen:
                ordered.append(pid)
                seen.add(pid)
    for pid in ordered:
        text = str((metas.get(pid) or {}).get("text") or "")
        if len(text) > per_segment_chars:
            text = text[:per_segment_chars] + "……"
        it = next((x for x in (plan.get("items") or []) if x.get("para_id") == pid), {})
        tag = it.get("label") or ""
        mark = "【细读】" if it.get("in_close_read") else "【禁止引用】"
        lines.append(f"{mark}[{pid}]（{tag}）{text}")
        lines.append("")
    lines.append("请只输出系统提示词规定的 JSON，不要输出任何其它文字。")
    return "\n".join(lines)


def filter_payload_to_close_band(
    payload: dict[str, Any] | None,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """机械剪枝：丢掉细读集外的 evidence；结论若被剪空则整条丢掉。"""
    data = dict(payload or {})
    close = set(plan.get("close_read") or [])
    cons_in = data.get("conclusions")
    if not isinstance(cons_in, list):
        return {"conclusions": [], "n_dropped_evidence": 0, "n_dropped_conclusions": 0}
    out_cons: list[dict[str, Any]] = []
    n_drop_ev = 0
    n_drop_con = 0
    for con in cons_in:
        if not isinstance(con, dict):
            n_drop_con += 1
            continue
        evs_in = con.get("evidence") or []
        if not isinstance(evs_in, list):
            evs_in = []
        kept_ev: list[dict[str, Any]] = []
        for ev in evs_in:
            if not isinstance(ev, dict):
                n_drop_ev += 1
                continue
            sid = str(ev.get("segment_id") or "").strip()
            if sid and sid in close:
                kept_ev.append(ev)
            else:
                n_drop_ev += 1
        if not kept_ev:
            n_drop_con += 1
            continue
        new_con = dict(con)
        new_con["evidence"] = kept_ev
        out_cons.append(new_con)
    return {
        "conclusions": out_cons,
        "n_dropped_evidence": n_drop_ev,
        "n_dropped_conclusions": n_drop_con,
    }


def repair_cites_to_band(
    payload: dict[str, Any] | None,
    plan: dict[str, Any],
    *,
    question: str,
    metas: dict[str, dict[str, Any]],
    generate_fn: Any | None = None,
    system_prompt: str = "",
) -> dict[str, Any]:
    """带宽修复：先机械剪枝；若仍无引用／成对失败则一轮重抽。

    generate_fn(prompt) -> {"parsed": dict, ...}；缺省不调用模型，只剪枝。
    """
    close = set(plan.get("close_read") or [])
    raw_cited = extract_cited_segment_ids(payload)
    oob = [p for p in raw_cited if p not in close]
    filtered = filter_payload_to_close_band(payload, plan)
    cited_after = extract_cited_segment_ids(filtered)
    compliance = measure_cite_compliance(plan, cited_after, metas=metas)
    repaired = False
    repair_raw = ""
    # 需要重抽：剪完无结论，或成对题剪后不成对
    need_regen = (
        generate_fn is not None
        and oob
        and (
            not filtered.get("conclusions")
            or (plan.get("pair_required") and not compliance["pair_ok"])
        )
    )
    if need_regen:
        allowed = "、".join(plan.get("close_read") or []) or "(空)"
        forbid = "、".join(oob)
        user = build_analyst_user_prompt(
            question, plan=plan, metas=metas, include_non_close=False,
        )
        repair_prompt = (
            (system_prompt + "\n\n" if system_prompt else "")
            + user
            + "\n\n【修复】上一轮引用了细读带宽外编号："
            + forbid
            + "。请重新作答：evidence.segment_id 只许使用："
            + allowed
            + "。只输出 JSON。"
        )
        resp = generate_fn(repair_prompt)
        parsed = (resp or {}).get("parsed") if isinstance(resp, dict) else {}
        if not isinstance(parsed, dict):
            parsed = {}
        repair_raw = str((resp or {}).get("raw") or "") if isinstance(resp, dict) else ""
        filtered2 = filter_payload_to_close_band(parsed, plan)
        if filtered2.get("conclusions"):
            filtered = filtered2
            repaired = True
            cited_after = extract_cited_segment_ids(filtered)
            compliance = measure_cite_compliance(plan, cited_after, metas=metas)
    return {
        "payload": {"conclusions": filtered.get("conclusions") or []},
        "cited_ids": cited_after,
        "compliance": compliance,
        "oob_before": oob,
        "n_dropped_evidence": int(filtered.get("n_dropped_evidence") or 0),
        "n_dropped_conclusions": int(filtered.get("n_dropped_conclusions") or 0),
        "repaired_by_regen": repaired,
        "repair_raw_chars": len(repair_raw),
    }
