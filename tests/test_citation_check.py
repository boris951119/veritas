"""零 LLM 引文核对器：逐字命中、空白归一、省略切分、打回汇总。"""

from app.core.citation_check import audit_dossier, check_evidence, check_quote, normalize
from app.core.evidence import Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType


def _dossier_with_text(text: str) -> tuple[Dossier, str]:
    d = Dossier(question="Q")
    src = Source.create("T", SourceType.PAPER, id="SRC1")
    seg = Segment(id="SRC1#s1", source_id="SRC1", text=text, locator="段 1")
    src.segments.append(seg)
    d.add_source(src)
    return d, seg.id


def test_exact_quote_hits():
    d, sid = _dossier_with_text("固态电池的能量密度显著高于液态锂离子电池。")
    ev = EvidenceNode.create("CON1", "能量密度显著高于液态锂离子电池", [sid])
    assert check_evidence(ev, d) == []


def test_whitespace_normalization_hits():
    d, sid = _dossier_with_text("报告显示  量产成本 下降 三成。")
    ev = EvidenceNode.create("CON1", "量产成本 下降 三成", [sid])
    assert check_evidence(ev, d) == []


def test_ellipsis_split_hits_in_order():
    text = "实验组续航提升百分之四十。成本方面仍高于预期。量产时间表尚未明确。"
    d, sid = _dossier_with_text(text)
    ev = EvidenceNode.create("CON1", "续航提升百分之四十……量产时间表尚未明确", [sid])
    assert check_evidence(ev, d) == []


def test_fabricated_quote_fails():
    d, sid = _dossier_with_text("实验组续航提升百分之四十。")
    ev = EvidenceNode.create("CON1", "续航提升了百分之六十", [sid])
    problems = check_evidence(ev, d)
    assert problems and "未命中" in problems[0]


def test_missing_segment_and_empty_quote_fail():
    d, _ = _dossier_with_text("原文。")
    missing = EvidenceNode.create("CON1", "原文", ["SRC1#s999"])
    assert any("不存在" in p for p in check_evidence(missing, d))
    empty = EvidenceNode.create("CON1", "   ", ["SRC1#s1"])
    assert any("空引文" in p for p in check_evidence(empty, d))


def test_audit_dossier_marks_and_collects():
    d, sid = _dossier_with_text("原文句子一二三。")
    d.conclusions.append(Conclusion.create("S", author="a", id="CON1"))
    good = EvidenceNode.create("CON1", "原文句子一二三", [sid], id="EV-G")
    bad = EvidenceNode.create("CON1", "编造的句子", [sid], id="EV-B")
    d.add_evidence(good)
    d.add_evidence(bad)
    failures = audit_dossier(d)
    assert [f.evidence_id for f in failures] == ["EV-B"]
    assert good.verified is True and bad.verified is False


def test_normalize_strips_all_whitespace():
    assert normalize("a b\tc\n d") == "abcd"


def test_typography_marks_are_tolerated():
    """Markdown 记号与全半角标点属排版差异：不构成打回理由。"""
    d, sid = _dossier_with_text("项目整体完成率**62%**，较计划提前。执行进度：100%。")
    stars = EvidenceNode.create("CON1", "整体完成率62%，较计划提前", [sid])
    colon = EvidenceNode.create("CON1", "执行进度:100%", [sid])
    assert check_evidence(stars, d) == []
    assert check_evidence(colon, d) == []


def test_content_change_still_fails_despite_mark_noise():
    """排版宽容不豁免内容篡改：数字被改写仍必须打回。"""
    d, sid = _dossier_with_text("完成率**62%**。")
    ev = EvidenceNode.create("CON1", "完成率**63%**", [sid])
    problems = check_evidence(ev, d)
    assert problems and "未命中" in problems[0]
