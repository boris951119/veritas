"""推理链完整性（第四分量）的单测。

核心要守住的不是"分数算得对"，而是**分数与警示不许打架**：
某道闸对一条结论亮了灯，链上对应那一环就必须判为断——否则工作台一边
显示「链完整性 1.00」一边挂着黄牌，产品主张当场破产。
"""

import pytest

from app.core.chain_integrity import (
    CHECK_ORDER, _BROKEN_BY_KIND, chain_context, chain_integrity,
    summarize_chain)
from app.core.confidence import (_CHAIN_FLOOR, _CHAIN_UNKNOWN,
                                 conclude_confidence, recompute_all)
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, RelationKind, Segment,
    Source, SourceType)


def _dossier(*, statement="客户B项目里程碑后移两周", quote="项目后移两周",
             seg_text="项目后移两周，回款正常", themes=True,
             with_date=False, causation=False, coverage=None,
             note="") -> Dossier:
    d = Dossier(question="客户B项目是否存在延期风险？")
    src = Source.create("台账", SourceType.REPORT, id="SRC1",
                        meta={"published_at": "2026-03"} if with_date else {})
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text=seg_text))
    d.add_source(src)
    d.panel = ["mainstream"]
    d.conclusions.append(Conclusion.create(statement, author="mainstream",
                                           id="CON1", confidence=0.2,
                                           coverage=coverage))
    d.add_evidence(EvidenceNode.create(
        "CON1", quote, ["SRC1#s1"], author="mainstream", level=EvidenceLevel.B,
        relation=RelationKind.CAUSATION if causation else RelationKind.CORRELATION,
        note=note))
    return d


def _dossier_without_evidence() -> Dossier:
    """没挂证据的结论：链上六环无一触发（正文既无数字也无范围词）。"""
    d = _dossier()
    d.evidences.clear()
    return d


def _chain(d, cid="CON1"):
    conf, parts = conclude_confidence(cid, d, n_panel=1)
    return parts, conf


# ---------------------------------------------------------------- 计分口径

def test_clean_chain_gets_full_score_and_no_penalty():
    d = _dossier()
    parts, conf = _chain(d)
    assert parts["chain"] == 1.0
    assert parts["chain_detail"]["broken"] == []
    rep = chain_integrity(d, "CON1")
    assert rep.applicable and not rep.broken


def test_broken_warrant_lowers_chain_and_confidence():
    """引文真、但所引段落不含主张的主题词：链上「理由支撑主张」必须断，
    且分数下降（段落写「人员编制」，主张谈「回款」——真引文推不出真主张）。"""
    d = _dossier(statement="客户B项目不存在回款风险",
                 quote="项目后移两周",
                 seg_text="项目后移两周，人员编制稳定")
    parts, _ = _chain(d)
    detail = parts["chain_detail"]
    assert "warrant_theme" in detail["broken"]
    assert "quote_hits" not in detail["broken"]        # 引文本身是真的
    # 「不存在…风险」同时是范围断言 → scope_declared 一起断：链上三分之二的环散
    assert detail["applicable"] == ["quote_hits", "warrant_theme", "scope_declared"]
    assert parts["chain"] == pytest.approx(1 / 3, abs=1e-3)
    # 同一处脱节、换个不含范围词的说法：分母收窄到两环，断一环即 0.5
    only = _dossier(statement="客户B项目回款已成定局", quote="项目后移两周",
                    seg_text="项目后移两周，人员编制稳定")
    o_parts, _ = _chain(only)
    assert o_parts["chain_detail"]["broken"] == ["warrant_theme"]
    assert o_parts["chain"] == 0.5


def test_applicable_only_counts_checks_that_apply():
    """没写数字的结论，「数字可溯源」不进分母——不许靠少说话白捡满分，
    也不许因没写数字被扣分。"""
    d = _dossier(statement="客户B项目里程碑后移两周")
    rep = chain_integrity(d, "CON1")
    assert "number_traceable" not in rep.applicable
    assert rep.score is not None and rep.score == 1.0


def test_no_applicable_check_is_unknown_not_perfect():
    """一环都不触发（这条结论没挂证据、正文无数字无范围词）时判 unknown，
    不给满分。注意链本身此时 score=None；置信度侧的无证据结论在更早的
    分支就返回 0，所以 unknown 是链口径的规矩而非融合分数的常态。"""
    rep = chain_integrity(_dossier_without_evidence(), "CON1")
    assert rep.applicable == [] and rep.score is None and rep.unknown


