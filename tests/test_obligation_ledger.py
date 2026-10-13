"""完整性判据台账（coverage_gap.obligations / ledger_limitation）的单测。

治的是 2026-10-13 量出来的一个实漏：`subquestion_status` 在切不出 ≥2 个子问时
返回空列表 ⇒ 开放题**没有任何完整性判据**，模型早退量不出来
（存量 34 份产物里 5 份台账为空）。现在四层来源保证非空，且来源偏弱必须留声明。
"""

from app.core.coverage_gap import (
    WEAK_LEDGER_SOURCES,
    ledger_limitation,
    obligations,
    subquestion_status)
from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType)

OPEN_Q = "评估这几个客户项目的交付风险并给出下一步建议"      # 无问号，机械切不开
NARROW_Q = "某制造公司是否已因资金链断裂全面停工？"          # 单个问号 → 旧逻辑返回空
COMPOUND_Q = "各客户项目是否存在延期风险？回款风险呢？"      # 两个问号
THEME_Q = "评估该制造企业的停工与资金链风险"                # 切不开但命中 2 个主题组


def _dossier(question: str, *, synthesis: dict | None = None,
             statements: tuple[str, ...] = ()) -> Dossier:
    d = Dossier(question=question)
    src = Source.create("资料", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(id="SRC1#s0", source_id="SRC1",
                                text="核心人员离职率 20%，回款正常，无停工记录"))
    d.add_source(src)
    d.panel = ["mainstream"]
    for i, st in enumerate(statements):
        d.conclusions.append(Conclusion.create(st, author="mainstream",
                                               id=f"CON{i+1}", confidence=0.2))
        d.add_evidence(EvidenceNode.create(f"CON{i+1}", "核心人员离职率 20%",
                                           ["SRC1#s0"], author="mainstream"))
    d.synthesis = synthesis or {}
    return d


def test_open_question_still_yields_a_ledger():
    """开放题切不出子问也要有判据：整题兜底 1 条，且必须声明判据偏弱。"""
    subs = obligations(_dossier(OPEN_Q))
    assert len(subs) == 1
    assert subs[0]["source"] == "whole_question"
    assert ledger_limitation(subs)
    assert subquestion_status(_dossier(OPEN_Q)) != []


def test_narrow_question_no_longer_has_empty_ledger():
    """旧行为：单问号 → 空台账。现在命中 ≥2 主题组就按主题展开，判据比整题更细。"""
    ledger = subquestion_status(_dossier(NARROW_Q))
    assert len(ledger) == 2
    assert {s["source"] for s in ledger} == {"theme"}
    assert "unanswered" in {s["status"] for s in ledger}   # 资金链那半没答上就亮着
    # 单主题窄题走整题兜底：判据只剩 1 条，但必须声明它弱
    weak = subquestion_status(_dossier("这批设备的保修期到什么时候？"))
    assert len(weak) == 1
    assert weak[0]["source"] == "whole_question"
    assert ledger_limitation(weak)


def test_theme_expansion_when_question_has_multiple_themes():
    """切不开但议题含 ≥2 个主题组 ⇒ 按主题组展开，一组一条义务。"""
    subs = obligations(_dossier(THEME_Q))
    assert len(subs) >= 2
    assert {s["source"] for s in subs} == {"theme"}
    assert "停工" in subs[0]["text"] or "资金链" in subs[0]["text"]


def test_mechanical_subquestions_beat_a_thin_chair_declaration():
    """主席只声明 1 条、议题本可切成 2 条 ⇒ 走子问，不许把判据做薄。"""
    d = _dossier(COMPOUND_Q, synthesis={"obligations": ["只看回款"]})
    subs = obligations(d)
    assert len(subs) == 2
    assert {s["source"] for s in subs} == {"subquestion"}


