"""证据模型：构造约束、JSON 往返、案卷索引与变更。"""

import pytest

from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    Segment,
    Source,
    SourceType,
    SOURCE_CREDIBILITY_PRIOR,
)


def test_source_credibility_prior_and_range_guard():
    src = Source.create("某论文", SourceType.PAPER)
    assert src.credibility == SOURCE_CREDIBILITY_PRIOR[SourceType.PAPER]
    with pytest.raises(ValueError):
        Source.create("坏信源", SourceType.NEWS, credibility=1.5)


def test_dossier_json_roundtrip():
    d = Dossier(question="Q?")
    src = Source.create("T", SourceType.REPORT, credibility=0.7, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text="原文内容", locator="段 1"))
    con = Conclusion.create("结论一", author="m", id="CON1")
    d.add_source(src)
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "原文内容", ["SRC1#s1"], id="EV1",
        relation=__import__("app.core.evidence", fromlist=["RelationKind"]).RelationKind.CAUSATION,
        level=EvidenceLevel.A,
    ))
    clone = Dossier.from_dict(d.to_dict())
    assert clone.segment("SRC1#s1").text == "原文内容"
    assert clone.evidences[0].relation.value == "causation"
    assert clone.conclusions[0].evidence_ids == ["EV1"]


def test_remove_evidence_detaches_from_conclusion():
    d = Dossier(question="Q")
    con = Conclusion.create("S", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "q", ["SRC1#s1"], id="EV1"))
    assert con.evidence_ids == ["EV1"]
    d.remove_evidence("EV1")
    assert d.evidence("EV1") is None
    assert con.evidence_ids == []


def test_segment_lookup_helpers():
    d = Dossier(question="Q")
    src = Source.create("T", SourceType.WEB, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text="t"))
    d.add_source(src)
    assert d.source_of_segment("SRC1#s1") is src
    assert d.source_of_segment("nope") is None
