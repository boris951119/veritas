"""资料预算装箱器：BM25 精排 + 跨信源轮转填充，装不下的全披露。

量大输入的「选择」层（夹层职能：选、围、标——绝不改写）：

1. 资格线：精确重复件与零相关信源先出局（沿用既有闸）；
2. 精排：BM25 分 > 0 的段落按分数降序优先装入；
3. 保底：零分段落跨信源**轮转**填充——防止单一信源灌满预算，
   保证每个信源至少有机会进入研判；
4. 全披露：任何未装入的段落进 excluded 清单（报告「因预算未进入
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

# 运行时预算（pipeline 按 Settings.material_char_budget 置位；
# render_segments_block / report 披露读同一值——全体出口口径一致）
_MATERIAL_BUDGET = DEFAULT_MATERIAL_CHAR_BUDGET


def set_material_budget(value: int) -> None:
    global _MATERIAL_BUDGET
    _MATERIAL_BUDGET = max(1, int(value))


def material_budget() -> int:
    return _MATERIAL_BUDGET


def pack_material(dossier: Dossier,
                  budget_chars: int | None = None) -> dict:
    """确定性装箱：返回 {selected: set[seg_id], excluded: list[dict],
    budget, n_total, used_chars}。"""
    budget = max(1, int(budget_chars or _MATERIAL_BUDGET))
    dups = duplicate_map(dossier)
    relevance = {s["source_id"]: s for s in classify_sources(dossier)}

    eligible: list[tuple[str, str]] = []  # (source_id, seg_id)
    lengths: dict[str, int] = {}
    for src in dossier.sources:
        if src.id in dups or (relevance.get(src.id) or {}).get("level") == "zero":
            continue
        for seg in src.segments:
            eligible.append((src.id, seg.id))
            lengths[seg.id] = len(seg.text)

    scores = dict(rank_segments(dossier))
    by_source: dict[str, list[str]] = {}
    for src_id, seg_id in eligible:
        by_source.setdefault(src_id, []).append(seg_id)
    # 信源内按 BM25 降序；信源间按其最高分降序（相关信源优先）
    for src_id in by_source:
        by_source[src_id].sort(key=lambda g: (-scores.get(g, 0.0), g))
    source_order = sorted(
        by_source,
        key=lambda s: -max((scores.get(g, 0.0) for g in by_source[s]),
                           default=0.0))

    # 轮转填充：每轮各信源取一段（能装入者），防单源灌满、保跨源覆盖；
    # 一整轮无一段能装入 → 预算尽，剩余统一进披露
    from app.core.answer_slots import priority_segment_ids

    selected: set[str] = set()
    used = 0
    # 议题槽位命中段优先入箱（问全年归母净利时，带期间口径的段不被无关段挤掉）
    pinned = [g for g in priority_segment_ids(dossier) if g in lengths]
    for seg_id in pinned:
        if used + lengths[seg_id] > budget:
            continue
        selected.add(seg_id)
        used += lengths[seg_id]
        for queue in by_source.values():
            if seg_id in queue:
                queue.remove(seg_id)
                break
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

    excluded = [{
        "source_id": src_id, "seg_id": seg_id,
        "reason": "BM25 排序未入预算" if scores.get(seg_id, 0.0) > 0
        else "预算截断",
    } for src_id, seg_id in eligible if seg_id not in selected]

    return {
        "selected": selected,
        "excluded": excluded,
        "budget": budget,
        "n_total": len(eligible),
        "n_selected": len(selected),
        "used_chars": used,
    }