def test_chair_declaration_wins_when_it_is_specific():
    """主席声明 ≥2 条 ⇒ 优先于机械切分（题意比标点可靠）。"""
    d = _dossier(COMPOUND_Q, synthesis={
        "obligations": ["核实各项目是否延期", "核实回款与坏账敞口"]})
    subs = obligations(d)
    assert len(subs) == 2
    assert {s["source"] for s in subs} == {"chair"}
    assert ledger_limitation(subs) == ""        # 来源可靠 ⇒ 不需要弱化声明


def test_weak_sources_are_the_ones_that_carry_a_limitation():
    """强弱来源分界：主题词/整题兜底必须偏弱，主席与子问不得偏弱。"""
    assert WEAK_LEDGER_SOURCES == {"theme", "whole_question"}
    strong = [{"text": "甲？", "source": "subquestion"},
              {"text": "乙？", "source": "chair"}]
    assert ledger_limitation(strong) == ""
    assert "不表示已审完全部材料" in ledger_limitation(
        [{"text": "停工（议题主题词落点）", "source": "theme"}])


def test_empty_question_is_not_silently_treated_as_complete():
    """没议题就没有判据——但这句声明必须写明「判据不可用」，不许当成审完了。"""
    subs = obligations(_dossier(""))
    assert subs == []
    assert "不可用" in ledger_limitation(subs)


def test_status_classification_still_works_on_the_new_ledger():
    """三态判据没退化：结论触及义务主题 → answered，没触及 → unanswered。"""
    hit = subquestion_status(_dossier(
        COMPOUND_Q, statements=("客户B项目回款正常，未见延期",)))
    assert {s["status"] for s in hit} <= {"answered", "gap"}
    miss = subquestion_status(_dossier(
        COMPOUND_Q, statements=("供应商交付延迟两周",)))
    assert "unanswered" in {s["status"] for s in miss}


# ------------------------------------------------------------------ 出口接线

from types import SimpleNamespace  # noqa: E402

from app.agents.base import Analyst  # noqa: E402
from app.pipeline import RunDeps, RunSpec, run_case  # noqa: E402

_OPEN_Q_NO_MARK = "评估该项目的交付风险并给出下一步建议"   # 无问号、无主题组 → 整题兜底
_FAKE_OUT = ('{"conclusions": [{"statement": "项目存在交付延期风险",'
             '"evidence": [{"quote": "项目里程碑整体后移两周",'
             '"segment_id": "SRC1#s1", "relation": "correlation",'
             '"level": "B", "note": ""}]}]}')


class _FakeClient:
    """鸭子类型桩：只实现 Analyst 用到的 chat。"""

    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, model, messages, json_mode=False):
        return SimpleNamespace(content=self.content)


def _make_open_case(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        f"question: {_OPEN_Q_NO_MARK}\n"
        "sources:\n  - file: a.md\n    type: report\n",
        encoding="utf-8")
    (tmp_path / "a.md").write_text(
        "# 台账\n\n项目里程碑整体后移两周，核心开发人员离职率达 20%。\n",
        encoding="utf-8")


def test_pipeline_end_to_end_declares_weak_ledger_in_report(tmp_path):
    """端到端：开放题走完整管线后，报告必须写出判据条数与弱化声明。

    顺带钉住 accounting 白名单——`obligation_limitation` 不在白名单里会被静默丢掉，
    报告就永远不亮这句（2026-10-13 接线时是个真风险点）。
    """
    import json

    _make_open_case(tmp_path)
    fake = _FakeClient(_FAKE_OUT)
    single = [Analyst("mainstream", "测试角色", fake, "test-model")]
    result = run_case(RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out"),
                      RunDeps(client=fake, analysts=single))

    ledger = result.dossier.accounting.get("subquestion_status") or []
    assert ledger, "开放题必须产生完整性判据"
    assert result.dossier.accounting.get("obligation_limitation")
    assert "完整性判据" in result.report_md
    assert "⚠️" in result.report_md

    saved = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert saved["accounting"].get("obligation_limitation"), "落盘产物必须带这句声明"
