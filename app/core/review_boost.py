"""C-99／合入：锚审支撑分 + A0 软保底装箱（默认开，可回滚）。

流程（对齐探针 C-85 C 臂 + C-91 boost）：
  1) 现产 pack_material → A0
  2) BM25 前 K 候选；LLM 抽审查锚 + 批审「直接支撑」分
  3) 弱锚从 K 外补召回再审（及格≥6 才并入）
  4) 融合分＝审阅×1000 + bm25_norm；A0 段再 +B；分主序装箱

开关 VERITAS_REVIEW_BOOST（默认开）。失败／无客户端／测试禁真调用
→ 回退 A0 并披露，生产可关＝0。
不许把 L2 增益说成官方涨分。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from app.core.answer_slots import priority_segment_ids
from app.core.bm25 import rank_segments
from app.core.dup_check import duplicate_map
from app.core.evidence import Dossier
from app.core.material import pack_material, pack_search_queries
from app.core.relevance import classify_sources
from app.ingest.segment import SEGMENT_MAX

DEFAULT_B = 7000.0
DEFAULT_K = 180
DEFAULT_BATCH = 12
DEFAULT_REFILL = 40
SEG_CAP = 420
SEG_TAIL = 120

ChatFn = Callable[[str], str]  # prompt → raw text


def _billing_len(text: str) -> int:
    return min(len(text or ""), int(SEGMENT_MAX))


def _eligible_lengths(dossier: Dossier) -> dict[str, int]:
    dups = duplicate_map(dossier)
    relevance = {s["source_id"]: s for s in classify_sources(dossier)}
    lengths: dict[str, int] = {}
    for src in dossier.sources:
        if src.id in dups or (relevance.get(src.id) or {}).get("level") == "zero":
            continue
        for seg in src.segments:
            lengths[seg.id] = _billing_len(seg.text)
    if not lengths:
        for src in dossier.sources:
            if src.id in dups:
                continue
            for seg in src.segments:
                lengths[seg.id] = _billing_len(seg.text)
    return lengths


def _clip_seg(text: str) -> str:
    t = (text or "").strip()
    if len(t) <= SEG_CAP:
        return t
    head = SEG_CAP - SEG_TAIL - 1
    return t[:head] + "…" + t[-SEG_TAIL:]


def _parse_json_obj(raw: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", (raw or "").strip(), flags=re.S)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"无 JSON：{(raw or '')[:200]}")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("JSON 非对象")
    return obj


def _parse_scores(raw: str, n: int) -> list[float]:
    obj = _parse_json_obj(raw)
    items = obj.get("scores")
    if not isinstance(items, list) or len(items) != n:
        raise ValueError(f"scores 长度≠{n}")
    out: list[float] = []
    for it in items:
        if isinstance(it, dict):
            out.append(float(it.get("score", 0)))
        else:
            out.append(float(it))
    return out


def _fallback_anchors(question: str) -> dict:
    return {
        "subject": "",
        "dispute": (question or "")[:120],
        "time_or_number": "",
        "must_hit": [(question or "")[:80]],
        "aliases": [],
        "reject_if": ["仅背景", "换主体", "纯态度"],
        "_fallback": True,
    }


def _anchor_prompt(question: str) -> str:
    return "\n".join([
        "你是研判资料审查员。只做一件事：从议题抽出「审查锚」（判决标准），不要答题。",
        "同义／别称可写在 aliases。不要编造议题未出现的实体。",
        f"议题：{question}",
        "只输出 JSON：",
        '{"subject":"主体","dispute":"要裁的争点/分歧","time_or_number":"关键时点或数字或空",'
        '"must_hit":["过闸至少应对上的要点"],'
        '"aliases":["别称或同指"],'
        '"reject_if":["同学课噪声典型：相关但裁不了题的情形"]}',
    ])


def _review_prompt(
    question: str, anchors: dict, batch: list[tuple[int, str]],
) -> str:
    n = len(batch)
    max_high = max(1, min(3, n // 4))
    lines = [
        "你是资料审查员。任务：判断每段能否作为「直接支撑」回答该议题。",
        "先看审查锚，再看段落。换说法／别称／同指算对齐；同学课（同事件但裁不了争点）必须低分。",
        "不要编造段落外事实。拿不准宁低勿高。",
        "",
        f"议题：{question}",
        f"审查锚：{json.dumps(anchors, ensure_ascii=False)}",
        "",
        "分档：",
        "  9–10＝直接支撑争点（锚对齐，含换说法）",
        "  6–8＝部分支撑（有事实但缺关键锚）",
        "  3–5＝弱相关背景",
        "  0–2＝无关／换主体／纯态度／同学课噪声",
        "否决上限：换主体≤1；只有背景热闹≤2；纯态度≤3；说不清对哪条锚≤4。",
        f"本批 {n} 段：9–10 分不超过 {max_high} 段。",
        "段落：",
    ]
    for i, text in batch:
        lines.append(f"[{i}] {_clip_seg(text)}")
    lines.append(
        "只输出："
        f'{{\"scores\":[{{\"i\":0,\"score\":0到10}},...]}} 长度＝{n}。'
    )
    return "\n".join(lines)


def fuse_scores(
    bm25_scores: dict[str, float],
    id_scores: dict[str, float],
) -> dict[str, float]:
    out = {sid: 0.0 for sid in bm25_scores}
    max_b = max(bm25_scores.values()) if bm25_scores else 1.0
    max_b = max_b if max_b > 0 else 1.0
    for sid, sc in id_scores.items():
        b = float(bm25_scores.get(sid, 0.0)) / max_b
        out[sid] = float(sc) * 1000.0 + b
    return out


def pack_score_primary_nofill(
    dossier: Dossier,
    budget: int,
    scores: dict[str, float],
) -> set[str]:
    """分主序 + 关零分灌满（与 C-99 探针同形）。"""
    budget = max(1, int(budget))
    lengths = _eligible_lengths(dossier)
    selected: set[str] = set()
    used = 0

    def _take(seg_id: str) -> bool:
        nonlocal used
        if seg_id in selected or seg_id not in lengths:
            return False
        ln = lengths[seg_id]
        if used + ln > budget:
            return False
        selected.add(seg_id)
        used += ln
        return True

    for seg_id in priority_segment_ids(dossier):
        _take(seg_id)
    scored = [
        g for g in lengths
        if scores.get(g, 0.0) > 0.0 and g not in selected
    ]
    for seg_id in sorted(scored, key=lambda g: (-scores.get(g, 0.0), g)):
        if used >= budget:
            break
        _take(seg_id)
    return selected


def pack_score_primary(
    dossier: Dossier,
    budget: int,
    scores: dict[str, float],
) -> set[str]:
    """分主序 + 零分跨源轮转（对齐 C-91／C-99 探针）。"""
    budget = max(1, int(budget))
    lengths = _eligible_lengths(dossier)
    selected: set[str] = set()
    used = 0

    def _take(seg_id: str) -> bool:
        nonlocal used
        if seg_id in selected or seg_id not in lengths:
            return False
        ln = lengths[seg_id]
        if used + ln > budget:
            return False
        selected.add(seg_id)
        used += ln
        return True

    for seg_id in priority_segment_ids(dossier):
        _take(seg_id)
    scored = [
        g for g in lengths
        if scores.get(g, 0.0) > 0.0 and g not in selected
    ]
    for seg_id in sorted(scored, key=lambda g: (-scores.get(g, 0.0), g)):
        if used >= budget:
            break
        _take(seg_id)

    by_source: dict[str, list[str]] = {}
    for src in dossier.sources:
        for seg in src.segments:
            if seg.id in lengths and seg.id not in selected:
                by_source.setdefault(src.id, []).append(seg.id)
    for sid in by_source:
        by_source[sid].sort(key=lambda g: (-scores.get(g, 0.0), g))
    source_order = sorted(
        by_source,
        key=lambda s: -max(
            (scores.get(g, 0.0) for g in by_source[s]), default=0.0),
    )
    while used < budget:
        progressed = False
        for src_id in source_order:
            queue = by_source[src_id]
            for i, seg_id in enumerate(queue):
                if used + lengths[seg_id] <= budget:
                    queue.pop(i)
                    selected.add(seg_id)
                    used += lengths[seg_id]
                    progressed = True
                    break
        if not progressed:
            break
    return selected


def pack_with_a0_boost(
    dossier: Dossier,
    budget: int,
    fused: dict[str, float],
    sel_a0: set[str],
    *,
    B: float = DEFAULT_B,
) -> set[str]:
    boosted = dict(fused)
    for sid in sel_a0:
        boosted[sid] = float(boosted.get(sid, 0.0)) + float(B)
    return pack_score_primary(dossier, budget, boosted)


def _bm25_table(dossier: Dossier) -> dict[str, float]:
    queries = pack_search_queries(dossier)
    ranked = (
        rank_segments(dossier, queries=queries)
        if queries else rank_segments(dossier)
    )
    return {str(k): float(v) for k, v in dict(ranked).items()}


def _score_batches(
    chat: ChatFn,
    question: str,
    anchors: dict,
    texts: list[str],
    *,
    batch_size: int,
) -> tuple[list[float], int]:
    scores = [0.0] * len(texts)
    n_calls = 0
    for start in range(0, len(texts), batch_size):
        local = [
            (i, t) for i, t in enumerate(texts[start:start + batch_size])
        ]
        prompt = _review_prompt(question, anchors, local)
        raw = chat(prompt)
        n_calls += 1
        try:
            part = _parse_scores(raw, len(local))
        except Exception:
            raw2 = chat(prompt + "\n再次确认：只输出 JSON。")
            n_calls += 1
            try:
                part = _parse_scores(raw2, len(local))
            except Exception:
                part = [0.0] * len(local)
        for j, sc in enumerate(part):
            scores[start + j] = float(sc)
    return scores, n_calls


def _anchor_terms(anc: dict) -> list[str]:
    out: list[str] = []
    for key in ("subject", "dispute", "time_or_number"):
        v = str(anc.get(key) or "").strip()
        if v:
            out.append(v)
    for lst_key in ("must_hit", "aliases"):
        for x in anc.get(lst_key) or []:
            s = str(x).strip()
            if s and s not in out:
                out.append(s)
    return out[:12]


def _weak_anchors(
    anc: dict, id_scores: dict[str, float], text_of: dict[str, str],
) -> list[str]:
    terms = _anchor_terms(anc)
    weak: list[str] = []
    for seed in terms:
        covered = False
        for sid, sc in id_scores.items():
            if sc < 6.0:
                continue
            if seed and seed in (text_of.get(sid) or ""):
                covered = True
                break
        if not covered and seed:
            weak.append(seed)
    return weak[:6] or terms[:4]


def score_review_table(
    dossier: Dossier,
    chat: ChatFn,
    *,
    k: int = DEFAULT_K,
    batch_size: int = DEFAULT_BATCH,
    refill_n: int = DEFAULT_REFILL,
    do_refill: bool = True,
) -> tuple[dict[str, float], dict[str, Any]]:
    """返回 sid→审阅分 与 meta（调用次数等）。"""
    question = dossier.question or ""
    bm25 = _bm25_table(dossier)
    ranked = sorted(bm25.items(), key=lambda x: (-x[1], x[0]))
    ids = [sid for sid, _ in ranked[: max(1, int(k))]]
    text_of = {
        seg.id: (seg.text or "")
        for src in dossier.sources for seg in src.segments
    }
    texts = [text_of.get(sid, "") for sid in ids]

    n_calls = 0
    raw_anc = chat(_anchor_prompt(question))
    n_calls += 1
    try:
        anchors = _parse_json_obj(raw_anc)
    except Exception:
        try:
            raw2 = chat(_anchor_prompt(question) + "\n再次确认：只输出 JSON。")
            n_calls += 1
            anchors = _parse_json_obj(raw2)
        except Exception:
            anchors = _fallback_anchors(question)

    batch_scores, c = _score_batches(
        chat, question, anchors, texts, batch_size=batch_size)
    n_calls += c
    id_scores = {sid: float(sc) for sid, sc in zip(ids, batch_scores)}

    refill_keep = 0
    if do_refill and refill_n > 0:
        weak = _weak_anchors(anchors, id_scores, text_of)
        terms = _anchor_terms({**anchors, "must_hit": weak})
        in_k = set(ids)
        outside = []
        for sid, bsc in ranked:
            if sid in in_k:
                continue
            txt = text_of.get(sid, "")
            hit = sum(1 for t in terms if t and t in txt)
            if hit <= 0:
                continue
            outside.append((hit, bsc, sid))
        outside.sort(key=lambda x: (-x[0], -x[1], x[2]))
        refill_ids = [sid for _h, _b, sid in outside[:refill_n]]
        if refill_ids:
            refill_texts = [text_of.get(sid, "") for sid in refill_ids]
            sc_refill, c2 = _score_batches(
                chat, question, anchors, refill_texts, batch_size=batch_size)
            n_calls += c2
            for sid, sc in zip(refill_ids, sc_refill):
                if sc >= 6.0:
                    id_scores[sid] = max(id_scores.get(sid, 0.0), float(sc))
                    refill_keep += 1

    meta = {
        "k": k,
        "n_candidates": len(ids),
        "n_scored": len(id_scores),
        "n_calls": n_calls,
        "refill_n": refill_n if do_refill else 0,
        "refill_keep_ge6": refill_keep,
        "anchors_fallback": bool(anchors.get("_fallback")),
    }
    return id_scores, meta


def apply_review_boost_pack(
    dossier: Dossier,
    *,
    chat: ChatFn,
    budget_chars: int | None = None,
    B: float = DEFAULT_B,
    k: int = DEFAULT_K,
    batch_size: int = DEFAULT_BATCH,
    refill_n: int = DEFAULT_REFILL,
    do_refill: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """返回 (pack_dict 同 pack_material 形, disclosure)。

    pack_dict 至少含 selected／budget／n_selected／used_chars。
    """
    base = pack_material(dossier, budget_chars=budget_chars)
    sel_a0 = {str(x) for x in (base.get("selected") or [])}
    budget = int(base.get("budget") or budget_chars or 1)

    id_scores, score_meta = score_review_table(
        dossier, chat, k=k, batch_size=batch_size,
        refill_n=refill_n, do_refill=do_refill,
    )
    bm25 = _bm25_table(dossier)
    for sid in id_scores:
        bm25.setdefault(sid, 0.0)
    fused = fuse_scores(bm25, id_scores)
    selected = pack_with_a0_boost(
        dossier, budget, fused, sel_a0, B=float(B),
    )
    used = sum(
        _billing_len(dossier.segment(s).text if dossier.segment(s) else "")
        for s in selected
    )
    pack = {
        "selected": selected,
        "excluded": [],  # 披露面用 base excluded 即可；此处不重算
        "budget": budget,
        "n_total": base.get("n_total"),
        "n_selected": len(selected),
        "used_chars": used,
        "a0_n_selected": len(sel_a0),
    }
    disc = {
        "applied": True,
        "B": float(B),
        "score_meta": score_meta,
        "n_a0": len(sel_a0),
        "n_boost": len(selected),
        "n_symdiff": len(sel_a0 ^ selected),
    }
    return pack, disc


def try_review_boost_pack(
    dossier: Dossier,
    *,
    chat: ChatFn | None,
    budget_chars: int | None = None,
    enabled: bool = True,
    B: float = DEFAULT_B,
    k: int = DEFAULT_K,
    batch_size: int = DEFAULT_BATCH,
    refill_n: int = DEFAULT_REFILL,
    do_refill: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """生产入口：关旗／无 chat／任一步失败 → A0 + 披露。"""
    base = pack_material(dossier, budget_chars=budget_chars)
    if not enabled:
        return base, {"applied": False, "reason": "flag_off"}
    if chat is None:
        return base, {"applied": False, "reason": "no_client"}
    try:
        return apply_review_boost_pack(
            dossier, chat=chat, budget_chars=budget_chars,
            B=B, k=k, batch_size=batch_size,
            refill_n=refill_n, do_refill=do_refill,
        )
    except Exception as exc:
        return base, {
            "applied": False,
            "reason": "error_fallback_a0",
            "error": f"{type(exc).__name__}: {exc}",
        }
