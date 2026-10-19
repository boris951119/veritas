"""C-18：主体澄清只在企业题面且标题级机构≥2且题面未点名时早退。"""

import json

from app.core.evidence import Dossier, Segment, Source, SourceType

_JILONG_Q = (
    "吉隆口岸泥石流灾害的起始时刻，应以官方通稿的8月26日10时30分许为准，"
    "还是以监控记录的10时52分至59分为准？"
)
_ENTERPRISE_Q = "2024年半年度归母净利润是多少？"


def _src(title: str, text: str, sid: str) -> Source:
    src = Source.create(title, SourceType.WEB, id=sid)
    src.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text))
    return src


class _Stub:
    def __init__(self):
        self.total_tokens_used = 0

    def chat(self, *a, **k):
        from types import SimpleNamespace
        self.total_tokens_used += 1
        return SimpleNamespace(content='{"conclusions":[]}')


def _run(tmp_path, question: str, sources_spec: list[tuple[str, str]]):
    from app.pipeline import RunDeps, RunSpec, run_case

    case = tmp_path / "case"
    case.mkdir()
    lines = [f"question: {question}", "sources:"]
    for i, (title, text) in enumerate(sources_spec, 1):
        name = f"s{i}.txt"
        lines.append(f"  - file: {name}")
        lines.append("    type: web")
        lines.append(f"    title: {title}")
        (case / name).write_text(text, encoding="utf-8")
    (case / "manifest.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = run_case(
        RunSpec(case_dir=case, out_dir=case / "out", probe=False),
        RunDeps(client=_Stub()),  # type: ignore[arg-type]
    )
    return result


def test_jilong_disaster_question_reaches_analyst(tmp_path):
    """a) 灾害时点之争：多家股份公司只在正文各出现一次，不早退。"""
    from app.core.answer_slots import slot_intent

    d = Dossier(question=_JILONG_Q)
    d.add_source(_src(
        "8·26吉隆口岸泥石流",
        "现场影像由天仪空间科技股份有限公司提供。", "S1"))
    d.add_source(_src(
        "道路抢通进展",
        "西藏天路股份有限公司参与保通。", "S2"))
    intent = slot_intent(d.question, d)
    assert not any("多家股份公司" in t for t in intent["clarify"])
    assert intent["disclosures"]

    result = _run(tmp_path, _JILONG_Q, [
        ("8·26吉隆口岸泥石流", "现场影像由天仪空间科技股份有限公司提供。"),
        ("道路抢通进展", "西藏天路股份有限公司参与保通。"),
    ])
    events = [r.event for r in result.chain.records]
    assert "slot_clarify_early_exit" not in events
    assert "analyst_done" in events


def test_non_enterprise_title_issuers_only_disclosed(tmp_path):
    """a2) 非企业题面 + 两家公司在信源标题：只披露，不早退。"""
    from app.core.answer_slots import slot_intent

    d = Dossier(question=_JILONG_Q)
    d.add_source(_src("天仪空间科技股份有限公司", "现场影像见附件。", "S1"))
    d.add_source(_src("西藏天路股份有限公司", "道路保通见附件。", "S2"))
    intent = slot_intent(d.question, d)
    assert intent["clarify"] == []
    assert any("股份公司" in t for t in intent["disclosures"])

    result = _run(tmp_path, _JILONG_Q, [
        ("天仪空间科技股份有限公司", "现场影像见附件。"),
        ("西藏天路股份有限公司", "道路保通见附件。"),
    ])
    events = [r.event for r in result.chain.records]
    assert "slot_clarify_early_exit" not in events
    assert "analyst_done" in events
    assert any("股份公司" in t
               for t in (result.dossier.accounting.get("slot_disclosures") or []))


def test_enterprise_title_issuers_still_early_exit(tmp_path):
    """b) 企业题面 + 标题级两家 + 题面未点名：仍然澄清、仍然早退。"""
    from app.core.answer_slots import slot_intent

    d = Dossier(question=_ENTERPRISE_Q)
    d.add_source(_src("甲乙丙丁股份有限公司2024年半年度报告", "净利润见合并利润表。", "S1"))
    d.add_source(_src("戊己庚辛股份有限公司2024年半年度报告", "净利润见合并利润表。", "S2"))
    intent = slot_intent(d.question, d)
    assert any("多家股份公司" in t for t in intent["clarify"])

    result = _run(tmp_path, _ENTERPRISE_Q, [
        ("甲乙丙丁股份有限公司2024年半年度报告", "净利润见合并利润表。"),
        ("戊己庚辛股份有限公司2024年半年度报告", "净利润见合并利润表。"),
    ])
    events = [r.event for r in result.chain.records]
    assert "slot_clarify_early_exit" in events
    assert "analyst_done" not in events
    assert result.dossier.accounting.get("n_calls") == 0


def test_enterprise_body_mentions_do_not_early_exit(tmp_path):
    """b2) 企业题面但股份公司只在正文：不早退，披露里留着这条线索。"""
    from app.core.answer_slots import slot_intent

    d = Dossier(question=_ENTERPRISE_Q)
    d.add_source(_src(
        "行业综述",
        "甲乙丙丁股份有限公司与戊己庚辛股份有限公司同期披露净利润。", "S1"))
    intent = slot_intent(d.question, d)
    assert not any("多家股份公司" in t for t in intent["clarify"])
    assert any("股份公司" in t for t in intent["disclosures"])

    result = _run(tmp_path, _ENTERPRISE_Q, [
        ("行业综述", "甲乙丙丁股份有限公司与戊己庚辛股份有限公司同期披露净利润。"),
    ])
    events = [r.event for r in result.chain.records]
    assert "slot_clarify_early_exit" not in events
    assert "analyst_done" in events
    assert any("股份公司" in t
               for t in (result.dossier.accounting.get("slot_disclosures") or []))


def test_early_exit_is_visible_in_official_export(tmp_path):
    """d) 仍然早退的题，字段说明与 omissions 印出未调用分析师。"""
    from app.export.official import export_official

    result = _run(tmp_path, _ENTERPRISE_Q, [
        ("甲乙丙丁股份有限公司2024年半年度报告", "净利润见合并利润表。"),
        ("戊己庚辛股份有限公司2024年半年度报告", "净利润见合并利润表。"),
    ])
    paths = export_official(
        [({"question_id": "q1", "question": _ENTERPRISE_Q}, result.dossier)],
        tmp_path / "sub",
    )
    notes = paths["notes"].read_text(encoding="utf-8")
    payload = json.loads(paths["conflict_resolution"].read_text(encoding="utf-8"))
    line = "本次 1 题因槽位未齐未调用分析师。"
    assert "裸结论闸：" in notes
    assert notes.index("裸结论闸：") < notes.index(line)
    assert line in notes
    assert line in payload["omissions"]