def test_unknown_factor_is_between_perfect_and_broken():
    """未知档因子既不许等于满分，也不许等于断链最低分。"""
    from app.core.confidence import chain_factor_of

    assert chain_factor_of(None) == _CHAIN_UNKNOWN
    assert chain_factor_of(1.0) == 1.0
    assert chain_factor_of(0.0) == _CHAIN_FLOOR
    assert _CHAIN_FLOOR < _CHAIN_UNKNOWN < 1.0
    assert chain_factor_of(0.5) == pytest.approx(_CHAIN_FLOOR + 0.5 * (1 - _CHAIN_FLOOR))


# ---------------------------------------------------------------- 一致性不变量

def test_every_fired_gate_breaks_the_matching_link():
    """不变量：闸对该结论亮了某 kind 的灯 ⇒ 链上对应环必须判为断。"""
    cases = [
        dict(statement="所有客户项目均无延期风险", quote="项目后移两周"),      # scope
        dict(statement="客户B项目不存在回款风险", quote="项目后移两周",
             seg_text="项目后移两周，人员编制稳定"),                          # warrant
        dict(statement="截至2026年3月，回款率40%，缺口768万元",
             quote="项目后移两周", seg_text="项目后移两周，回款正常",
             with_date=True),                                                 # as_of/数字
        dict(statement="因台账缺失导致客户B项目延期", quote="项目后移两周",
             causation=True),                                                 # causation
    ]
    for kwargs in cases:
        d = _dossier(**kwargs)
        from app.core.audit import audit_all

        kinds = {f["kind"] for f in audit_all(d) if f.get("conclusion_id") == "CON1"}
        rep = chain_integrity(d, "CON1")
        for check, mapped in _BROKEN_BY_KIND.items():
            if check in rep.applicable and kinds & mapped:
                assert check in rep.broken, f"{kwargs} 里 {check} 亮了灯却没算断链"


def test_tampered_quote_breaks_the_quote_link():
    """人工/篡改让引文对不上原文 ⇒ quote_hits 断链（与防篡改同一条线）。"""
    d = _dossier()
    d.evidences[0].quote = "项目后移三周"          # 改一个字
    rep = chain_integrity(d, "CON1")
    assert "quote_hits" in rep.applicable
    assert "quote_hits" in rep.broken


def test_declared_scope_repairs_the_scope_link():
    """补上覆盖声明（partial + 局限）后，scope 环不再算断——分数与警示同步。"""
    broken = chain_integrity(_dossier(statement="所有客户项目均无延期风险"), "CON1")
    fixed = chain_integrity(_dossier(
        statement="所有客户项目均无延期风险",
        coverage={"state": "partial", "limitations": ["仅纳入本次 1 份台账"]}), "CON1")
    assert "scope_declared" in broken.broken
    assert "scope_declared" not in fixed.broken


# ---------------------------------------------------------------- 工程接线

def test_recompute_all_matches_per_conclusion_path():
    """批量重算与逐条重算必须同值（链上下文缓存不许引入偏差）。"""
    d = _dossier(statement="所有客户项目均无延期风险")
    recompute_all(d, n_panel=1)
    stored = d.conclusion("CON1").confidence
    fresh, _ = conclude_confidence("CON1", d, n_panel=1)
    assert stored == pytest.approx(fresh)


def test_chain_factor_range_is_bounded():
    """链全断也只压到 _CHAIN_FLOOR，不清零——语义取舍仍归人。"""
    d = _dossier(statement="所有客户项目均不存在延期，回款率40%")
    parts, conf = _chain(d)
    _, base = conclude_confidence("CON1", _dossier(), n_panel=1)
    assert parts["chain"] <= 1.0
    assert conf > 0.0
    assert _CHAIN_FLOOR < _CHAIN_UNKNOWN < 1.0


def test_summarize_counts_unknowns_separately():
    s = summarize_chain([chain_integrity(_dossier(), "CON1"),
                         chain_integrity(_dossier_without_evidence(), "CON1")])
    assert s["n_conclusions"] == 2 and s["n_unknown"] == 1
    assert s["n_broken_checks"] == 0


