"""置信度量化（榜单硬需求 3：按信源可信度、证据数量与一致性、
推理链完整性给分并说明依据）。

三分量，全部可解释、可增量重算：
- strength   证据强度：等级权 × 信源可信度 × 因果加成 × 人工权重 的均值；
- coverage   证据覆盖：条数边际递减，饱和于 4 条；单条有基本覆盖下限；
- agreement  跨智能体一致性：结论署名数 / 分析师编队人数（归并组被多个
             分析师独立得出 → 加成；单人结论不打到 0，floor 0.5）。

综合 = strength × coverage × agreement_factor。
人工修改（删证据/改权重/改信源可信度）后调 recompute_conclusion()
只重算受影响结论——周 3 工作台的「修改后重算」走同一入口。
"""

from __future__ import annotations

import math

from app.core.evidence import (
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    LEVEL_WEIGHT,
    RelationKind,
)

_CAUSATION_BONUS = 1.15       # 因果证据加成（封顶 1）
_COVERAGE_SATURATION = 4      # 覆盖分饱和所需证据条数
_COVERAGE_FLOOR = 0.5         # 单条证据的覆盖分下限（有证据就有基本覆盖）
_AGREEMENT_FLOOR = 0.5        # 单人结论的一致性因子下限


def evidence_score(ev: EvidenceNode, dossier: Dossier) -> float:
    """单条证据的强度分（0-1）：等级 × 信源可信度 × 因果加成 × 人工权重。

    因果加成须有机制词支撑（引文/说明含「因为/导致/由此…」）——causation
    有加成即有虚标动机，无机制表述按相关计分（机械侧与 discourse_check
    的 causation_support 闸同口径，闸亮黄牌、此处压分）。"""
    creds = []
    for sid in ev.segment_ids:
        src = dossier.source_of_segment(sid)
        if src is not None:
            creds.append(src.credibility)
    base = (sum(creds) / len(creds)) if creds else 0.3
    score = LEVEL_WEIGHT.get(ev.level, 0.5) * base * ev.weight
    if ev.relation == RelationKind.CAUSATION:
        from app.core.discourse_check import has_mechanism_word

        if has_mechanism_word(ev.quote, ev.note):
            score *= _CAUSATION_BONUS
    return min(1.0, max(0.0, score))


def evidence_strength_of(conclusion_id: str, dossier: Dossier) -> float:
    """结论的证据平均强度（0-1；无证据为 0）——冲突加权的机械口径。"""
    evs = dossier.evidences_of(conclusion_id)
    if not evs:
        return 0.0
    return sum(evidence_score(e, dossier) for e in evs) / len(evs)


def conclude_confidence(conclusion_id: str, dossier: Dossier,
                        n_panel: int = 1) -> tuple[float, dict]:
    """结论置信度 = strength × coverage × agreement_factor。"""
    con = dossier.conclusion(conclusion_id)
    evs = dossier.evidences_of(conclusion_id)
    if con is None or not evs:
        return 0.0, {"strength": 0.0, "coverage": 0.0, "agreement": 0.0,
                     "n_evidence": len(evs), "note": "无证据支撑"}
    scores = [evidence_score(e, dossier) for e in evs]
    strength = sum(scores) / len(scores)
    n = len(evs)
    coverage = _COVERAGE_FLOOR + (1 - _COVERAGE_FLOOR) * (
        1.0 - math.exp(-(n - 1) / (_COVERAGE_SATURATION - 1)))
    n_authors = len({*con.author_names()}) or 1
    panel = max(1, int(n_panel))
    agreement = min(1.0, n_authors / panel)
    agreement_factor = _AGREEMENT_FLOOR + (1 - _AGREEMENT_FLOOR) * agreement
    parts = {
        "strength": round(strength, 4),
        "coverage": round(coverage, 4),
        "agreement": round(agreement, 4),
        "n_evidence": n,
        "n_authors": n_authors,
        "levels": sorted({e.level.value for e in evs}),
        "min_evidence_score": round(min(scores), 4),
    }
    conf = min(1.0, strength * coverage * agreement_factor)
    return round(conf, 4), parts


def recompute_conclusion(conclusion_id: str, dossier: Dossier,
                         n_panel: int = 1) -> float:
    """人工修改后的增量重算入口（工作台每改一处只重算受影响结论）。"""
    conf, parts = conclude_confidence(conclusion_id, dossier, n_panel)
    con = dossier.conclusion(conclusion_id)
    if con is not None:
        con.confidence = conf
        con.confidence_parts = parts
    return conf


def recompute_all(dossier: Dossier, n_panel: int = 1) -> None:
    """全量回填（管线收口与报告前调用）。"""
    for con in dossier.conclusions:
        recompute_conclusion(con.id, dossier, n_panel)
