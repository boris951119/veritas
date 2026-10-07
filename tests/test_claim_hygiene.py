"""输出脱敏、无基数百分比、货币口径、未核验出处、证据强度否决票数。"""

from app.core.claim_check import (
    audit_bare_percent, audit_unit_mismatch, audit_unverified_sources,
)
from app.core.conflicts import ConflictPair, Resolution, prefer_stronger_side
from app.core.dossier_diff import diff_conclusions
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, Segment, Source, SourceType,
)
from app.core.pii import mask_pii
from app.core.view_filter import redact_dossier


def _two(level_a, cred_a, level_b, cred_b) -> Dossier:
    d = Dossier(question="Q")
    src_a = Source.create("官方", SourceType.REPORT, credibility=cred_a, id="SRC-A")
    src_a.segments.append(Segment(id="SRC-A#s1", source_id="SRC-A", text="产线仍按计划运转。"))
    src_b = Source.create("帖子", SourceType.NEWS, credibility=cred_b, id="SRC-B")
    src_b.segments.append(Segment(id="SRC-B#s1", source_id="SRC-B", text="已因资金链断裂全面停工。"))
    d.add_source(src_a)
    d.add_source(src_b)
    d.conclusions.append(Conclusion.create("官方：未停工", author="tech", id="CON-0"))
    d.conclusions.append(Conclusion.create("谣言：已停工", author="rt", id="CON-1"))
    d.add_evidence(EvidenceNode.create(
        "CON-0", "产线仍按计划运转。", ["SRC-A#s1"],
        level=level_a, id="EV-0"))
    d.add_evidence(EvidenceNode.create(
        "CON-1", "已因资金链断裂全面停工。", ["SRC-B#s1"],
        level=level_b, id="EV-1"))
    return d


def test_mask_pii_phone_email_id():
    text = "联系 13912345678 与 张三@corp.com 身份证 110101199001011234"
    out = mask_pii(text)
    assert "13912345678" not in out
    assert "张三@corp.com" not in out
    assert "***@corp.com" in out
    assert "110101199001011234" not in out


def test_redact_view_masks_pii_in_quotes():
    d = Dossier(question="Q")
    src = Source.create("花名册", SourceType.NOTE, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1",
                                text="负责人手机 13812345678"))
    d.add_source(src)
    view, _ = redact_dossier(d, "confidential")
    assert "13812345678" not in view.sources[0].segments[0].text
    assert "13812345678" in d.sources[0].segments[0].text  # 原案卷保真


def test_bare_percent_without_base():
    d = Dossier(question="Q")
    src = Source.create("帖", SourceType.NEWS, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text="订单同比下降 50%。"))
    d.add_source(src)
    d.conclusions.append(Conclusion.create("订单同比下降 50%", author="a", id="CON1"))
    d.add_evidence(EvidenceNode.create("CON1", "订单同比下降 50%。", ["SRC1#s1"], id="EV1"))
    flags = audit_bare_percent(d)
    assert flags and flags[0]["kind"] == "percent_no_base"


def test_unit_mismatch_cny_usd():
    d = Dossier(question="Q")
    a = Source.create("中报", SourceType.REPORT, id="SRC1")
    a.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text="营收 300 亿人民币"))
    b = Source.create("外电", SourceType.NEWS, id="SRC2", url="https://example.com/x")
    b.segments.append(Segment(id="SRC2#s1", source_id="SRC2", text="revenue 300 亿美元"))
    d.add_source(a)
    d.add_source(b)
    flags = audit_unit_mismatch(d)
    assert flags and flags[0]["kind"] == "unit_mismatch"


def test_unverified_news_without_url():
    d = Dossier(question="Q")
    src = Source.create("帖", SourceType.NEWS, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text="传闻"))
    d.add_source(src)
    flags = audit_unverified_sources(d)
    assert flags and flags[0]["kind"] == "source_unverified"


def test_prefer_stronger_side_overrides_weaker_llm_winner():
    d = _two(EvidenceLevel.B, 0.85, EvidenceLevel.D, 0.3)
    pair = ConflictPair(a_id="CON-0", b_id="CON-1")
    res = Resolution(winner_id="CON-1", rationale="票多",
                     evidence_weight={"CON-0": 0.68, "CON-1": 0.12})
    out = prefer_stronger_side(pair, d, res)
    assert out.winner_id == "CON-0"
    assert out.method == "evidence_weight"
    assert "否决票数" in out.rationale


def test_rumor_offline_flips_to_official_and_keeps_dissent(tmp_path):
    from pathlib import Path

    from app.ingest.case_loader import load_case
    from app.pipeline import RunDeps, RunSpec, run_case
    from scripts.demo_offline import RumorVsOfficialStubClient

    case_dir = Path("cases/rumor-vs-official")
    stub_dossier = load_case(case_dir)
    result = run_case(
        RunSpec(case_dir=case_dir, out_dir=tmp_path / "out"),
        RunDeps(client=RumorVsOfficialStubClient(stub_dossier)),
    )
    d = result.dossier
    majors = [c for c in d.conclusions if c.status == "majority"]
    dissents = [c for c in d.conclusions if c.status == "dissent"]
    assert any("不实" in c.statement or "运转" in c.statement for c in majors)
    assert dissents
    res = d.conflicts[0]["resolution"]
    assert res["method"] == "evidence_weight"
    assert any(c.id == res["winner_id"] for c in majors)
    winner = next(c for c in d.conclusions if c.id == res["winner_id"])
    quotes = [e.quote for e in d.evidences if e.conclusion_id == winner.id]
    assert quotes and "传闻不实" in quotes[0]


def test_prefer_stronger_keeps_tie():
    d = _two(EvidenceLevel.B, 0.8, EvidenceLevel.B, 0.8)
    pair = ConflictPair(a_id="CON-0", b_id="CON-1")
    res = Resolution(winner_id="tie", method="tie")
    assert prefer_stronger_side(pair, d, res).winner_id == "tie"


def test_diff_conclusions_added_removed():
    a = Dossier(question="Q")
    a.conclusions.append(Conclusion.create("旧判断", author="a", id="CON-a"))
    b = Dossier(question="Q")
    b.conclusions.append(Conclusion.create("新判断", author="a", id="CON-b"))
    diff = diff_conclusions(a, b)
    assert diff["n_added"] == 1 and diff["n_removed"] == 1
