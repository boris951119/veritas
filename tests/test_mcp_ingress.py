"""契约 B2：外部智能体结论入卷 ingest_external_judgment。

import 路径写死为 app.agents.ingress（深化实现落在此模块）。
"""

from __future__ import annotations

from app.core.citation_check import audit_dossier
from app.core.evidence import Dossier, Segment, Source, SourceType


def _dossier() -> Dossier:
    d = Dossier(question="Q")
    src = Source.create("笔记", SourceType.NOTE, credibility=0.5, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="全固态电芯的中试良率尚不足百分之四十。",
        locator="段 1"))
    d.add_source(src)
    return d


def test_ingest_external_judgment_materializes():
    """深化后：外部 payload 合法引文入卷并返回新结论 id。"""
    from app.agents.ingress import ingest_external_judgment

    d = _dossier()
    ids = ingest_external_judgment(d, {
        "agent": "ext-bot",
        "conclusions": [{
            "statement": "良率仍是瓶颈",
            "evidence": [{
                "quote": "全固态电芯的中试良率尚不足百分之四十",
                "segment_id": "SRC1#s1",
                "relation": "correlation",
                "level": "B",
                "note": "外部观察",
            }],
        }],
    })
    assert len(ids) == 1
    con = d.conclusion(ids[0])
    assert con is not None
    assert con.statement == "良率仍是瓶颈"
    assert d.evidences_of(ids[0])


def test_ingest_sets_author_to_external_agent():
    """深化后：入卷结论与证据的 author 为外部 agent 名。"""
    from app.agents.ingress import ingest_external_judgment

    d = _dossier()
    ids = ingest_external_judgment(d, {
        "agent": "ext-bot",
        "conclusions": [{
            "statement": "良率仍是瓶颈",
            "evidence": [{
                "quote": "全固态电芯的中试良率尚不足百分之四十",
                "segment_id": "SRC1#s1",
                "relation": "correlation",
                "level": "B",
                "note": "x",
            }],
        }],
    })
    con = d.conclusion(ids[0])
    assert con.author == "ext-bot"
    for ev in d.evidences_of(ids[0]):
        assert ev.author == "ext-bot"


def test_ingest_fabricated_quote_enters_rejected():
    """深化后：假引文经 citation 审计进入 rejected，不留在存活证据里。"""
    from app.agents.ingress import ingest_external_judgment

    d = _dossier()
    ids = ingest_external_judgment(d, {
        "agent": "ext-bot",
        "conclusions": [{
            "statement": "编造结论",
            "evidence": [{
                "quote": "这段话在原文中根本不存在",
                "segment_id": "SRC1#s1",
                "relation": "causation",
                "level": "A",
                "note": "假",
            }],
        }],
    })
    assert ids  # 结论 id 仍返回，但证据被打回
    rejected = audit_dossier(d)
    assert rejected or d.rejected
    assert not d.evidences_of(ids[0]) or all(
        e.verified is False for e in d.evidences_of(ids[0]))
    con = d.conclusion(ids[0])
    assert con.status == "insufficient"
    assert "资料不足" in con.statement


def test_ingest_rejected_carries_submitter():
    """打回记录带提交方署名，出事可指认哪家智能体。"""
    from app.agents.ingress import attribution_summary, ingest_external_judgment

    d = _dossier()
    payload = {
        "agent": "灵境-研判助手",
        "agent_id": "lingjing-judge-01",
        "submitted_at": "2026-10-09T12:00:00+00:00",
        "conclusions": [{
            "statement": "编造结论",
            "evidence": [{
                "quote": "原文根本没有这句话",
                "segment_id": "SRC1#s1",
                "relation": "correlation",
                "level": "C",
            }],
        }],
    }
    ids = ingest_external_judgment(d, payload)
    hit = [r for r in d.rejected if r.get("conclusion_id") in ids]
    assert hit
    assert hit[0]["agent"] == "灵境-研判助手"
    assert hit[0]["agent_id"] == "lingjing-judge-01"
    assert hit[0]["source"] == "external_ingest"
    attr = attribution_summary(d, ids, payload)
    assert attr["n_rejected"] == 1
    assert attr["agent_id"] == "lingjing-judge-01"
