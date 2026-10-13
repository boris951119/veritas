"""冲突配对：主体闸、极性补召、丢弃披露；knife1 离线复放。"""

from pathlib import Path

from app.agents.arbiter import Coordinator
from app.core.conflict_pairing import (
    build_candidate_pairs,
    extract_subject,
    polarity_of,
    subject_mismatch_reason,
)
from app.core.conflicts import ConflictPair, validate_conflict
from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
)
from app.core.hashchain import HashChain
from app.pipeline import render_report_md
from tests.test_collab import ScriptedClient


def _con(d: Dossier, cid: str, stmt: str, quote: str = "引文占位足够长"):
    d.conclusions.append(Conclusion.create(stmt, author="a0", id=cid))
    d.add_evidence(EvidenceNode.create(
        cid, quote, ["SRC1#s1"], author="a0", id=cid.replace("CON", "EV")))


def _bi_shell() -> Dossier:
    d = Dossier(question="各客户是否存在回款或坏账风险？")
    src = Source.create("账", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text="引文占位足够长用于挂证。"))
    d.add_source(src)
    return d


def test_extract_subject_and_polarity():
    assert extract_subject("客户C（某头部券商）存在坏账风险") == "客户C"
    assert extract_subject("客户B累计回款无坏账") == "客户B"
    assert polarity_of("客户C不存在坏账风险，累计回款1088万") == "neg"
    assert polarity_of("客户C存在坏账风险，计提坏账43100元") == "pos"


def test_cross_subject_rejected_by_validate():
    d = _bi_shell()
    _con(d, "CON-c", "客户C（某头部券商）数据中台项目存在坏账风险")
    _con(d, "CON-b", "客户B（某地产集团）数据中台项目整体完成率为62%")
    assert subject_mismatch_reason(d, "CON-c", "CON-b")
    problems = validate_conflict(
        ConflictPair(a_id="CON-c", b_id="CON-b"), d)
    assert any("主体不一致" in p for p in problems)


def test_same_subject_polarity_forced_candidate():
    d = _bi_shell()
    _con(d, "CON-neg", "客户C（某头部券商）累计回款10,880,000.00元，无坏账风险")
    _con(d, "CON-pos", "客户C（某头部券商）存在坏账风险，坏账计提43100元")
    cands = build_candidate_pairs(d, ["CON-neg", "CON-pos"])
    assert len(cands) == 1
    assert cands[0]["forced_polarity"] is True


def test_detect_conflicts_drops_cross_subject_and_discloses():
    d = _bi_shell()
    _con(d, "CON-c", "客户C（某头部券商）数据中台项目存在回款风险")
    _con(d, "CON-b", "客户B（某地产集团）数据中台项目整体完成率为62%，无坏账风险")
    # 自由检出（无同主体候选）吐出跨主体对 → 必须丢掉并披露
    coord = Coordinator(ScriptedClient([
        '{"conflicts":[{"a":"CON-c","b":"CON-b","topic":"坏账",'
        '"description":"错配"}]}'
    ]), "m")
    pairs = coord.detect_conflicts(d, ["CON-c", "CON-b"])
    assert pairs == []
    acc = d.accounting.get("conflict_drops") or {}
    assert acc.get("n_dropped", 0) >= 1
    assert "主体不一致" in (acc.get("note") or "")
    md = render_report_md(d, HashChain(), [])
    assert "配对丢弃" in md and "主体不一致" in md


def test_detect_conflicts_recalls_same_subject_polarity():
    d = _bi_shell()
    _con(d, "CON-neg", "客户C（某头部券商）累计回款10,880,000.00元，无坏账风险")
    _con(d, "CON-pos", "客户C（某头部券商）存在坏账风险，计提坏账43,100元")
    # 模型漏选 → 程序补召
    coord = Coordinator(ScriptedClient([
        '{"conflicts":[]}'
    ]), "m")
    pairs = coord.detect_conflicts(d, ["CON-neg", "CON-pos"])
    assert len(pairs) == 1
    assert {pairs[0].a_id, pairs[0].b_id} == {"CON-neg", "CON-pos"}
    assert "补召" in (pairs[0].description or "")


def test_knife1_offline_cross_subject_pairs_would_drop():
    """靶子：knife1 里 2 场 C↔B 真错配，主体闸必须挡。"""
    path = Path("cases/bi-delivery-risk/out_local14b_knife1/report.json")
    if not path.exists():
        return
    d = Dossier.from_json(path)
    cross = []
    for raw in d.conflicts or []:
        a, b = raw.get("a_id"), raw.get("b_id")
        reason = subject_mismatch_reason(d, a, b)
        if reason:
            cross.append((a, b, reason))
    # 产物里至少那两场 C↔B
    assert len(cross) >= 2, cross
    for a, b, _ in cross:
        assert validate_conflict(ConflictPair(a_id=a, b_id=b), d)


def test_legacy_no_subject_pairs_still_work():
    """无客户标签时仍走自由检出（固态电池类）。"""
    d = Dossier(question="Q")
    src = Source.create("T", SourceType.PAPER, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text="全固态电芯的中试良率尚不足百分之四十。"))
    d.add_source(src)
    for i, stmt in enumerate(("结论甲难以量产", "结论乙已验证")):
        _con(d, f"CON-{i}", stmt, "全固态电芯的中试良率尚不足百分之四十")
    coord = Coordinator(ScriptedClient([
        '{"conflicts":[{"a":"CON-0","b":"CON-1","topic":"量产","description":"对立"}]}'
    ]), "m")
    pairs = coord.detect_conflicts(d, ["CON-0", "CON-1"])
    assert len(pairs) == 1
