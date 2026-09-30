"""输入生命周期三机制：事实对撞台账 / 时序核对 / 相关性分层。"""

import re

from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
)
from app.core.fact_ledger import extract_facts, facts_block, find_collisions
from app.core.relevance import classify_sources, unadopted_sources
from app.core.temporal_check import audit_temporal
from app.core.hashchain import HashChain
from app.pipeline import render_report_md


def _seg(d: Dossier, source_id: str, text: str, source_type=SourceType.REPORT,
         meta: dict | None = None) -> Source:
    src = Source.create(source_id, source_type, id=source_id, meta=meta or {})
    src.segments.append(Segment(id=f"{source_id}#s1", source_id=source_id,
                                text=text))
    d.add_source(src)
    return src


# -- 事实对撞台账 ---------------------------------------------------------------


def _two_source_collision_dossier() -> Dossier:
    d = Dossier(question="客户B的回款情况如何？")
    _seg(d, "SRC1", "客户B回款率40%，回款正常。", meta={"published_at": "2025-06"})
    _seg(d, "SRC2", "客户B回款率45%，回款正常。", meta={"published_at": "2026-03"})
    return d


def test_cross_source_collision_detected():
    d = _two_source_collision_dossier()
    collisions = find_collisions(d)
    assert len(collisions) == 1
    c = collisions[0]
    assert (c.entity, c.metric) == ("客户b", "回款率") or c.entity == "客户B"
    assert c.cross_source
    assert {f.raw for f in c.facts} == {"40%", "45%"}


def test_different_entities_do_not_collide():
    d = Dossier(question="回款情况")
    _seg(d, "SRC1", "客户B回款率40%。")
    _seg(d, "SRC2", "客户C回款率45%。")
    assert find_collisions(d) == []


def test_unit_scaling_prevents_false_collision():
    d = Dossier(question="回款情况")
    _seg(d, "SRC1", "客户B累计回款512万元。")
    _seg(d, "SRC2", "客户B累计回款0.0512亿元。")
    assert find_collisions(d) == []


def test_years_are_not_facts():
    d = Dossier(question="营收情况")
    _seg(d, "SRC1", "2026年3月，客户B营收1200万元。")
    facts = extract_facts(d)
    assert all(f.metric != "" for f in facts)
    assert not any(f.raw.startswith("2026") for f in facts)


def test_facts_block_injected_only_with_collisions():
    clean = Dossier(question="回款情况")
    _seg(clean, "SRC1", "客户B回款率40%。")
    assert facts_block(clean) == ""
    d = _two_source_collision_dossier()
    block = facts_block(d)
    assert "数字冲突" in block and "SRC1" in block and "SRC2" in block


# -- 时序核对（时效闸 + as-of 闸） -------------------------------------------------


def _stale_dossier(cited_old: bool, anchor_time: bool) -> Dossier:
    d = _two_source_collision_dossier()
    con = Conclusion.create(
        "客户B回款率40%" + ("，截至2025年报" if anchor_time else ""),
        author="a", id="CON1")
    d.conclusions.append(con)
    _seg(d, "SRC3", "客户B经营平稳。")  # 供引用的非对撞段落
    d.add_evidence(EvidenceNode.create(
        "CON1", "客户B回款率40%，回款正常。" if cited_old
        else "客户B回款率45%，回款正常。",
        ["SRC1#s1"] if cited_old else ["SRC2#s1"], author="a"))
    return d


def test_stale_flag_when_citing_only_old_source():
    d = _stale_dossier(cited_old=True, anchor_time=True)
    flags = [f for f in audit_temporal(d) if f["kind"] == "stale"]
    assert flags and "SRC2(2026-03)" in flags[0]["detail"]


def test_no_stale_flag_when_citing_newest():
    d = _stale_dossier(cited_old=False, anchor_time=True)
    assert not [f for f in audit_temporal(d) if f["kind"] == "stale"]


def test_as_of_flag_without_time_anchor():
    d = _stale_dossier(cited_old=False, anchor_time=False)
    flags = [f for f in audit_temporal(d) if f["kind"] == "as_of"]
    assert flags and "未锚定时点" in flags[0]["detail"]


def test_undated_sources_produce_no_as_of_flags():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "客户B回款率40%。")  # 无时点
    con = Conclusion.create("客户B回款率40%", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "回款率40%", ["SRC1#s1"]))
    assert audit_temporal(d) == []


# -- 相关性分层 ------------------------------------------------------------------


def _mixed_dossier() -> Dossier:
    d = Dossier(question="固态电池2030年前能否规模上车？")
    _seg(d, "SRC1", "固态电池的中试良率尚不足百分之四十，装车验证推进中。")
    _seg(d, "SRC2", "固态电池相关专利数量逐年上升，产业化路径逐步清晰。")
    _seg(d, "SRC3", "红烧肉的做法：五花肉焯水后加冰糖炒糖色，小火慢炖四十分钟。")
    return d


def test_irrelevant_source_classified_zero():
    levels = {s["source_id"]: s["level"] for s in classify_sources(_mixed_dossier())}
    assert levels["SRC3"] == "zero"
    assert levels["SRC1"] == "high"


def test_weakly_related_source_classified_low():
    d = Dossier(question="固态电池2030年前能否规模上车？")
    _seg(d, "SRC1", "固态电池的中试良率尚不足百分之四十。")
    _seg(d, "SRC2", "锂价今夏小幅波动，下游排产平淡。")  # 仅「电池」级弱重合
    levels = {s["source_id"]: s["level"] for s in classify_sources(d)}
    assert levels["SRC2"] in ("low", "zero")


def test_zero_source_excluded_from_prompt_but_disclosed():
    d = _mixed_dossier()
    from app.agents.prompts import render_segments_block

    block = render_segments_block(d)
    assert "SRC3" not in block and "红烧肉" not in block
    assert "SRC1" in block
    unadopted = unadopted_sources(d)
    assert [s["source_id"] for s in unadopted] == ["SRC3"]
    assert "零重合" in unadopted[0]["reason"]


def test_no_question_entities_means_no_judgment():
    d = Dossier(question="请分析。")
    _seg(d, "SRC1", "任意内容。")
    assert all(s["level"] == "high" for s in classify_sources(d))


# -- 报告披露 -------------------------------------------------------------------


def test_report_discloses_collisions_and_unadopted():
    d = _mixed_dossier()
    _seg(d, "SRC4", "客户B回款率40%。", meta={"published_at": "2025-06"})
    _seg(d, "SRC5", "客户B回款率45%。", meta={"published_at": "2026-03"})
    con = Conclusion.create("截至2025年报，客户B回款率40%", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "客户B回款率40%。",
                                       ["SRC4#s1"], author="a"))
    md = render_report_md(d, HashChain(), [])
    assert "资料内数字冲突" in md and "跨信源" in md
    assert "未采信信源" in md and "SRC3" in md
    stale = [f for f in audit_temporal(d) if f["kind"] == "stale"]
    assert stale  # 时效闸也覆盖该场景
