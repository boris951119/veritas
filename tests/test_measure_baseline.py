"""基线测量器（scripts/measure_baseline.py）的单测。

按「尺子自己也要被量」的规矩写：这里**大部分用例是要求必须测出问题**的
must-detect 断言——如果测量器把越权断言数成 0、把免检闸数成已进场、
把空台账当成有台账，这些用例就该红。
"""

from pathlib import Path

import pytest

from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType)
from scripts.measure_baseline import measure

_UNIV_STATEMENT = "所有客户项目均不存在人员流失风险，回款稳定"
_CLEAN_STATEMENT = "客户B项目 2026 年 3 月核心开发人员离职率达 20%"


def _dossier(question: str, statement: str, *, cited: bool = True) -> Dossier:
    """5 段材料 + 1 条结论：引用 1 段 ⇒ 覆盖 20% < 25% 阈值，可测「声称范围却欠引用」。"""
    d = Dossier(question=question)
    src = Source.create("台账", SourceType.REPORT, id="SRC1")
    for i, text in enumerate(
        ["核心开发人员离职率达 20%，2026 年 3 月另 6 人合同到期",
         "客户B项目回款周期正常，无逾期记录",
         "客户C项目增补合同应收 235,100 元未核销",
         "供应商交付延迟两周，里程碑整体后移",
         "运维交接文档缺失，知识集中度过高"]):
        src.segments.append(Segment(id=f"SRC1#s{i}", source_id="SRC1", text=text))
    d.add_source(src)
    d.panel = ["mainstream"]
    d.conclusions.append(Conclusion.create(
        statement, author="mainstream", id="CON1", confidence=0.2))
    if cited:
        d.add_evidence(EvidenceNode.create("CON1", "核心开发人员离职率达 20%",
                                           ["SRC1#s0"], author="mainstream"))
    return d


def _write(tmp_path: Path, d: Dossier) -> Path:
    out = tmp_path / "report.json"
    d.to_json(out)
    return out


def test_universal_claim_with_low_coverage_is_counted(tmp_path):
    """全称量词 + 引用覆盖 <25% 必须同时被记下——这是范围越权的核心显影。"""
    row = measure(_write(tmp_path, _dossier(
        "各客户项目是否存在人员流失风险？回款风险呢？", _UNIV_STATEMENT)))
    assert row["n_conclusions"] == 1
    assert row["n_universal"] == 1
    assert row["n_universal_low_coverage"] == 1
    assert row["n_absence"] >= 0


def test_clean_conclusion_adds_no_overclaim(tmp_path):
    """反向对照：只陈述观测到的事实、不声称范围，越权计数必须为 0。"""
    row = measure(_write(tmp_path, _dossier(
        "各客户项目是否存在人员流失风险？回款风险呢？", _CLEAN_STATEMENT)))
    assert row["n_universal"] == 0
    assert row["n_overclaim"] == 0


def test_counting_gate_exemption_is_measured(tmp_path):
    """结论不写「计数:M/N」⇒ 计数闸压根不进场，免检率必须是 100%。"""
    row = measure(_write(tmp_path, _dossier(
        "各客户项目是否存在人员流失风险？回款风险呢？", _CLEAN_STATEMENT)))
    assert row["n_counting_in_scope"] == 0
    assert row["counting_exempt_rate"] == 1.0


def test_absence_claim_is_counted(tmp_path):
    """「未发现」被当成「不存在」说 ⇒ 缺失类断言必须计入。"""
    row = measure(_write(tmp_path, _dossier(
        "各客户项目是否存在人员流失风险？回款风险呢？",
        "资料中未发现人员流失记载，因此不存在流失风险")))
    assert row["n_absence"] == 1


def test_open_question_now_still_gets_a_ledger(tmp_path):
    """子问地基修复后的账：切不出子问的开放题走整题兜底，判据非空且声明偏弱。

    本用例原先断言 `n_obligations == 0`（钉住缺陷），2026-10-13 修完地基后翻案：
    若哪天兜底又被拆掉、台账重新变空，这里会立刻红。
    """
    row = measure(_write(tmp_path, _dossier(
        "评估这几个客户项目的交付风险并给出下一步建议", _CLEAN_STATEMENT)))
    assert row["n_subquestions_split"] == 1      # 标点确实切不开
    assert row["n_obligations"] == 1             # 但判据不能因此消失
    assert row["ledger_weak"] is True
    assert row["ledger_sources"] == ["whole_question"]


def test_broken_artifact_raises_not_silently(tmp_path):
    """坏产物必须抛异常由调用方记为失败，不能被当成「零问题」。"""
    bad = tmp_path / "report.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(Exception):
        measure(bad)


# ------------------------------------------------- 第四分量的净效应（第 5 件事）

def _as_legacy_artifact(d: Dossier) -> Dossier:
    """把案卷扮成「加分量之前落盘」的存量产物：置信度=三分量积，parts 无链键。

    净效应测量的前提就是改前值来自存量口径；直接拿现在的 recompute_all 结果
    当改前，等于把链因子乘两遍，量出来的价钱是假的。
    """
    from app.core.confidence import conclude_confidence

    for con in d.conclusions:
        _, parts = conclude_confidence(con.id, d, n_panel=1)
        if parts.get("note"):
            continue
        conf = (parts["strength"] * parts["coverage"]
                * (0.5 + 0.5 * parts["agreement"]))
        con.confidence = round(min(1.0, conf), 4)
        con.confidence_parts = {k: v for k, v in parts.items()
                                if not k.startswith("chain")}
    return d


def test_chain_effect_prices_a_broken_link():
    """断链的结论必须被量出降价——量不出差价就说明这条尺子是空的。"""
    from scripts.measure_baseline import chain_effect

    d = _as_legacy_artifact(_dossier(
        "各客户项目是否存在人员流失风险？回款风险呢？", _UNIV_STATEMENT))
    e = chain_effect(d)
    assert e["n_scored"] == 1 and e["n_unknown"] == 0
    assert e["conf_before"] != e["conf_after"]
    assert e["conf_after"][0] < e["conf_before"][0]
    assert "scope_declared" in e["broken_by_check"]


def test_chain_effect_does_not_penalize_a_closed_chain():
    """反向对照：链上触发的环全闭合 ⇒ 一分不扣（否则惩罚的是叙述长度不是断链）。"""
    from scripts.measure_baseline import chain_effect

    d = _as_legacy_artifact(_dossier(
        "各客户项目是否存在人员流失风险？回款风险呢？", _CLEAN_STATEMENT))
    e = chain_effect(d)
    assert e["broken_by_check"] == {}
    assert e["conf_after"] == e["conf_before"]
    assert e["chain_median"] == 1.0


def test_chain_effect_skips_conclusions_without_evidence():
    """没证据的结论走「无从判定」，不进净效应样本（它们的 0 分由前三分量承担）。"""
    from scripts.measure_baseline import chain_effect

    d = _as_legacy_artifact(_dossier(
        "各客户项目是否存在人员流失风险？回款风险呢？", _CLEAN_STATEMENT,
        cited=False))
    e = chain_effect(d)
    assert e["conf_before"] == [] and e["n_scored"] == 0
