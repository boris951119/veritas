"""议题前提核对器：问题实体在信源零命中 → 前置黄牌。"""

from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.premise_check import extract_entities, premise_flags

SEG_TEXT = "客户B的供应商已拖欠回款超过90天，账期从90天延长至150天，回款周期显著拉长。"


def _dossier(question: str, seg: str = SEG_TEXT) -> Dossier:
    d = Dossier(question=question)
    src = Source.create("T", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text=seg))
    d.add_source(src)
    return d


def test_entities_split_by_frame_words():
    ents = extract_entities("客户B的供应商是否拖欠回款？")
    assert "客户" in ents and "供应商" in ents and "拖欠回款" in ents
    assert all("是否" not in e for e in ents)


def test_covered_question_produces_no_flags():
    d = _dossier("客户B的供应商是否拖欠回款？")
    assert premise_flags(d) == []


def test_uncovered_entity_flagged():
    d = _dossier("新荣集团是否存在交付风险？")
    flags = premise_flags(d)
    assert len(flags) == 1
    assert flags[0]["kind"] == "premise" and flags[0]["value"] == "新荣集团"
    assert flags[0]["severity"] == "medium"


def test_latin_entity_zero_hit_flagged():
    d = _dossier("ACME公司是否存在交付风险？")
    flags = premise_flags(d)
    assert [f["value"] for f in flags] == ["ACME"]  # 「公司」「交付风险」属框架词不入查


def test_generic_analysis_words_not_checked():
    d = _dossier("请分析客户B的风险情况并评估影响")
    assert premise_flags(d) == []


def test_shareholder_question_template_not_flagged():
    """「第一大股东是谁」是问句模板，不是要在原文找的专有名。"""
    d = _dossier(
        "截至2024年半年度报告期末，第一大股东是谁？持股数量与持股比例？",
        "宜兴市中港投资有限公司持股97,500,000股，比例46.95%。",
    )
    assert premise_flags(d) == []
    assert "第一大股东是谁" not in extract_entities(d.question)


def test_flag_cap_at_five():
    d = _dossier("甲集团、乙集团、丙集团、丁集团、戊集团、己集团各有什么风险？")
    assert len(premise_flags(d)) <= 5
