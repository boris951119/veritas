"""刀六：编队减员必须显影。"""

from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.hashchain import HashChain
from app.core.panel_attrition import apply_panel_attrition, panel_attrition_record
from app.pipeline import render_report_md


def test_panel_attrition_note_and_delivered_only():
    d = Dossier(question="q")
    rec = apply_panel_attrition(
        d,
        ["mainstream", "redteam", "technologist"],
        {"redteam": "TimeoutError: litellm.Timeout"},
    )
    assert rec is not None
    assert d.panel == ["mainstream", "technologist"]
    assert "3 人中 1 人未交付" in rec["note"]
    assert "redteam（超时）" in rec["note"]
    assert "一致性分量已封顶" in rec["note"]
    assert rec["agreement_cap"] == round(1 / 3, 4)


def test_no_attrition_when_all_delivered():
    assert panel_attrition_record(["a", "b"], {}) is None


def test_report_renders_attrition_banner():
    d = Dossier(question="客户B回款如何？", title="t")
    src = Source.create("台账", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text="累计回款512万元"))
    d.add_source(src)
    apply_panel_attrition(
        d, ["mainstream", "redteam", "technologist"],
        {"redteam": "litellm.Timeout: timed out"},
    )
    md = render_report_md(d, HashChain(), [])
    assert "**编队减员**" in md
    assert "redteam（超时）" in md
    assert "mainstream" in md and "technologist" in md


def test_pipeline_injects_attrition_on_analyst_timeout(tmp_path):
    from app.agents.base import Analyst
    from app.pipeline import RunDeps, RunSpec, run_case

    case = tmp_path / "pa"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "question: 客户B回款如何？\n"
        "sources:\n  - file: a.md\n    type: report\n",
        encoding="utf-8")
    (case / "a.md").write_text(
        "客户B合同金额1280万元，累计回款512万元。\n", encoding="utf-8")

    ok = (
        '{"conclusions":[{"statement":"客户B累计回款512万元",'
        '"evidence":[{"quote":"累计回款512万元","segment_id":"SRC1#s1",'
        '"relation":"correlation","level":"B","note":"回款"}]}]}'
    )

    class Fixed:
        def __init__(self):
            self.call_log = []
            self.total_tokens_used = 0

        def chat(self, *a, **k):
            from types import SimpleNamespace
            self.call_log.append(1)
            self.total_tokens_used += 5
            return SimpleNamespace(content=ok)

    class FlakyAnalyst(Analyst):
        def analyze(self, dossier):
            if self.name == "redteam":
                raise TimeoutError("simulated timeout")
            return super().analyze(dossier)

    client = Fixed()
    roster = [
        ("mainstream", "主流视角", None),
        ("redteam", "质疑视角", None),
        ("technologist", "技术视角", None),
    ]
    analysts = [FlakyAnalyst(n, p, client, "m") for n, p, _ in roster]
    result = run_case(
        RunSpec(case_dir=case, out_dir=case / "out", probe=False,
                roster=roster),
        RunDeps(client=client, analysts=analysts),
    )
    acc = result.dossier.accounting or {}
    assert acc.get("panel_attrition")
    assert "未交付" in acc["panel_attrition"]["note"]
    assert "redteam" not in result.dossier.panel
    assert "panel_attrition" in {r.event for r in result.chain.records}