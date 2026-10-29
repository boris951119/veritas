"""资料预算装箱器：BM25 精排 + 跨信源轮转填充，装不下的全披露。

量大输入的「选择」层（夹层职能：选、围、标——绝不改写）：

1. 资格线：精确重复件与零相关信源先出局（沿用既有闸）；
2. 第一遍：议题槽位（answer_slots.priority_segment_ids）优先入箱；
3. 第二遍：BM25 分 > 0 的段落按「分／log2(字数)」降序填剩余预算
   （同预算内尽量多装高相关短段）；检索问句在装箱时做轻量增强
   （去财务探针污染、议题切面、命中标题、基组同义）——不改原文；
4. 保底：零分段落跨信源**轮转**填充——防止单一信源灌满预算；
5. 全披露：任何未装入的段落进 excluded 清单（报告「因预算未进入
   研判的段落」），读了什么、没读什么，账面可见——「资料不足」类
   结论的语义边界因此成立。

确定性承诺：同案卷 + 同预算 → 同一装箱结果（全体分析师同料，
冲突检测与仲裁的公平性前提）。检索分数只决定优先级，不豁免围栏
与机械闸——选进来的段落照包不可信边界、照过全部核对。
"""

from __future__ import annotations

from app.core.bm25 import rank_segments
from app.core.dup_check import duplicate_map
from app.core.evidence import Dossier
from app.core.relevance import classify_sources

DEFAULT_MATERIAL_CHAR_BUDGET = 80_000
ALIGN_MAX_ITERS = 6
WINDOW_EXCLUDE_REASON = "模型窗口截断（窗口对齐装箱）"

# 运行时预算（pipeline 按 Settings.material_char_budget 置位；
# render_segments_block / report 披露读同一值——全体出口口径一致）
_MATERIAL_BUDGET = DEFAULT_MATERIAL_CHAR_BUDGET
# 预算挤出段的 reason；窗口对齐时改为 WINDOW_EXCLUDE_REASON，与「预算截断」分家
_EXCLUDE_BUDGET_REASON = "预算截断"


def set_material_budget(value: int) -> None:
    global _MATERIAL_BUDGET
    _MATERIAL_BUDGET = max(1, int(value))


def material_budget() -> int:
    return _MATERIAL_BUDGET


def set_exclude_budget_reason(reason: str | None = None) -> None:
    """打包 excluded 的预算侧 reason；None／空串回退「预算截断」。"""
    global _EXCLUDE_BUDGET_REASON
    text = (reason or "").strip()
    _EXCLUDE_BUDGET_REASON = text or "预算截断"


def exclude_budget_reason() -> str:
    return _EXCLUDE_BUDGET_REASON


def production_pack_messages(
    dossier: Dossier,
    *,
    persona: str,
    profile_tier: str = "standard",
    focus_segment_ids: list[str] | None = None,
) -> list[dict]:
    """与 Analyst.analyze 同形的两条 messages（含 skills_rules／focus）。

    窗口对齐估算必须走这条，不许用 probe_pack_window 的替身构造。
    """
    from app.agents.prompts import render_segments_block, render_system_prompt
    from app.core.skills import render_skills_rules

    return [
        {"role": "system",
         "content": render_system_prompt(
             persona,
             skills_rules=render_skills_rules(dossier, profile_tier))},
        {"role": "user",
         "content": render_segments_block(
             dossier, focus_segment_ids=focus_segment_ids)},
    ]


