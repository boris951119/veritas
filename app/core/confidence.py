"""置信度量化 v0（榜单硬需求 3：按信源可信度、证据数量与一致性、
推理链完整性给分并说明依据）。

v0 口径（第 2 周升级为完整融合 + 人工修改后增量重算）：
- strength  证据强度：各证据 weight × 等级权 × 信源可信度 × 因果加成
            的加权均值；
- coverage  证据覆盖：证据越多越稳（边际递减，饱和于 4 条）；
- 综合 = strength × coverage，两分量原样写进 confidence_parts 解释。
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


def evidence_score(ev: EvidenceNode, dossier: Dossier) -> float:
    """单条证据的强度分（0-1）：等级 × 信源可信度 × 因果加成 × 人工权重。"""
    creds = []
    for sid in ev.segment_ids:
        src = dossier.source_of_segment(sid)
        if src is not None:
            creds.append(src.credibility)
    base = (sum(creds) / len(creds)) if creds else 0.3
    score = LEVEL_WEIGHT.get(ev.level, 0.5) * base * ev.weight
    if ev.relation == RelationKind.CAUSATION:
        score *= _CAUSATION_BONUS
    return min(1.0, max(0.0, score))


def conclude_confidence(conclusion_id: str, dossier: Dossier) -> tuple[float, dict]:
    """结论置信度 = strength × coverage；返回 (置信度, 分量解释)。"""
    evs = dossier.evidences_of(conclusion_id)
    if not evs:
        return 0.0, {"strength": 0.0, "coverage": 0.0, "n_evidence": 0,
                     "note": "无证据支撑"}
    scores = [evidence_score(e, dossier) for e in evs]
    strength = sum(scores) / len(scores)
    n = len(evs)
    coverage = _COVERAGE_FLOOR + (1 - _COVERAGE_FLOOR) * (
        1.0 - math.exp(-(n - 1) / (_COVERAGE_SATURATION - 1)))
    parts = {
        "strength": round(strength, 4),
        "coverage": round(coverage, 4),
        "n_evidence": n,
        "levels": sorted({e.level.value for e in evs}),
        "min_evidence_score": round(min(scores), 4),
    }
    return round(min(1.0, strength * coverage), 4), parts
