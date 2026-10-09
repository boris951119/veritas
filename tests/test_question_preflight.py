"""议题预检与澄清协议：表述质量分级 / 机械回读 / MCP needs_clarification。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.core.audit import audit_all
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.question_check import (
    question_flag, question_preflight, readback_line,
)
from app.core.skills import detect_skills


def _d(question: str) -> Dossier:
    d = Dossier(question=question)
    src = Source.create("T", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1",
                                text="客户B回款率40%。"))
    d.add_source(src)
    return d


# -- 五级分级 ---------------------------------------------------------------------


def test_clear_question_with_entities_and_date():
    pf = question_preflight("客户B在2026年3月的回款率是多少？")
    assert pf["tier"] == "clear"
    assert "客户B" in pf["entities"] or any("客户" in e for e in pf["entities"])
    assert any("2026" in x for x in pf["dates"])
    assert question_flag(pf and "客户B在2026年3月的回款率是多少？") is None


def test_vague_question_flagged():
    pf = question_preflight("对行业整体情况做个分析吧")
    assert pf["tier"] == "vague"
    assert pf["clarify"] and "分析对象" in pf["clarify"][0]


def test_empty_question():
    assert question_preflight("嗯").get("tier") == "empty"
    assert question_preflight("").get("tier") == "empty"


def test_ambiguous_pronoun_flagged():
    pf = question_preflight("他的交付风险怎么样")
    assert pf["tier"] == "ambiguous"
    assert any("指代" in s for s in pf["signals"])


def test_compound_question_detected():
    pf = question_preflight("客户B回款率怎么样？交付进度又怎么样？")
    assert pf["tier"] == "compound"
    pf2 = question_preflight("客户B的回款、交付和风险分别评估一下")
    assert pf2["tier"] == "compound"


def test_determinism():
    q = "客户B的整体情况怎么样，另外交付进度和回款也说说"
    assert question_preflight(q) == question_preflight(q)


# -- 回读与闸 ---------------------------------------------------------------------


def test_readback_line_shows_elements_not_rewrite():
    line = readback_line("客户B在2026年3月的回款率是多少？")
    assert "对象" in line and "时点" in line and "客户B" in line
    assert "原文照录" in line          # 不改写，只确认


def test_metric_without_period_enters_clarify_and_readback():
    pf = question_preflight("公司归母净利润是多少？")
    assert any("未锁定会计期间" in c for c in pf["clarify"])
    assert pf["readback"]["指标"]
    assert not pf["readback"]["期间"]
    line = readback_line("公司归母净利润是多少？")
    assert "指标" in line and "归属于上市公司股东的净利润" in line


def test_audit_flags_non_clear_question():
    flags = audit_all(_d("对行业整体情况做个分析吧"))
    assert any(f["kind"] == "question" for f in flags)
    assert not any(f["kind"] == "question" for f in audit_all(
        _d("客户B的回款率是多少？")))


# -- 纪律 skill 触发 ----------------------------------------------------------------


def test_question_skills_fire_by_tier():
    assert "question_focus" in {s.name for s in detect_skills(_d("对行业整体情况做个分析吧"))}
    assert "question_scoped" in {s.name for s in detect_skills(
        _d("客户B回款率怎么样？交付进度又怎么样？"))}
    fired = {s.name for s in detect_skills(_d("客户B的回款率是多少？"))}
    assert "question_focus" not in fired and "question_scoped" not in fired


# -- 主席层歧义框定 + 报告渲染 ---------------------------------------------------------


def test_chair_template_frames_non_clear_question():
    from app.agents.chair import render_chair_template

    d = _d("对行业整体情况做个分析吧")
    issues = render_chair_template(d)["open_issues"]
    assert any(o["kind"] == "question" and "原文照录" in o["text"]
               for o in issues)


def test_report_renders_preflight_section(tmp_path):
    from app.core.hashchain import HashChain
    from app.pipeline import render_report_md

    md = render_report_md(_d("分析一下这个行业"), HashChain(), [])
    assert "议题体检" in md and "澄清建议" in md and "研判议题确认" in md
    md2 = render_report_md(_d("客户B的回款率是多少？"), HashChain(), [])
    assert "议题体检（清晰）" in md2


# -- MCP 校验与澄清协议 ---------------------------------------------------------------


def test_mcp_question_validation_and_preflight(tmp_path):
    from app.mcp_server import _attach_preflight, _validate_question

    assert _validate_question("") == {"error": "question 不能为空"}
    assert "过长" in _validate_question("长" * 501)["error"]
    assert _validate_question("客户B的回款率？") is None
    result = _attach_preflight("对行业整体情况做个分析吧", {"ok": True})
    pf = result["preflight"]
    assert pf["tier"] == "vague" and pf["needs_clarification"]
    assert "2 轮" in pf["protocol"]
