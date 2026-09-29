"""skill 注册表：闸配对纪律、条件触发、注入与三个新配对闸。"""

from app.core.discourse_check import audit_hedge, audit_level_tone
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, Segment, Source,
    SourceType,
)
from app.core.numeric_check import audit_counting
from app.core.skills import (
    KNOWN_GATES, SKILLS, detect_skills, render_skills_rules, skill_status,
)


def _seg(d: Dossier, source_id: str, text: str, source_type=SourceType.REPORT,
         seg_no: int = 1) -> None:
    src = next((s for s in d.sources if s.id == source_id), None)
    if src is None:
        src = Source.create(source_id, source_type, id=source_id)
        d.add_source(src)
    src.segments.append(Segment(id=f"{source_id}#s{seg_no}",
                                source_id=source_id, text=text))


# -- 注册表纪律 ----------------------------------------------------------------


def test_every_skill_pairs_a_known_gate():
    """无闸的 skill 是许愿：注册表完整性自检。"""
    for s in SKILLS:
        assert s.gate in KNOWN_GATES, s.name
        assert s.rule.strip() and s.description.strip(), s.name
        if not s.enabled:
            assert s.disabled_reason.strip(), s.name


def test_disabled_skills_have_reason():
    disabled = [s for s in SKILLS if not s.enabled]
    assert {s.name for s in disabled} == {"negation_guard", "sic_verbatim"}
    assert all(s.disabled_reason for s in disabled)


# -- 触发器 --------------------------------------------------------------------


def _numeric_dossier() -> Dossier:
    d = Dossier(question="Q")
    _seg(d, "SRC1", "合同金额1,280万元 累计回款512万元 缺口768万元 占比40% 2026年 3月")
    return d


def test_numeric_case_fires_calc_and_provenance_only_relevant():
    fired = {s.name for s in detect_skills(_numeric_dossier())}
    assert {"calc_discipline", "number_provenance", "level_tone"} <= fired
    assert "counting_discipline" not in fired  # 单信源不触发计数
    assert "hedged_claim" not in fired         # 无低可信信源


def test_lowcred_case_fires_hedge():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "网友爆料某厂资金紧张", SourceType.WEB)
    _seg(d, "SRC2", "媒体报道称该厂裁员", SourceType.NEWS)
    fired = {s.name for s in detect_skills(d)}
    assert "hedged_claim" in fired


def test_render_skills_rules_contains_fired_rules_only():
    d = _numeric_dossier()
    rules = render_skills_rules(d)
    assert "计算:a/b=c%" in rules and "专项纪律" in rules
    assert "转述语气" not in rules  # 未触发的 skill 不注入（守提示词预算）


def test_skill_status_reports_full_registry():
    st = {s["name"]: s for s in skill_status(_numeric_dossier())}
    assert st["calc_discipline"]["enabled"] and st["calc_discipline"]["triggered"]
    assert not st["negation_guard"]["enabled"] and st["negation_guard"]["disabled_reason"]
    assert not st["negation_guard"]["triggered"]


# -- 计数闸 ----------------------------------------------------------------------


def test_counting_claim_with_valid_list_passes():
    d = Dossier(question="Q")
    for i in (1, 2, 3):
        _seg(d, f"SRC{i}", f"文档{i}内容", seg_no=1)
    con = Conclusion.create("6份中3份显示风险", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "文档1内容", ["SRC1#s1"],
        note="计数:3/3 信源，见 SRC1、SRC2、SRC3"))
    assert audit_counting(d) == []


def test_counting_claim_with_wrong_numerator_flagged():
    d = Dossier(question="Q")
    for i in (1, 2, 3):
        _seg(d, f"SRC{i}", f"文档{i}内容", seg_no=1)
    con = Conclusion.create("6份中4份显示风险", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "文档1内容", ["SRC1#s1"],
        note="计数:4/3 信源，见 SRC1、SRC2、SRC3"))
    flags = audit_counting(d)
    assert flags and "分子" in flags[0]["detail"]


def test_counting_claim_without_list_flagged():
    d = Dossier(question="Q")
    for i in (1, 2, 3):
        _seg(d, f"SRC{i}", f"文档{i}内容", seg_no=1)
    con = Conclusion.create("6份中3份显示风险", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "文档1内容", ["SRC1#s1"],
                                       note="计数:3/3 信源"))
    flags = audit_counting(d)
    assert flags and "未列出" in flags[0]["detail"]


# -- 转述级闸 ---------------------------------------------------------------------


def test_lowcred_assertive_conclusion_flagged():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "网友爆料某厂资金链紧张", SourceType.WEB)
    con = Conclusion.create("某厂资金链已经断裂", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "资金链紧张", ["SRC1#s1"]))
    flags = audit_hedge(d)
    assert flags and flags[0]["kind"] == "hedge"


def test_lowcred_hedged_conclusion_passes():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "网友爆料某厂资金链紧张", SourceType.WEB)
    con = Conclusion.create("有网友称某厂疑似资金链紧张，未经官方证实",
                            author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "资金链紧张", ["SRC1#s1"]))
    assert audit_hedge(d) == []


def test_credible_source_assertive_conclusion_passes():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "经审计的财报显示回款正常", SourceType.PAPER)
    con = Conclusion.create("某厂回款正常", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "回款正常", ["SRC1#s1"]))
    assert audit_hedge(d) == []


# -- 措辞-等级闸 -------------------------------------------------------------------


def test_weak_evidence_with_assertive_word_flagged():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "博客文章认为该技术必然成功")
    con = Conclusion.create("该技术必然成功", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "必然成功", ["SRC1#s1"],
                                       level=EvidenceLevel.D))
    flags = audit_level_tone(d)
    assert flags and flags[0]["value"] == "必然"


def test_strong_evidence_assertive_word_passes():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "同行评审论文给出确定性结论")
    con = Conclusion.create("该结论确凿", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "确定性结论", ["SRC1#s1"],
                                       level=EvidenceLevel.A))
    assert audit_level_tone(d) == []


# -- 提示词注入 -------------------------------------------------------------------


def test_analyst_prompt_injects_fired_rules():
    """skill 命中 → 分析师系统提示词包含对应纪律；未命中不含。"""
    from app.agents.base import Analyst

    d = _numeric_dossier()
    captured = {}

    class Cap:
        def chat(self, model, messages, json_mode=False):
            captured["system"] = messages[0]["content"]
            return SimpleNamespace(content='{"conclusions": []}')

    from types import SimpleNamespace

    Analyst("m", "测", Cap(), "mod").analyze(d)
    assert "计算:a/b=c%" in captured["system"]
    assert "转述语气" not in captured["system"]
