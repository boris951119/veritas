"""刀七理由主张闸 + 刀八未引用披露 + 刀九子问三态。"""

from app.core.audit import KIND_LABEL, audit_all
from app.core.coverage_gap import (
    split_subquestions,
    subquestion_status,
    unused_topic_segments,
)
from app.core.evidence import Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType
from app.core.skills import KNOWN_GATES, SKILLS
from app.core.warrant_check import audit_warrant_theme


def _d(question: str) -> Dossier:
    d = Dossier(question=question)
    src = Source.create("账目", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="项目账目统计截止日为2025年3月31日，应收应付开票回款全量往来已覆盖。"))
    src.segments.append(Segment(
        id="SRC1#s2", source_id="SRC1",
        text="风险台账：进度延迟70%，核心开发人员离职20%。"))
    d.add_source(src)
    return d


def test_warrant_theme_flags_unsupported_claim():
    d = _d("各客户是否存在人员流失风险？")
    con = Conclusion.create(
        "不存在人员流失风险，因为项目账目统计截止日为2025年3月31日",
        author="a0", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "项目账目统计截止日为2025年3月31日", ["SRC1#s1"],
        note="账目", author="a0"))
    flags = audit_warrant_theme(d)
    assert flags and flags[0]["kind"] == "warrant_theme"
    assert "人员流失" in flags[0]["detail"]
    assert any(f["kind"] == "warrant_theme" for f in audit_all(d))
    assert "warrant_theme" in KIND_LABEL
    assert "warrant_theme" in KNOWN_GATES
    assert any(s.name == "warrant_theme" and s.gate == "warrant_theme"
               for s in SKILLS)


def test_warrant_theme_ignores_theme_restated_only_in_note():
    """说明里复述「人员流失」不能抵消所引段落没有该主题词。"""
    d = _d("各客户是否存在人员流失风险？")
    d.conclusions.append(Conclusion.create(
        "客户C项目不存在人员流失风险，因为项目账目统计截止日为2025年3月31日",
        author="mainstream", id="CON1"))
    d.add_evidence(EvidenceNode.create(
        "CON1", "账目统计截止日为2025年3月31日", ["SRC1#s1"],
        note="因此不存在人员流失风险。", author="mainstream"))
    flags = audit_warrant_theme(d)
    assert flags and "人员流失" in flags[0]["detail"]


def test_denial_backed_by_official_rebuttal_is_not_flagged():
    """谣言主叙事：并未资金链停工 ← 传闻不实、按计划运转。缺「资金链」原词不亮灯。"""
    d = Dossier(question="停工传闻是否属实？")
    src = Source.create("通报", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="针对某制造公司的停工传闻，监管部门核查后确认：该传闻不实，产线仍按计划运转。"))
    d.add_source(src)
    d.conclusions.append(Conclusion.create(
        "某制造公司并未因资金链断裂全面停工，产线仍按计划运转。",
        author="a0", id="CON1"))
    d.add_evidence(EvidenceNode.create(
        "CON1", "该传闻不实，产线仍按计划运转。", ["SRC1#s1"],
        note="因此不存在资金链问题。", author="a0"))
    assert audit_warrant_theme(d) == []


def test_denial_without_rebuttal_still_flags():
    """「不存在人员流失，因为截止日」没有裁决句，否定词不能放行。"""
    d = _d("各客户是否存在人员流失风险？")
    d.conclusions.append(Conclusion.create(
        "客户C项目不存在人员流失风险，因为账目统计截止日为2025年3月31日",
        author="a0", id="CON1"))
    d.add_evidence(EvidenceNode.create(
        "CON1", "账目统计截止日为2025年3月31日", ["SRC1#s1"],
        note="核查后确认不存在人员流失", author="a0"))
    flags = audit_warrant_theme(d)
    assert flags and "人员流失" in flags[0]["value"]


def test_warrant_theme_ok_when_segment_shares_theme():
    d = _d("人员流失？")
    con = Conclusion.create(
        "存在人员流失风险，核心开发人员离职20%", author="a0", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "核心开发人员离职20%", ["SRC1#s2"],
        note="离职", author="a0"))
    assert audit_warrant_theme(d) == []


def test_unused_topic_segments_lists_uncited_risk_row():
    d = _d("各客户项目是否存在延期、回款或人员流失风险？")
    con = Conclusion.create("账目已覆盖", author="a0", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "应收应付开票回款全量往来已覆盖", ["SRC1#s1"],
        note="账目", author="a0"))
    unused = unused_topic_segments(d)
    ids = {u["segment_id"] for u in unused}
    assert "SRC1#s2" in ids
    assert "SRC1#s1" not in ids


def test_unused_topic_skips_question_without_theme_words():
    """营收类议题不含延期/回款/人员词时，不拿全套主题组扫材料。"""
    d = _d("恒兴新材2025年中报营业收入和归母净利润是多少？")
    unused = unused_topic_segments(d)
    assert unused == []


def test_subquestion_status_reads_this_round_synthesis():
    """资料里已有「自述指标」时前提不再黄灯；主席本轮缺口仍要把该子问标成缺口。"""
    q = ("各客户项目是否存在延期、回款或人员流失风险？"
         "厂商技术方案的自述指标可信吗？")
    d = _d(q)
    d.sources[0].segments[0].text += "厂商自述指标为可用率99%。"
    d.conclusions.append(Conclusion.create(
        "回款方面：客户B累计回款512万元", author="a0", id="CON1"))
    chair = {"open_issues": [
        {"kind": "gap", "ref": "议题", "text": "自述指标未见第三方验证"},
    ]}
    blind = {s["text"]: s["status"] for s in subquestion_status(d)}
    seen = {s["text"]: s["status"] for s in subquestion_status(d, chair)}
    second = [k for k in seen if "自述" in k or "可信" in k][0]
    assert blind[second] == "unanswered"
    assert seen[second] == "gap"


def test_subquestion_status_marks_unanswered():
    q = ("各客户项目是否存在延期、回款或人员流失风险？"
         "厂商技术方案的自述指标可信吗？")
    assert len(split_subquestions(q)) >= 2
    d = _d(q)
    con = Conclusion.create(
        "回款方面：客户B累计回款512万元", author="a0", id="CON1")
    d.conclusions.append(con)
    d.synthesis = {
        "open_issues": [
            {"kind": "gap", "ref": "议题", "text": "延期一词资料零命中"},
        ],
    }
    statuses = {s["text"]: s["status"] for s in subquestion_status(d)}
    # 第一子问含回款 → 已答；第二子问被前提黄灯「自述指标可信零命中」标成缺口
    first = [k for k in statuses if "回款" in k or "延期" in k][0]
    second = [k for k in statuses if "自述" in k or "可信" in k][0]
    assert statuses[first] in ("answered", "gap")
    assert statuses[second] == "gap"
