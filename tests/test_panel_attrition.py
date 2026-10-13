"""刀六：编队减员必须显影（含空交付）；刀十二：署名人数入行。"""

from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
)
from app.core.hashchain import HashChain
from app.core.panel_attrition import (
    apply_panel_attrition,
    author_count_label,
    failures_from_panel_results,
    panel_attrition_record,
)
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


def test_empty_delivery_counts_as_attrition():
    """刀六漏洞：成功返回 [] 也必须显影。"""
    results = {
        "mainstream": [object()],  # 非空即算交付
        "redteam": [],
        "technologist": [],
        "_failures": {},
    }
    fails = failures_from_panel_results(
        ["mainstream", "redteam", "technologist"], results)
    assert "redteam" in fails and "technologist" in fails
    assert "mainstream" not in fails
    assert "空交付" in fails["redteam"] or "零结论" in fails["redteam"]

    d = Dossier(question="q")
    rec = apply_panel_attrition(d, ["mainstream", "redteam", "technologist"], fails)
    assert d.panel == ["mainstream"]
    assert "空交付" in rec["note"]
    assert "technologist（空交付）" in rec["note"]


def test_no_attrition_when_all_delivered():
    assert panel_attrition_record(["a", "b"], {}) is None
    results = {"a": [1], "b": [2], "_failures": {}}
    assert failures_from_panel_results(["a", "b"], results) == {}


def test_report_renders_attrition_banner_and_solo_label():
    d = Dossier(question="客户B回款如何？", title="t")
    src = Source.create("台账", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text="累计回款512万元"))
    d.add_source(src)
    con = Conclusion.create("客户B累计回款512万元", author="mainstream", id="C1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "C1", "累计回款512万元", ["SRC1#s1"], author="mainstream"))
    apply_panel_attrition(
        d, ["mainstream", "redteam", "technologist"],
        {"redteam": "empty: 零结论交付",
         "technologist": "empty: 零结论交付"},
    )
    assert author_count_label(con) == "（仅 1 人署名）"
    md = render_report_md(d, HashChain(), [])
    assert "**编队减员**" in md
    assert "空交付" in md
    assert "technologist" not in md.split("**研判编队**")[1].split("\n")[0]
    assert "mainstream" in md
    assert "仅 1 人署名" in md


def test_knife11_offline_replay_marks_technologist_empty():
    """用 knife11 署名分布复放：technologist 0 条 → 必显影。"""
    from pathlib import Path

    path = Path("cases/bi-delivery-risk/out_local14b_knife11/report.json")
    if not path.exists():
        return  # 无产物时跳过（CI 可无本地 out）
    d = Dossier.from_json(path)
    roster = ["mainstream", "redteam", "technologist"]
    # 按终表署名重建 panel 结果形态（二次定向也算 mainstream 交付）
    by = {n: [] for n in roster}
    for c in d.conclusions:
        for a in c.author_names():
            if a in by:
                by[a].append(c)
    results = {**by, "_failures": {}}
    fails = failures_from_panel_results(roster, results)
    assert "technologist" in fails
    assert "mainstream" not in fails
    rec = apply_panel_attrition(d, roster, fails)
    assert "technologist" not in d.panel
    assert "空交付" in rec["note"]
    md = render_report_md(d, HashChain(), list(d.rejected or []))
    assert "**编队减员**" in md and "technologist（空交付）" in md
    assert "仅 1 人署名" in md


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
        def analyze(self, dossier, focus_segment_ids=None):
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


def test_pipeline_marks_empty_delivery(tmp_path):
    from app.agents.base import Analyst
    from app.pipeline import RunDeps, RunSpec, run_case

    case = tmp_path / "empty"
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
    empty = '{"conclusions":[]}'

    class Fixed:
        def __init__(self):
            self.call_log = []
            self.total_tokens_used = 0
            self._n = 0

        def chat(self, *a, **k):
            from types import SimpleNamespace
            self.call_log.append(1)
            self.total_tokens_used += 5
            # 顺序不保证并行；按 messages 无法区分角色——用 Analyst 覆盖
            return SimpleNamespace(content=ok)

    class Selective(Analyst):
        def analyze(self, dossier, focus_segment_ids=None):
            if self.name == "technologist":
                from app.agents.base import extract_json
                from types import SimpleNamespace
                data = extract_json(empty)
                return self._materialize(data, dossier)
            return super().analyze(dossier)

    client = Fixed()
    roster = [
        ("mainstream", "主流视角", None),
        ("redteam", "质疑视角", None),
        ("technologist", "技术视角", None),
    ]
    analysts = [Selective(n, p, client, "m") for n, p, _ in roster]
    result = run_case(
        RunSpec(case_dir=case, out_dir=case / "out", probe=False,
                roster=roster),
        RunDeps(client=client, analysts=analysts),
    )
    pa = (result.dossier.accounting or {}).get("panel_attrition") or {}
    assert pa, "空交付必须写入 panel_attrition"
    assert "technologist" in (pa.get("failures") or {})
    assert pa["failures"]["technologist"] == "空交付"
    assert "technologist" not in result.dossier.panel
    md = (case / "out" / "report.md").read_text(encoding="utf-8")
    assert "编队减员" in md and "空交付" in md
    assert "仅 1 人署名" in md
