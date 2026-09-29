"""话语机械核对器：质证引文闸（防稻草人）+ 引用存在性闸（防编造依据）。"""

from app.core.conflicts import ConflictPair, Resolution
from app.core.discourse_check import audit_discourse
from app.core.evidence import Dossier, Segment, Source, SourceType

SEG_TEXT = "全固态电芯的中试良率尚不足百分之四十，量产时间表尚未明确。"


def _dossier_with_conflict(rebuts: dict, rationale: str = "") -> Dossier:
    d = Dossier(question="Q")
    src = Source.create("T", SourceType.PAPER, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text=SEG_TEXT))
    d.add_source(src)
    pair = ConflictPair(a_id="CON-A", b_id="CON-B", topic="量产前景")
    pair.resolution = Resolution(winner_id="CON-A", rationale=rationale,
                                 rebuts=rebuts)
    d.conflicts.append(pair.to_dict())
    return d


def test_verbatim_rebuttal_quote_passes():
    d = _dossier_with_conflict(
        {"a": "乙方引「全固态电芯的中试良率尚不足百分之四十」属断章"})
    assert audit_discourse(d) == []


def test_strawman_quote_flagged():
    """质证把对方没说的话安上去：引文在全部段落零命中 → 黄牌。"""
    d = _dossier_with_conflict(
        {"a": "对方声称「所有客户都将立即违约」过于绝对"})
    flags = audit_discourse(d)
    assert len(flags) == 1
    assert flags[0]["kind"] == "rebut_quote" and flags[0]["side"] == "a"
    assert flags[0]["severity"] == "medium"


def test_ellipsis_quote_checks_each_part():
    d = _dossier_with_conflict(
        {"b": "甲方引「中试良率尚不足……量产时间表尚未明确」无误"})
    assert audit_discourse(d) == []


def test_nonexistent_conclusion_ref_flagged():
    d = _dossier_with_conflict({"a": "CON-9999 的证据不足"}, rationale="")
    flags = audit_discourse(d)
    assert [f["kind"] for f in flags] == ["rebut_ref"]


def test_arbitration_rationale_with_fake_evidence_id_flagged():
    d = _dossier_with_conflict({}, rationale="EV-deadbeef01 等级更高，故甲方胜")
    flags = audit_discourse(d)
    assert [f["kind"] for f in flags] == ["arbiter_ref"]


def test_arbitration_rationale_with_real_id_passes():
    d = _dossier_with_conflict({}, rationale="甲方证据强度更高")
    assert audit_discourse(d) == []


def test_unresolved_conflicts_not_audited():
    d = _dossier_with_conflict({})
    d.conflicts[0]["resolution"] = None
    assert audit_discourse(d) == []
