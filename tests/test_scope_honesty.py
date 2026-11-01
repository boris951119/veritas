"""覆盖声明三态（scope_state）与范围诚实闸（scope_check）的单测。

负例优先：这个改动要治的是 2026-10-13 实测的那 17 条全称量词结论
（引用覆盖全部 <25%，最低 1.8%），其中 6 条现有闸全绿放行。
所以这里大部分用例要求**必须亮灯 / 必须构造失败**。
"""

import pytest

from app.core.audit import audit_all, audit_scan
from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType)
from app.core.scope_check import audit_scope, cited_share, scope_trigger
from app.core.scope_state import Coverage


def _dossier(*, statement: str, coverage=None, n_segments: int = 20,
             cited: int = 1) -> Dossier:
    d = Dossier(question="各客户项目是否存在延期、回款或人员流失风险？")
    src = Source.create("台账", SourceType.REPORT, id="SRC1")
    for i in range(n_segments):
        src.segments.append(Segment(id=f"SRC1#s{i}", source_id="SRC1",
                                    text=f"客户B项目记录 {i}：里程碑与回款台账条目"))
    d.add_source(src)
    d.panel = ["mainstream"]
    d.conclusions.append(Conclusion.create(statement, author="mainstream",
                                           id="CON1", confidence=0.3,
                                           coverage=coverage))
    if cited:
        d.add_evidence(EvidenceNode.create(
            "CON1", "客户B项目记录 0：里程碑与回款台账条目",
            [f"SRC1#s{i}" for i in range(cited)], author="mainstream"))
    return d


# ---------------------------------------------------------------- 三态：非法造不出来

def test_partial_without_limitations_cannot_be_constructed():
    """REA 式的类型级约束：说「部分覆盖」却不写局限，构造阶段就抛。"""
    with pytest.raises(ValueError, match="局限"):
        Coverage(state="partial", limitations=[])
    with pytest.raises(ValueError, match="局限"):
        Conclusion.create("x", coverage={"state": "partial"})


def test_unknown_without_reason_cannot_be_constructed():
    with pytest.raises(ValueError, match="为什么未知"):
        Coverage(state="unknown", reason="")


def test_illegal_state_is_rejected_rather_than_coerced():
    """状态名写错不许被顺手改成 complete。"""
    with pytest.raises(ValueError):
        Coverage(state="mostly")
    with pytest.raises(ValueError):
        Coverage.parse({"state": "全覆盖"})


def test_valid_states_construct_and_roundtrip():
    cov = Coverage(state="partial", limitations=["仅纳入 12/200 份"], scope="本次案卷")
    assert cov.to_dict()["limitations"] == ["仅纳入 12/200 份"]
    d = _dossier(statement="本次纳入资料未见人员流失", coverage=cov.to_dict())
    got = d.conclusions[0].coverage
    assert got.state == "partial" and got.limitations == ("仅纳入 12/200 份",)
    assert "部分覆盖" in got.note()


def test_old_artifacts_without_coverage_still_load():
    """向后兼容：存量 report.json 没有 coverage 字段 → None（未声明），不许炸。"""
    raw = {"id": "CON1", "statement": "老产物没有这字段", "status": "majority"}
    con = Conclusion.from_dict(raw)
    assert con.coverage is None


# ---------------------------------------------------------------- 闸：该亮必须亮

def test_universal_claim_without_declaration_is_flagged():
    """今天全绿放行那一类的最小复现：声称「所有」却只引 5% 段落。"""
    d = _dossier(statement="所有客户项目中未发现已发生的人员流失风险")
    flags = audit_scope(d)
    assert len(flags) == 1 and flags[0]["kind"] == "scope"
    assert flags[0]["severity"] == "medium"
    assert "5%" in flags[0]["detail"]          # 引用覆盖必须写进理由，方便改写
    assert "未发现" in flags[0]["detail"] or "所有" in flags[0]["detail"]


def test_absence_claim_alone_triggers_the_gate():
    """「未发现」这类没找到≠不存在的表述同样要声明范围。"""
    assert scope_trigger("资料中未发现停工记录")[1] == "absence"
    assert len(audit_scope(_dossier(statement="资料中未发现停工记录"))) == 1