def test_report_label_names_all_four_components():
    """报告里的分量表述必须四项齐全并说清断在哪一环。"""
    from app.pipeline import confidence_label

    d = _dossier(statement="所有客户项目均无延期风险")
    _, parts = conclude_confidence("CON1", d, n_panel=1)
    label = confidence_label(parts)
    assert "强度" in label and "覆盖" in label and "一致性" in label
    assert "链完整性" in label and "范围有声明" in label


def test_label_survives_legacy_parts_without_chain():
    """存量产物的 confidence_parts 没有 chain 键：渲染不许崩，且要说明是旧口径，
    不能光留一个「—」让评委读成「这条链没问题」。"""
    from app.pipeline import confidence_label

    legacy = {"strength": 0.5, "coverage": 0.6, "agreement": 0.5, "n_evidence": 2}
    text = confidence_label(legacy)
    assert "0.50" in text and "旧口径" in text and "全闭合" not in text
    assert confidence_label({}) == ""


def test_no_evidence_never_renders_as_closed_chain():
    """证据被删空的结论：链分量记「无从判定」，绝不许渲染成「0.00 全闭合」。"""
    from app.pipeline import confidence_label

    _, parts = conclude_confidence("CON1", _dossier_without_evidence(), n_panel=1)
    assert parts["chain"] is None and parts["chain_detail"]["unknown"] is True
    label = confidence_label(parts)
    assert "无从判定" in label and "全闭合" not in label


def test_label_says_how_many_rings_were_actually_checked():
    """只触发一环时不许说「六环全闭合」——分量表述要能对着闸复查。"""
    from app.pipeline import confidence_label

    _, parts = conclude_confidence("CON1", _dossier(), n_panel=1)
    label = confidence_label(parts)
    n = len(parts["chain_detail"]["applicable"])
    assert f"核 {n} 环" in label and "六环" not in label


# ---------------------------------------------------------------- 分母不白送

# 环 → 判它断不断的那道闸（quote_hits 由链自己判，不借闸）
RING_GATE = {"warrant_theme": "warrant_theme", "number_traceable": "provenance",
             "scope_declared": "scope", "as_of_anchored": "as_of",
             "causation_mechanism": "causation_support"}


def test_ring_in_the_denominator_always_has_its_gate_in_scope():
    """不变量：环进了分母 ⇒ 判它的那道闸必须有可核对象。

    违反的后果很具体——闸自报「本次无对象、未执行」，链却把对应环记成闭合，
    等于**用没跑过的检查给分数发满分**（免检当通过的分量版）。存量 34 份产物
    304 条结论实测零矛盾，这里把口径钉成结构约束：新增环时必须同步新增闸的
    准入条件，否则本测试直接红。
    """
    from app.core.gate_applicability import GATE_SPECS

    fixtures = [
        _dossier(),
        _dossier(statement="所有客户项目均无延期风险"),
        _dossier(statement="客户B项目不存在回款风险", quote="项目后移两周",
                 seg_text="项目后移两周，人员编制稳定"),
        _dossier(statement="客户B项目回款率 40%，缺口 768 万元",
                 seg_text="回款率 40%，缺口 768 万元"),
        _dossier(statement="客户B项目里程碑后移两周", with_date=True),
        _dossier(statement="因台账缺失导致项目延期", causation=True),
        _dossier(statement="客户B项目里程碑后移两周", with_date=True,
                 causation=True, coverage={"state": "partial",
                                           "limitations": ["仅 1 份台账"]}),
    ]
    checked = 0
    for d in fixtures:
        spec_by_kind = {s.kind: s for s in GATE_SPECS}
        for con in d.conclusions:
            rep = chain_integrity(d, con.id)
            for ring in rep.applicable:
                kind = RING_GATE.get(ring)
                if kind is None:
                    continue
                checked += 1
                assert spec_by_kind[kind].has_work(d), (
                    f"{ring} 进了分母，但 {kind} 闸自报无对象——白送的闭合环")
    assert checked >= 6          # 覆盖到五条环，防止 fixtures 退化成一堆空案卷


def test_check_order_covers_every_declared_check():
    assert set(CHECK_ORDER) == {"quote_hits", "warrant_theme", "number_traceable",
                                "scope_declared", "as_of_anchored",
                                "causation_mechanism"}
