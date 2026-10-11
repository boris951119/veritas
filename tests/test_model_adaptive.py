"""模型画像自适应机制：探测分档 → 强化规则注入 → derived 归一 → 修复环。

用户接什么模型未知——执法（机械闸）模型无关，教（提示词）按探测档位
自适应，不遵从触发定向重写。全部零 key 桩测试。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.agents.base import Analyst
from app.agents.repair import RepairCtx, run_repair_round
from app.core.audit import audit_all
from app.core.evidence import Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType
from app.core.skills import detect_skills, render_skills_rules
from app.llm.profile import probe_model

PROBE_COMPLIANT = json.dumps({"conclusions": [{
    "statement": "有网友称该厂疑似产能过剩",
    "evidence": [{"quote": "产能利用率约65%，较前年下滑两成",
                  "segment_id": "SRC-P#s1", "relation": "correlation",
                  "level": "D",
                  "note": "计算:65/100=65%"}]}]}, ensure_ascii=False)

PROBE_SLOPPY = json.dumps({"conclusions": [{
    "statement": "该厂产能利用率为65%，海外占比25%",
    "evidence": [{"quote": "产能利用率约为六成五",
                  "segment_id": "SRC-P#s1", "relation": "correlation",
                  "level": "D", "note": "产能情况"}]}]}, ensure_ascii=False)


class Fixed:
    """固定回复桩。"""

    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"messages": messages, "json_mode": json_mode})
        return SimpleNamespace(content=self.content)


class Scripted:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"messages": messages, "json_mode": json_mode})
        item = self.responses.pop(0)
        return SimpleNamespace(content=item)


# -- 探测分档 -------------------------------------------------------------------


def test_probe_compliant_tier():
    prof = probe_model(Fixed(PROBE_COMPLIANT), "m1")
    assert prof["tier"] == "compliant"
    assert prof["scores"] == {"citation": True, "calc": True, "hedge": True}


def test_probe_sloppy_model_flagged_noncompliant():
    """改引文 + 无算式 + 无转述：三项全挂 → noncompliant。"""
    prof = probe_model(Fixed(PROBE_SLOPPY), "m1")
    assert prof["tier"] == "noncompliant"
    assert not any(prof["scores"].values())


def test_probe_partial_compliance_two_of_three():
    """含数字但无算式 + 引文被改写 → 仅 hedge 过(1/3) → noncompliant。"""
    sloppy_with_hedge = json.dumps({"conclusions": [{
        "statement": "有网友称该厂疑似海外占比25%",
        "evidence": [{"quote": "产能利用率约为六成五", "segment_id": "SRC-P#s1",
                      "relation": "correlation", "level": "D", "note": "x"}]}]},
        ensure_ascii=False)
    prof = probe_model(Fixed(sloppy_with_hedge), "m1")
    assert prof["tier"] == "noncompliant"
    assert prof["scores"]["hedge"] is True
    assert not prof["scores"]["calc"] and not prof["scores"]["citation"]


def test_probe_clean_statement_exempt_from_calc():
    """无数字陈述不需要算式——诚实的规避不算违规（2/3 → compliant）。"""
    sloppy_with_hedge = json.dumps({"conclusions": [{
        "statement": "有网友称该厂疑似产能过剩",
        "evidence": [{"quote": "产能利用率约为六成五", "segment_id": "SRC-P#s1",
                      "relation": "correlation", "level": "D", "note": "x"}]}]},
        ensure_ascii=False)
    prof = probe_model(Fixed(sloppy_with_hedge), "m1")
    assert prof["tier"] == "compliant"  # hedge+calc豁免过，引文挂 → 2/3


# -- 档位化规则注入 ---------------------------------------------------------------


def _lowcred_dossier() -> Dossier:
    d = Dossier(question="Q")
    src = Source.create("帖子", SourceType.WEB, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1",
                                text="网友称某厂资金紧张 营收1200万元"))
    d.add_source(src)
    return d


def test_standard_tier_keeps_advisory_rules():
    d = _lowcred_dossier()
    rules = render_skills_rules(d, "standard")
    assert "专项纪律" in rules          # level_tone 恒真，建议版注入
    assert "转述标记" not in rules       # 停用 skill 的强化版不注入
    assert "derived" not in rules        # 结构化契约只在 noncompliant 档
    assert "hedged_claim" not in [s.name for s in detect_skills(d, "standard")]


def test_noncompliant_tier_injects_hard_rules_and_derived_contract():
    d = _lowcred_dossier()
    rules = render_skills_rules(d, "noncompliant")
    assert "机械闸" in rules and "derived" in rules
    assert "转述标记" in rules            # 停用 skill 的强化版参与注入
    assert any(s.name == "hedged_claim" for s in detect_skills(d, "noncompliant"))


def test_analyst_uses_tier_for_injection():
    d = _lowcred_dossier()
    cap = Scripted(['{"conclusions": []}'])
    a = Analyst("m", "测", cap, "mod")
    a.profile_tier = "noncompliant"
    a.analyze(d)
    assert "derived" in cap.calls[0]["messages"][0]["content"]
    a.profile_tier = "standard"
    cap2 = Scripted(['{"conclusions": []}'])
    a.client = cap2
    a.analyze(d)
    assert "derived" not in cap2.calls[0]["messages"][0]["content"]


# -- derived 字段机械归一 ---------------------------------------------------------


def test_materialize_normalizes_derived_into_note():
    d = _lowcred_dossier()
    cap = Scripted([json.dumps({"conclusions": [{
        "statement": "海外占比25%",
        "derived": [{"value": "25%", "formula": "300/1200=25%"}],
        "evidence": [{"quote": "其中海外收入300万元", "segment_id": "SRC1#s1",
                      "relation": "correlation", "level": "D", "note": "结构"}]}]},
        ensure_ascii=False)])
    Analyst("m", "测", cap, "mod").analyze(d)
    ev = d.evidences[0]
    assert "计算:300/1200=25%" in ev.note


# -- 修复环 ---------------------------------------------------------------------


def _flagged_dossier() -> tuple[Dossier, Conclusion]:
    d = Dossier(question="客户B的回款情况如何？")
    src = Source.create("台账", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="客户B合同金额1,280万元，累计回款512万元。"))
    d.add_source(src)
    con = Conclusion.create("客户B回款率为45%", author="a0", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "合同金额1,280万元，累计回款512万元", ["SRC1#s1"],
        note="计算:512/1280=45%", author="a0"))
    return d, con


def test_repair_accepts_improved_rewrite():
    from app.core.audit import audit_all

    d, con = _flagged_dossier()
    before = [f for f in audit_all(d) if f.get("conclusion_id") == "CON1"]
    assert before  # 45% 错算 + 来源外
    fixed = json.dumps({"conclusions": [{
        "statement": "客户B回款率为40%",
        "derived": [{"value": "40%", "formula": "512/1280=40%"}],
        "evidence": [{"quote": "合同金额1,280万元，累计回款512万元",
                      "segment_id": "SRC1#s1", "relation": "correlation",
                      "level": "B", "note": "回款率"}]}]}, ensure_ascii=False)
    result = run_repair_round(d, before, RepairCtx(Fixed(fixed), "m", [], 6))
    assert result == {"attempted": 1, "accepted": 1}
    after = [f for f in audit_all(d) if f.get("conclusion_id") == "CON1"]
    assert not after
    assert d.conclusion("CON1").statement == "客户B回款率为40%"


def test_repair_rolls_back_when_not_improved():
    from app.core.audit import audit_all

    d, con = _flagged_dossier()
    before = [f for f in audit_all(d) if f.get("conclusion_id") == "CON1"]
    n_ev_before = len(d.evidences_of("CON1"))
    # 重写仍然错（45% 原样）
    same = json.dumps({"conclusions": [{
        "statement": "客户B回款率为45%",
        "evidence": [{"quote": "合同金额1,280万元，累计回款512万元",
                      "segment_id": "SRC1#s1", "relation": "correlation",
                      "level": "B", "note": "计算:512/1280=45%"}]}]},
        ensure_ascii=False)
    result = run_repair_round(d, before, RepairCtx(Fixed(same), "m", [], 6))
    assert result["accepted"] == 0
    assert d.conclusion("CON1").statement == "客户B回款率为45%"  # 原状回滚
    assert len(d.evidences_of("CON1")) == n_ev_before
    assert [f for f in audit_all(d) if f.get("conclusion_id") == "CON1"]


def test_repair_rolls_back_when_all_new_quotes_fail():
    d, con = _flagged_dossier()
    before = [f for f in audit_all(d) if f.get("conclusion_id") == "CON1"]
    bad = json.dumps({"conclusions": [{
        "statement": "客户B回款率为40%",
        "evidence": [{"quote": "编造的引文不命中", "segment_id": "SRC1#s1",
                      "relation": "correlation", "level": "B", "note": "x"}]}]},
        ensure_ascii=False)
    result = run_repair_round(d, before, RepairCtx(Fixed(bad), "m", [], 6))
    assert result["accepted"] == 0
    assert d.evidences_of("CON1")  # 原证据完整回滚


# -- 管线接线（probe=True 显式开启，桩路径仍确定） --------------------------------


def _case(tmp_path) -> Path:
    case_dir = tmp_path / "cases" / "demo"
    case_dir.mkdir(parents=True)
    (case_dir / "manifest.yaml").write_text(
        "question: 客户B的回款情况如何？\n"
        "sources:\n  - file: a.md\n    type: report\n", encoding="utf-8")
    (case_dir / "a.md").write_text(
        "# 台账\n\n客户B合同金额1,280万元，累计回款512万元。\n", encoding="utf-8")
    return case_dir


PANEL_BAD_CALC = json.dumps({"conclusions": [{
    "statement": "客户B回款率为45%",
    "evidence": [{"quote": "合同金额1,280万元，累计回款512万元",
                  "segment_id": "SRC1#s1", "relation": "correlation",
                  "level": "B", "note": "计算:512/1280=45%"}]}]}, ensure_ascii=False)


def test_force_tier_skips_probe_and_injects_hard_rules(tmp_path, monkeypatch):
    """VERITAS_FORCE_TIER=noncompliant：不探测，链记 forced，提示词带 derived。"""
    from app.config import Settings
    from app.pipeline import RunDeps, RunSpec, run_case

    monkeypatch.setenv("VERITAS_FORCE_TIER", "noncompliant")
    case_dir = _case(tmp_path)
    good = json.dumps({"conclusions": [{
        "statement": "客户B回款率为40%",
        "derived": [{"value": "40%", "formula": "512/1280=40%"}],
        "evidence": [{"quote": "合同金额1,280万元，累计回款512万元",
                      "segment_id": "SRC1#s1", "relation": "correlation",
                      "level": "B", "note": "回款率"}]}]}, ensure_ascii=False)
    client = Scripted([good])  # 强制档：无探测调用
    settings = Settings.from_env()
    assert settings.force_profile_tier == "noncompliant"
    result = run_case(
        RunSpec(case_dir=case_dir, out_dir=case_dir / "out", probe=True,
                settings=settings),
        RunDeps(client=client,
                analysts=[Analyst("mainstream", "测", client, "m")]))
    profiles = [r.payload for r in result.chain.records
                if r.event == "model_profile"]
    assert profiles and profiles[0].get("forced") is True
    assert profiles[0]["tier"] == "noncompliant"
    assert "derived" in client.calls[0]["messages"][0]["content"]
    assert len(client.calls) >= 1
    assert all("SRC-P#s1" not in json.dumps(c["messages"], ensure_ascii=False)
               for c in client.calls)


def test_pipeline_probe_and_repair_round_in_chain(tmp_path):
    from app.pipeline import RunDeps, RunSpec, run_case

    case_dir = _case(tmp_path)
    client = Scripted([
        PROBE_SLOPPY,        # 探测：判 noncompliant
        PANEL_BAD_CALC,      # 分析师：错算输出
        json.dumps({"conclusions": [{         # 修复：改正
            "statement": "客户B回款率为40%",
            "derived": [{"value": "40%", "formula": "512/1280=40%"}],
            "evidence": [{"quote": "合同金额1,280万元，累计回款512万元",
                          "segment_id": "SRC1#s1", "relation": "correlation",
                          "level": "B", "note": "回款率"}]}]}, ensure_ascii=False),
    ])
    result = run_case(RunSpec(case_dir=case_dir, out_dir=case_dir / "out", probe=True),
                      RunDeps(client=client,
                              analysts=[Analyst("mainstream", "测", client, "m")]))
    events = {r.event for r in result.chain.records}
    assert "model_profile" in events and "repair_round" in events
    # 修复后错算红牌消失
    from app.core.audit import audit_all

    assert not [f for f in audit_all(result.dossier)
                if f["kind"] == "calc" and f["conclusion_id"]]
    # 探测出的 noncompliant 档真实影响了提示词（首次分析师调用带 derived 契约）
    analyst_call = client.calls[1]
    assert "derived" in analyst_call["messages"][0]["content"]
    assert result.chain.verify_chain().ok