def test_declared_partial_satisfies_the_gate():
    """写了局限就放行——闸要的是诚实，不是措辞洁癖。"""
    d = _dossier(statement="所有客户项目均未见人员流失",
                 coverage={"state": "partial",
                           "limitations": ["本次仅纳入 12/200 份信源"]})
    assert audit_scope(d) == []


def test_complete_declaration_without_evidence_is_still_flagged():
    """声称已覆盖全部却一条证据都没挂，是自相矛盾，照样亮灯。"""
    d = _dossier(statement="所有客户项目均无延期",
                 coverage={"state": "complete"}, cited=0)
    assert len(audit_scope(d)) == 1 and "自相矛盾" in audit_scope(d)[0]["detail"]


def test_plain_observed_statement_is_not_flagged():
    """反向对照：只说观察到的事、不带范围词，不许误伤。"""
    d = _dossier(statement="客户B项目里程碑后移两周")
    assert audit_scope(d) == []
    assert scope_trigger(d.conclusions[0].statement) is None


def test_scope_flag_survives_into_full_audit_and_scan():
    """接线检查：audit_all 与 audit_scan 都得带上这道闸。"""
    d = _dossier(statement="所有客户项目均未见人员流失")
    assert any(f["kind"] == "scope" for f in audit_all(d))
    scan = audit_scan(d)
    assert any(f["kind"] == "scope" for f in scan["flags"])
    assert scan["summary"]["clean"] is False
    # 声称了范围 ⇒ scope 闸本次有活干，不许被记成未执行
    assert "scope" not in {n["kind"] for n in scan["not_evaluated"]}


def test_cited_share_math_is_over_real_segments_only():
    """覆盖率的分子只数真实存在的段落，指向不存在段落的证据不算数。"""
    d = _dossier(statement="客户B台账条目 0 显示后移", cited=2)
    assert cited_share(d, "CON1") == pytest.approx(0.1)
    d.evidences[0].segment_ids.append("SRC1#s999")
    assert cited_share(d, "CON1") == pytest.approx(0.1)


# ---------------------------------------------------------------- 归并与人工改写

def test_merge_takes_the_most_conservative_declaration():
    """归并时局限不许蒸发：成员里最保守的那份往上并，顺序 unknown>partial>complete。"""
    merged = Coverage.merge_declarations([
        {"state": "complete"},
        {"state": "partial", "limitations": ["仅纳入 12/200 份信源"]},
    ])
    assert merged.state == "partial"
    assert "仅纳入 12/200 份信源" in merged.limitations


def test_merge_with_no_declarations_stays_undeclared():
    assert Coverage.merge_declarations([None, None]) is None


def test_group_conclusion_inherits_member_limitation():
    """组结论端到端：成员声明了部分覆盖，归并后代表结论仍带着那句局限。"""
    from app.agents.arbiter import Coordinator

    d = _dossier(statement="客户B项目存在延期风险",
                 coverage={"state": "partial", "limitations": ["仅纳入 12/200 份"]})
    second = Conclusion.create("客户B项目里程碑后移两周", author="redteam",
                               id="CON2", confidence=0.3)
    d.conclusions.append(second)
    d.add_evidence(EvidenceNode.create("CON2", "客户B项目记录 0：里程碑与回款台账条目",
                                       ["SRC1#s0"], author="redteam"))
    members = [d.conclusion("CON1"), d.conclusion("CON2")]
    group = Coordinator._materialize(d, members, "客户B项目存在延期风险")
    assert group.coverage is not None and group.coverage.state == "partial"
    assert "仅纳入 12/200 份" in group.coverage.limitations
    assert [m.status for m in members] == ["merged", "merged"]


def test_human_rewrite_drops_the_models_coverage_claim():
    """人工重写句子后，模型原先的覆盖声明作废——人自己得重新负责。"""
    from app.core.human_ops import edit_conclusion

    d = _dossier(statement="客户B项目未见人员流失",
                 coverage={"state": "complete"})
    assert audit_scope(d) == []                      # 声明齐备时本不亮灯
    edit_conclusion(d, "CON1", "所有客户项目均不存在人员流失风险")
    assert d.conclusion("CON1").coverage is None
    flags = audit_scope(d)
    assert len(flags) == 1 and flags[0]["kind"] == "scope"
