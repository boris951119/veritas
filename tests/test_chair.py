"""主席汇总层 + 标注诚实性闸：仲裁汇总的「汇总」半边，与等级/因果虚标防线。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.agents.chair import (
    build_synthesis, render_chair_template, _validate_llm_output,
)
from app.core.confidence import evidence_score
from app.core.conflicts import ConflictPair, Resolution, apply_resolution
from app.core.discourse_check import audit_causation_support, audit_level_consistency
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, RelationKind,
    Segment, Source, SourceType,
)


def _seg(d: Dossier, sid: str, text: str, stype=SourceType.REPORT,
         cred: float | None = None, meta: dict | None = None) -> None:
    src = Source.create(sid, stype, id=sid, meta=meta or {})
    src.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text))
    d.add_source(src)


def _rich_dossier() -> Dossier:
    """两条多数结论（置信度不同）+ 一个已裁决冲突 + 一条少数意见。"""
    d = Dossier(question="客户B的交付风险如何？")
    _seg(d, "SRC1", "客户B回款率40%，回款正常。")
    c1 = Conclusion.create("截至2026年3月，客户B回款率为40%", author="a", id="CON-1")
    c2 = Conclusion.create("客户B存在交付延期风险，延期6天", author="b", id="CON-2")
    d.conclusions += [c1, c2]
    d.add_evidence(EvidenceNode.create("CON-1", "回款率40%", ["SRC1#s1"],
                                       level=EvidenceLevel.B))
    d.add_evidence(EvidenceNode.create("CON-2", "延期6天", ["SRC1#s1"],
                                       level=EvidenceLevel.C))
    c1.confidence, c2.confidence = 0.7, 0.5
    c3 = Conclusion.create("客户B风险可控", author="c", id="CON-3")
    d.conclusions.append(c3)
    d.add_evidence(EvidenceNode.create("CON-3", "回款正常", ["SRC1#s1"]))
    pair = ConflictPair(a_id="CON-2", b_id="CON-3", topic="风险程度")
    pair.resolution = Resolution(winner_id="CON-2", rationale="证据等级占优")
    apply_resolution(pair, d)
    d.conflicts.append(pair.to_dict())
    return d


class Stub:
    def __init__(self, content):
        self.content = content

    def chat(self, model, messages, json_mode=False):
        return SimpleNamespace(content=self.content)


# -- 零 LLM 模板 -----------------------------------------------------------------


def test_template_covers_all_majority_and_discloses_issues():
    d = _rich_dossier()
    s = render_chair_template(d)
    assert {p["con_id"] for p in s["points"]} == {"CON-1", "CON-2"}
    kinds = {o["kind"] for o in s["open_issues"]}
    assert "conflict" in kinds and "dissent" in kinds
    assert s["mode"] == "template"
    # 确定性：两次渲染一致
    assert render_chair_template(d) == s


def test_template_empty_dossier_never_crashes():
    s = render_chair_template(Dossier(question="Q"))
    assert "无多数结论" in s["headline"] and s["points"] == []


# -- LLM 主席 + 四道闸 -------------------------------------------------------------


def test_llm_chair_passes_gates_when_honest():
    d = _rich_dossier()
    data = json.dumps({
        "headline": "客户B交付存在延期风险但回款尚可，整体风险中等",
        "points": [
            {"con_id": "CON-1", "gloss": "回款率40%（截至2026年3月）"},
            {"con_id": "CON-2", "gloss": "存在延期风险，延期6天"}],
        "open_issues": [
            {"kind": "conflict", "ref": d.conflicts[0]["id"],
             "text": "风险程度已裁决，少数意见保留"}]}, ensure_ascii=False)
    synth = build_synthesis(d, Stub(data), "m")
    assert synth["mode"] == "llm"
    assert not any(p["auto"] for p in synth["points"])
    assert len(synth["points"]) == 2


def test_fabricated_number_in_gloss_replaced_by_source_text():
    d = _rich_dossier()
    data = json.dumps({
        "headline": "客户B整体风险高",
        "points": [
            {"con_id": "CON-1", "gloss": "回款率高达95%"},   # 95% 无溯源
            {"con_id": "CON-2", "gloss": "延期6天"}],
        "open_issues": []}, ensure_ascii=False)
    synth = _validate_llm_output(d, json.loads(data))[0]
    point1 = next(p for p in synth["points"] if p["con_id"] == "CON-1")
    assert "95%" not in point1["gloss"]          # 违规概括被原文顶替
    assert "40%" in point1["gloss"]
    assert any("数字无溯源" in n or "原文顶替" in n
               for n in synth["gate_notes"])


def test_omitted_majority_auto_filled_unknown_dropped():
    d = _rich_dossier()
    data = json.dumps({
        "headline": "只提了一条",
        "points": [
            {"con_id": "CON-1", "gloss": "回款率40%"},
            {"con_id": "CON-99", "gloss": "编造的结论编号"}],  # 不存在
        "open_issues": []}, ensure_ascii=False)
    synth = _validate_llm_output(d, json.loads(data))[0]
    ids = {p["con_id"] for p in synth["points"]}
    assert ids == {"CON-1", "CON-2"}              # CON-2 自动补全，CON-99 丢弃
    auto = [p for p in synth["points"] if p["auto"]]
    assert [p["con_id"] for p in auto] == ["CON-2"]


def test_headline_with_untraceable_number_falls_back_to_template():
    d = _rich_dossier()
    data = json.dumps({
        "headline": "客户B有87%的概率违约",          # 87% 无溯源
        "points": [{"con_id": "CON-1", "gloss": "回款率40%"}],
        "open_issues": []}, ensure_ascii=False)
    synth = _validate_llm_output(d, json.loads(data))[0]
    assert "87%" not in synth["headline"]
    assert any("headline" in n for n in synth["gate_notes"])


def test_suppressed_dissent_reinstated():
    """分歧不得抹平：LLM 全略过冲突/少数意见 → 模板补全。"""
    d = _rich_dossier()
    data = json.dumps({
        "headline": "一切正常",
        "points": [{"con_id": "CON-1", "gloss": "回款率40%"}],
        "open_issues": []}, ensure_ascii=False)
    synth = _validate_llm_output(d, json.loads(data))[0]
    kinds = {o["kind"] for o in synth["open_issues"]}
    assert "conflict" in kinds and "dissent" in kinds
    assert any("抹平" in n or "略过" in n for n in synth["gate_notes"])


def test_chair_llm_failure_falls_back_to_template():
    class Boom:
        def chat(self, *a, **kw):
            raise RuntimeError("网关挂了")

    d = _rich_dossier()
    synth = build_synthesis(d, Boom(), "m")
    assert synth["mode"] == "template"
    assert any("失败" in n for n in synth["gate_notes"])


# -- 管线接线 ---------------------------------------------------------------------


def test_pipeline_synthesis_in_chain_report_and_json(tmp_path):
    from app.pipeline import RunDeps, RunSpec, run_case

    case_dir = tmp_path / "cases" / "demo"
    case_dir.mkdir(parents=True)
    (case_dir / "manifest.yaml").write_text(
        "question: 客户B的回款情况如何？\n"
        "sources:\n  - file: a.md\n    type: report\n", encoding="utf-8")
    (case_dir / "a.md").write_text("客户B回款512万元。", encoding="utf-8")

    PANEL = json.dumps({"conclusions": [{
        "statement": "客户B回款512万元",
        "evidence": [{"quote": "客户B回款512万元。", "segment_id": "SRC1#s1",
                      "relation": "correlation", "level": "B", "note": "x"}]}]},
        ensure_ascii=False)

    class Fake:
        def chat(self, model, messages, json_mode=False):
            return SimpleNamespace(content=PANEL)

    result = run_case(RunSpec(case_dir=case_dir, out_dir=case_dir / "out", probe=False),
                      RunDeps(client=Fake()))  # 桩客户端 → 注入路径 → 模板主席
    # analysts 未注入时 build_panel 会用 Fake → 注入 client 判定成立？
    # injected_client 为 True（client 非 None）→ chair 模板
    assert result.dossier.synthesis["mode"] == "template"
    assert "综合研判意见" in result.report_md
    events = {r.event for r in result.chain.records}
    assert "chair_summary" in events
    reloaded = json.loads((case_dir / "out" / "report.json").read_text(
        encoding="utf-8"))
    assert reloaded["synthesis"]["points"]


# -- 标注诚实性闸 ------------------------------------------------------------------


def test_level_consistency_flags_web_source_with_level_a():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "网友爆料某厂资金紧张", SourceType.WEB)
    con = Conclusion.create("某厂资金紧张", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "资金紧张", ["SRC1#s1"],
                                       level=EvidenceLevel.A))
    flags = audit_level_consistency(d)
    assert flags and flags[0]["kind"] == "level_consistency"
    assert "虚标" in flags[0]["detail"]


def test_level_consistency_passes_for_formal_source():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "同行评审论文正文", SourceType.PAPER)
    con = Conclusion.create("结论", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "正文", ["SRC1#s1"],
                                       level=EvidenceLevel.A))
    assert audit_level_consistency(d) == []


def test_causation_support_flags_bare_causation():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "接口缺失。进度滞后。")  # 并列句，无机制词
    con = Conclusion.create("接口缺失致进度滞后", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "接口缺失。进度滞后。", ["SRC1#s1"],
        relation=RelationKind.CAUSATION, note="两者同段出现"))
    flags = audit_causation_support(d)
    assert flags and "按相关计分" in flags[0]["detail"]
    # 计分联动：无机制词的 causation 不享受加成
    assert evidence_score(d.evidences[0], d) == evidence_score(
        EvidenceNode.create("CON1", "接口缺失。进度滞后。", ["SRC1#s1"],
                            note="两者同段出现"), d)


def test_causation_with_mechanism_word_passes():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "接口缺失导致进度滞后。")
    con = Conclusion.create("接口缺失致进度滞后", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "接口缺失导致进度滞后。", ["SRC1#s1"],
        relation=RelationKind.CAUSATION, note="机制明确"))
    assert audit_causation_support(d) == []
