"""答辩演示：第三方智能体假引文入卷 → 机械打回并署名提交方（零 LLM）。"""

from __future__ import annotations

from app.agents.ingress import attribution_summary, ingest_external_judgment
from app.core.evidence import Dossier, Segment, Source, SourceType


def _mini_dossier() -> Dossier:
    d = Dossier(question="某制造公司是否已因资金链断裂全面停工？")
    src = Source.create(
        "监管核查通报", SourceType.REPORT, credibility=0.85, id="SRC1",
    )
    text = ("针对某制造公司的停工传闻，监管部门核查后确认："
            "该传闻不实，产线仍按计划运转。")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text=text, locator="段 1",
    ))
    d.add_source(src)
    return d


def run_external_reject_demo() -> dict:
    """假引文打回 + 真引文对照；不碰磁盘案卷。"""
    d = _mini_dossier()
    payload = {
        "agent": "灵境-研判助手",
        "agent_id": "lingjing-judge-demo",
        "submitted_at": "2026-10-10T00:00:00+00:00",
        "conclusions": [{
            "statement": "该公司已全面停工且不会复产",
            "evidence": [{
                "quote": "经查该公司已永久关停所有产线并遣散员工",
                "segment_id": "SRC1#s1",
                "relation": "causation",
                "level": "A",
                "note": "外部智能体主张",
            }],
        }],
    }
    ids = ingest_external_judgment(d, payload)
    attr = attribution_summary(d, ids, payload)
    ok_ids = ingest_external_judgment(d, {
        "agent": "灵境-研判助手",
        "agent_id": "lingjing-judge-demo",
        "conclusions": [{
            "statement": "监管认定传闻不实",
            "evidence": [{
                "quote": "该传闻不实，产线仍按计划运转",
                "segment_id": "SRC1#s1",
                "relation": "correlation",
                "level": "B",
            }],
        }],
    })
    return {
        "attribution": attr,
        "n_rejected_on_disk_view": len(d.rejected),
        "true_quote_kept": bool(ok_ids and d.evidences_of(ok_ids[0])),
        "fake_quote_surviving": any(
            "永久关停" in (e.quote or "") for e in d.evidences
        ),
    }
