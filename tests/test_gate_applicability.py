"""闸准入探针（app/core/gate_applicability）的单测。

这一层唯一的职责是**不许把「没查」说成「查过」**，所以每条用例都在验两件事：
该显影的显影了，不该显影的别乱显影（假免检比没免检更坏）。
"""

from app.core.audit import audit_all, audit_scan, summarize
from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, RelationKind, Segment, Source, SourceType)
from app.core.gate_applicability import (
    GATE_SPECS, gates_considered, not_evaluated, not_evaluated_note)


def _dossier(*, question="各客户项目是否延期？回款风险呢？",
             statements=("项目存在延期风险",), with_sources: int = 2,
             count_fmt: str = "", causation: bool = False) -> Dossier:
    d = Dossier(question=question)
    for i in range(with_sources):
        src = Source.create(f"资料{i}", SourceType.REPORT, id=f"SRC{i+1}")
        src.segments.append(Segment(
            id=f"SRC{i+1}#s1", source_id=f"SRC{i+1}",
            text="项目里程碑整体后移两周，核心开发人员离职率达 20%"))
        d.add_source(src)
    d.panel = ["mainstream"]
    for i, st in enumerate(statements):
        d.conclusions.append(Conclusion.create(st, author="mainstream",
                                               id=f"CON{i+1}", confidence=0.3))
        d.add_evidence(EvidenceNode.create(
            f"CON{i+1}", "项目里程碑整体后移两周", ["SRC1#s1"],
            author="mainstream",
            relation=RelationKind.CAUSATION if causation else RelationKind.CORRELATION))
    return d


def _kinds(notes: list[dict]) -> set[str]:
    return {n["kind"] for n in notes}


def test_counting_gate_reports_exemption_when_format_absent():
    """结论里没有任何「计数:M/N」写法 ⇒ 计数闸必须自报未执行。"""
    notes = _kinds(not_evaluated(_dossier()))
    assert "counting" in notes


def test_counting_gate_reports_work_when_format_present():
    """写了该格式就不再免检——探针只认闸自己认的那种写法，口径不许漂。"""
    d = _dossier(statements=("项目存在延期风险，计数:1/2",))
    assert "counting" not in _kinds(not_evaluated(d))


def test_causation_probe_follows_the_relation_annotation():
    """没有因果标注时机制词核对未执行；标了 causation 就必须算已执行。"""
    assert "causation_support" in _kinds(not_evaluated(_dossier()))
    assert "causation_support" not in _kinds(not_evaluated(_dossier(causation=True)))


def test_empty_dossier_is_never_reported_as_clean():
    """空案卷最危险：一条结论都没有时，「零警示」必须被判成不干净。"""
    empty = Dossier(question="某制造公司是否已全面停工？")
    scan = audit_scan(empty)
    assert scan["flags"] == []
    assert scan["not_evaluated"], "空案卷必须有未执行清单"
    assert scan["summary"]["clean"] is False


def test_clean_requires_both_no_flags_and_no_exemption():
    """clean 的定义：既没亮灯，也没有闸没进场。"""
    notes = not_evaluated(_dossier())
    assert summarize([], notes)["clean"] is False
    assert summarize([], [])["clean"] is True
    assert summarize([{"kind": "calc", "severity": "high"}], [])["clean"] is False


def test_probe_never_contradicts_a_flag_itself():
    """不变量：某个 kind 亮了灯，就绝不允许同时被记为「未执行」。

    2026-10-13 这条抓到过真 bug——两个探针 lambda 误用了外层变量名，
    抛 NameError 被 except 吞掉，于是「数字溯源」明明亮了灯还被写成免检。
    """
    for kwargs in ({}, {"causation": True},
                   {"statements": ("回款率 40%，计数:1/2",)},
                   {"with_sources": 1}):
        d = _dossier(**kwargs)
        clash = {f["kind"] for f in audit_all(d)} & _kinds(not_evaluated(d))
        assert not clash, f"{kwargs} 自相矛盾：{clash}"


def test_no_probe_silently_raises():
    """探针自己失灵不许伪装成留痕——异常文案一旦被测到就是回归。"""
    d = _dossier()
    bad = [n["kind"] for n in not_evaluated(d) if "探针执行异常" in n["reason"]]
    assert not bad, f"这些探针抛异常被吞了：{bad}"
    assert len(GATE_SPECS) == len(gates_considered())


def test_note_wording_refuses_to_imply_full_pass():
    """文案不许留歧义：必须明写「无警示不等于全部核对通过」。"""
    note = not_evaluated_note(not_evaluated(_dossier()))
    assert note and "不等于" in note
    assert not_evaluated_note([]) == ""


def test_every_spec_carries_a_human_readable_reason():
    """每条留痕都要能解释为什么没跑——只报 kind 不报原因的留痕没人能复核。"""
    for spec in GATE_SPECS:
        assert spec.reason and spec.label and len(spec.reason) >= 8
