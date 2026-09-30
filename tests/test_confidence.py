"""置信度 v0：分量可解释、方向单调。"""

from app.core.confidence import conclude_confidence, evidence_score
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    RelationKind,
    Segment,
    Source,
    SourceType,
)


def _dossier(cred: float) -> tuple[Dossier, str]:
    d = Dossier(question="Q")
    src = Source.create("T", SourceType.PAPER, credibility=cred, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text="原文"))
    d.add_source(src)
    return d, "SRC1#s1"


def _add(d, sid, *, level=EvidenceLevel.A, relation=RelationKind.CORRELATION, weight=1.0, cid="CON1", note=""):
    d.conclusions.append(Conclusion.create("S", author="a", id=cid)) \
        if not d.conclusion(cid) else None
    d.add_evidence(EvidenceNode.create(cid, "原文", [sid], level=level,
                                       relation=relation, weight=weight,
                                       note=note))


def test_no_evidence_zero():
    d, _ = _dossier(0.8)
    d.conclusions.append(Conclusion.create("S", author="a", id="CON0"))
    conf, parts = conclude_confidence("CON0", d)
    assert conf == 0.0 and parts["n_evidence"] == 0


def test_higher_credibility_higher_score():
    d1, s1 = _dossier(0.9)
    _add(d1, s1)
    d2, s2 = _dossier(0.3)
    _add(d2, s2)
    assert evidence_score(d1.evidences[0], d1) > evidence_score(d2.evidences[0], d2)


def test_causation_beats_correlation():
    """因果加成须有机制词支撑：有机制词 > 相关；裸标 causation（无机制
    表述）不加成——防虚标抬分（与 causation_support 闸同口径）。"""
    d, sid = _dossier(0.8)
    _add(d, sid, relation=RelationKind.CAUSATION)
    d2, sid2 = _dossier(0.8)
    _add(d2, sid2, relation=RelationKind.CORRELATION)
    # 裸标：引文/说明无机制词 → 与相关同分
    assert evidence_score(d.evidences[0], d) == \
        evidence_score(d2.evidences[0], d2)
    # 有机制词支撑：加成生效
    d3, sid3 = _dossier(0.8)
    _add(d3, sid3, relation=RelationKind.CAUSATION,
         note="接口缺失导致进度滞后")
    assert evidence_score(d3.evidences[0], d3) > \
        evidence_score(d2.evidences[0], d2)


def test_more_evidence_never_lower_confidence():
    d, sid = _dossier(0.8)
    _add(d, sid, cid="CON1")
    conf1, parts1 = conclude_confidence("CON1", d)
    _add(d, sid, cid="CON1")
    conf2, parts2 = conclude_confidence("CON1", d)
    assert conf2 >= conf1
    assert parts2["n_evidence"] == 2


def test_parts_are_explained_numbers():
    d, sid = _dossier(0.8)
    _add(d, sid)
    conf, parts = conclude_confidence("CON1", d)
    assert 0.0 < conf <= 1.0
    assert isinstance(parts["strength"], float) and isinstance(parts["coverage"], float)
    assert parts["levels"] == ["A"]