def align_budget_to_window(
    dossier: Dossier,
    settings,
    *,
    persona: str,
    profile_tier: str = "standard",
    window_tokens: int | None = None,
) -> dict:
    """有界确定性缩档：整条生产提示词 est ≤ 窗口满值（不减 max_response_tokens）。

    返回 accounting["pack_window"] 形状。预算经 set_material_budget 钉死。
    C-67：window_tokens 实参优先（编队所用模型窗的最小值）；未传则读
    settings.model_context_tokens。公式与 0.92／zh_chars_per_token 不变。
    """
    from app.core.prompt_guard import estimate_prompt_window

    if window_tokens is not None:
        window = int(window_tokens)
    else:
        window = int(getattr(settings, "model_context_tokens", 0) or 0)
    density = float(getattr(settings, "zh_chars_per_token", 1.45) or 1.45)
    if density <= 0:
        density = 1.45
    orig = max(1, int(getattr(settings, "material_char_budget",
                              DEFAULT_MATERIAL_CHAR_BUDGET) or
                      DEFAULT_MATERIAL_CHAR_BUDGET))
    pack_on = bool(getattr(settings, "pack_to_window", True))

    def _stamp(rule: str, budget: int, *, est=None, n_iters=None,
               fits=None) -> dict:
        """disabled／unchecked：没估算过 → est／n_iters／fits 记 null。"""
        set_material_budget(budget)
        if rule in ("disabled", "unchecked"):
            set_exclude_budget_reason("预算截断")
            return {
                "rule": rule,
                "window_tokens": window,
                "target_tokens": window if window > 0 else 0,
                "budget": budget,
                "est_tokens": None,
                "n_iters": None,
                "fits": None,
            }
        if pack_on and budget < orig:
            set_exclude_budget_reason(WINDOW_EXCLUDE_REASON)
        else:
            set_exclude_budget_reason("预算截断")
        return {
            "rule": rule,
            "window_tokens": window,
            "target_tokens": window if window > 0 else 0,
            "budget": budget,
            "est_tokens": int(est or 0),
            "n_iters": int(n_iters or 0),
            "fits": bool(fits),
        }

    if not pack_on:
        return _stamp("disabled", orig)
    if window <= 0:
        return _stamp("unchecked", orig)

    # 先按原预算估一次：已进窗则零改动（判据 f 反向格）
    set_material_budget(orig)
    set_exclude_budget_reason("预算截断")
    msgs0 = production_pack_messages(
        dossier, persona=persona, profile_tier=profile_tier)
    rec0 = estimate_prompt_window(
        msgs0, window_tokens=window, zh_chars_per_token=density)
    est0 = int(rec0["est_tokens"])
    if int(rec0.get("overflow_tokens") or 0) <= 0:
        return _stamp("align_to_window", orig, est=est0, n_iters=1, fits=True)

    # 超窗：按比值有界缩档；每轮全量生产同形估算（判据 m）。无进程级缓存。
    est = est0
    n_iters = 0
    fits = False
    budget = min(
        orig,
        max(1, int(window * density)),
        max(1, int(orig * window / max(est0, 1) * 0.92)),
    )
    for _ in range(ALIGN_MAX_ITERS):
        n_iters += 1
        set_material_budget(budget)
        set_exclude_budget_reason(
            WINDOW_EXCLUDE_REASON if budget < orig else "预算截断")
        msgs = production_pack_messages(
            dossier, persona=persona, profile_tier=profile_tier)
        rec = estimate_prompt_window(
            msgs, window_tokens=window, zh_chars_per_token=density)
        est = int(rec["est_tokens"])
        if int(rec.get("overflow_tokens") or 0) <= 0:
            fits = True
            break
        new_budget = max(1, int(budget * window / max(est, 1) * 0.92))
        if new_budget >= budget:
            new_budget = max(1, budget // 2)
        if new_budget == budget:
            break
        budget = new_budget

    out = _stamp("align_to_window", budget, est=est, n_iters=n_iters, fits=fits)
    if not fits:
        set_exclude_budget_reason(WINDOW_EXCLUDE_REASON)
    return out


def _dossier_corpus_blob(dossier: Dossier, *, max_chars: int = 400_000) -> str:
    """案卷标题＋正文拼接，供门控同义过滤（扩展词必须已在案卷出现）。"""
    parts: list[str] = []
    n = 0
    for src in dossier.sources:
        if src.title:
            parts.append(src.title)
            n += len(src.title)
        for seg in src.segments:
            t = seg.text or ""
            parts.append(t)
            n += len(t)
            if n >= max_chars:
                return "\n".join(parts)
    return "\n".join(parts)


def _facet_queries(question: str) -> list[str]:
    """从议题切出对照面／从句，供多路 BM25（不改原议题）。"""
    import re
    q = (question or "").strip()
    if not q:
        return []
    parts = re.split(r"(?:还是|或是|？|\?|。)", q)
    facets = [p.strip("，、；; ") for p in parts if len(p.strip("，、；; ")) >= 4]
    for m in re.finditer(r"(?:称|认定|表示|认为|报道)([^，。？?]{2,24})", q):
        frag = m.group(1).strip()
        if frag:
            facets.append(frag)
    seen: set[str] = set()
    out: list[str] = []
    for f in facets:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out[:8]


def _title_queries(dossier: Dossier, question: str) -> list[str]:
    """标题与议题共享字符 2-gram 的信源标题 → 追加为检索问句。"""
    from app.core.bm25 import _tokens
    q_toks = set(_tokens(question or ""))
    if not q_toks:
        return []
    out: list[str] = []
    for src in dossier.sources:
        title = (src.title or "").strip()
        if not title or len(title) > 100:
            continue
        if set(_tokens(title)) & q_toks:
            out.append(title)
    return out[:8]


def pack_search_queries(dossier: Dossier) -> list[str]:
    """装箱时的 BM25 问句列表（走 query_rewrite 通道，可现场增强）。

    - 非财务题：剥掉历史 run 里 expand_query 打进去的财务探针尾；
    - 追加议题切面、命中标题、基组同义（扩展词∈案卷；门控专题已摘）；
    - 空则回退 rank_segments 默认（原问 + expand_query）。
    """
    from app.core.bm25 import (
        strip_finance_probe_tail,
        synonym_terms,
    )

    qinfo = (dossier.accounting or {}).get("query_rewrite") or {}
    if not isinstance(qinfo, dict):
        qinfo = {}
    original = (qinfo.get("original") or dossier.question or "").strip()
    variants = [str(v).strip() for v in (qinfo.get("variants") or []) if str(v).strip()]
    stored = [str(q).strip() for q in (qinfo.get("queries") or []) if str(q).strip()]
    corpus = _dossier_corpus_blob(dossier)

    out: list[str] = []
    seen: set[str] = set()

    def _add(q: str) -> None:
        q = (q or "").strip()
        if not q or q in seen:
            return
        seen.add(q)
        out.append(q)

    # R-C52-1：摘掉 looks_financial 分支——统一走剥探针尾＋基组同义（门控专题已摘）
    if original:
        _add(original)
        for v in variants:
            _add(strip_finance_probe_tail(v) or v)
        for sq in stored:
            cleaned = strip_finance_probe_tail(sq)
            if cleaned:
                _add(cleaned)
        syn = synonym_terms(original, corpus=corpus)
        if syn:
            _add(original + " " + " ".join(syn))
            for t in syn[:6]:
                _add(t)
        for f in _facet_queries(original):
            _add(f)
        for t in _title_queries(dossier, original):
            _add(t)
    elif stored:
        for sq in stored:
            _add(sq)

    return out[:16]


def pack_material(
    dossier: Dossier,
    budget_chars: int | None = None,
    *,
    exclude_seg_ids: set[str] | frozenset[str] | None = None,
    max_segments: int | None = None,
    fill_zero_score: bool = True,
    min_bm25: float = 0.0,
) -> dict:
    """确定性装箱：返回 {selected: set[seg_id], excluded: list[dict],
    budget, n_total, used_chars}。

    两段式（C-52）：① 议题槽位优先；② BM25>0 按分／log2(len) 填箱；
    零分段落再跨信源轮转保底。同案卷＋同预算 ⇒ 同结果。

    ``exclude_seg_ids``＝续盒用：已装段不进本箱（C-66／树16）。

    C-81（默认关＝与改前逐字同形）：``max_segments`` 硬顶段数；
    ``fill_zero_score=False`` 关掉零分轮转灌满；``min_bm25`` 提高密度段门槛
    （默认 0 ⇒ 仍只要 score>0）。生产路径不传这些参数。
    """
    import math
    from app.core.answer_slots import priority_segment_ids

    budget = max(1, int(budget_chars or _MATERIAL_BUDGET))
    cap = None if max_segments is None else max(1, int(max_segments))
    skip = {str(x) for x in (exclude_seg_ids or []) if str(x).strip()}
    dups = duplicate_map(dossier)
    relevance = {s["source_id"]: s for s in classify_sources(dossier)}

    # C-54：计费长度＝渲染后长度（与 render_segments_block 的 SEGMENT_MAX
    # 截断同形）。只改字数核算，不改写 seg.text、不改 SEGMENT_MAX 本身。
    from app.ingest.segment import SEGMENT_MAX as _SEGMENT_MAX

    def _billing_len(text: str) -> int:
        return min(len(text or ""), int(_SEGMENT_MAX))

    eligible: list[tuple[str, str]] = []  # (source_id, seg_id)
    lengths: dict[str, int] = {}
    for src in dossier.sources:
        if src.id in dups or (relevance.get(src.id) or {}).get("level") == "zero":
            continue
        for seg in src.segments:
            if seg.id in skip:
                continue
            eligible.append((src.id, seg.id))
            lengths[seg.id] = _billing_len(seg.text)

    # 短议题实体名对不上正文时，相关层会把全家打成 zero → 空箱。
    # 回退：忽略零相关，按 BM25（含探针扩展）装箱，仍排除精确重复件。
    if not eligible:
        for src in dossier.sources:
            if src.id in dups:
                continue
            for seg in src.segments:
                if seg.id in skip:
                    continue
                eligible.append((src.id, seg.id))
                lengths[seg.id] = _billing_len(seg.text)

    queries = pack_search_queries(dossier)
    scores = dict(rank_segments(dossier, queries=queries)
                  if queries else rank_segments(dossier))

    by_source: dict[str, list[str]] = {}
    for src_id, seg_id in eligible:
        by_source.setdefault(src_id, []).append(seg_id)
    for src_id in by_source:
        by_source[src_id].sort(key=lambda g: (-scores.get(g, 0.0), g))
    source_order = sorted(
        by_source,
        key=lambda s: -max((scores.get(g, 0.0) for g in by_source[s]),
                           default=0.0))

    selected: set[str] = set()
    used = 0

    def _full() -> bool:
        return cap is not None and len(selected) >= cap

    def _take(seg_id: str) -> bool:
        nonlocal used
        if _full():
            return False
        if seg_id in selected or seg_id not in lengths:
            return False
        ln = lengths[seg_id]
        if used + ln > budget:
            return False
        selected.add(seg_id)
        used += ln
        for queue in by_source.values():
            if seg_id in queue:
                queue.remove(seg_id)
                break
        return True

    # ① 议题槽位
    for seg_id in priority_segment_ids(dossier):
        if _full():
            break
        _take(seg_id)

    # ② BM25>min_bm25：按 score/log2(len) 降序填剩余预算（确定性破同分用 id）
    scored = [
        g for g in lengths
        if scores.get(g, 0.0) > float(min_bm25) and g not in selected
    ]

    def _density(seg_id: str) -> float:
        return scores.get(seg_id, 0.0) / math.log2(max(lengths[seg_id], 2))

    for seg_id in sorted(scored, key=lambda g: (-_density(g), g)):
        if used >= budget or _full():
            break
        _take(seg_id)

    # ③ 零分保底：跨信源轮转（C-81 可关＝不许灌噪声填满）
    if fill_zero_score:
        while used < budget and not _full():
            progressed = False
            for src_id in source_order:
                if _full():
                    break
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

    cut_reason = _EXCLUDE_BUDGET_REASON
    excluded = []
    for src_id, seg_id in eligible:
        if seg_id in selected:
            continue
        if cut_reason != "预算截断":
            reason = cut_reason
        elif scores.get(seg_id, 0.0) > 0:
            reason = "BM25 排序未入预算"
        else:
            reason = "预算截断"
        excluded.append({
            "source_id": src_id, "seg_id": seg_id, "reason": reason,
        })

    return {
        "selected": selected,
        "excluded": excluded,
        "budget": budget,
        "n_total": len(eligible),
        "n_selected": len(selected),
        "used_chars": used,
    }


# ---- 树16／C-66：续盒（多箱）------------------------------------------------------

DEFAULT_MULTI_BOX_MAX = 3


def pack_continuation_boxes(
    dossier: Dossier,
    *,
    budget_chars: int | None = None,
    max_boxes: int = DEFAULT_MULTI_BOX_MAX,
) -> dict:
    """逐箱剔除已装段后重装，最多 ``max_boxes`` 箱。

    返回 shape：
      boxes: [{index, selected, excluded, budget, used_chars, n_selected}, ...]
      union_selected: set[str]   # 构造保证：首箱 ⊆ 并集
      n_boxes / max_boxes / budget

    确定性：同案卷＋同预算＋同 max_boxes ⇒ 同结果。
    """
    cap = max(1, int(max_boxes))
    budget = max(1, int(budget_chars or _MATERIAL_BUDGET))
    boxes: list[dict] = []
    drop: set[str] = set()
    for i in range(cap):
        pack = pack_material(
            dossier, budget_chars=budget, exclude_seg_ids=drop)
        sel = {str(x) for x in (pack.get("selected") or [])}
        if not sel:
            break
        boxes.append({
            "index": i + 1,
            "selected": sorted(sel),
            "excluded": list(pack.get("excluded") or []),
            "budget": int(pack.get("budget") or budget),
            "used_chars": int(pack.get("used_chars") or 0),
            "n_selected": len(sel),
            "n_excluded": len(pack.get("excluded") or []),
        })
        drop |= sel
    union = set()
    for b in boxes:
        union |= set(b["selected"])
    # 构造不变量：首箱 ⊆ 并集（C-66 lost=0 前提）
    if boxes:
        assert set(boxes[0]["selected"]) <= union
    return {
        "boxes": boxes,
        "union_selected": union,
        "n_boxes": len(boxes),
        "max_boxes": cap,
        "budget": budget,
    }


def multi_box_accounting(plan: dict) -> dict:
    """进 report.accounting['multi_box'] 的可序列化账。"""
    boxes = plan.get("boxes") or []
    union = sorted(str(x) for x in (plan.get("union_selected") or []))
    return {
        "enabled": True,
        "n_boxes": int(plan.get("n_boxes") or 0),
        "max_boxes": int(plan.get("max_boxes") or DEFAULT_MULTI_BOX_MAX),
        "budget": int(plan.get("budget") or 0),
        "n_union": len(union),
        "union_selected": union,
        "per_box": [
            {
                "index": b["index"],
                "n_selected": b["n_selected"],
                "used_chars": b["used_chars"],
                "budget": b["budget"],
            }
            for b in boxes
        ],
    }
