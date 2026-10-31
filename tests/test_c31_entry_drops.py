"""C-31：ingress／repair 的条目级丢弃要留痕，修复环多给的条只计数。"""

from types import SimpleNamespace

import pytest

from app.agents.ingress import ingest_external_judgment
from app.agents.repair import _apply_repair
from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
    record_parse_drop,
)
from app.core.hashchain import HashChain
from app.pipeline import render_report_md

_SEG = "SRC1#s1"
_NOT_OBJECT = "结论条目非法：非对象"
_EMPTY_STMT = "结论条目 statement 为空"


def _dossier() -> Dossier:
    d = Dossier(question="客户回款如何？")
    src = Source.create("账", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id=_SEG, source_id="SRC1", text="客户B累计回款512万元。"))
    d.add_source(src)
    return d


def _mix() -> list:
    return [
        {"statement": "正常结论甲", "evidence": [
            {"segment_id": _SEG, "quote": "累计回款512万元"}]},
        "字符串不是对象",
        {"statement": "   "},
        {"statement": "正常结论乙", "evidence": [
            {"segment_id": _SEG, "quote": "累计回款512万元"}]},
    ]


def _reasons(d: Dossier) -> set[str]:
    return {r["reason"] for r in d.parse_drops}


def test_ingress_records_non_object_and_empty_statement():
    d = _dossier()
    ids = ingest_external_judgment(d, {"agent": "外部", "conclusions": _mix()})
    assert len(ids) == 2
    assert len(d.conclusions) == 2
    assert len(d.parse_drops) >= 2
    assert _reasons(d) >= {_NOT_OBJECT, _EMPTY_STMT}
    assert {r["conclusion_id"] for r in d.parse_drops} == {""}


def test_repair_records_non_object_and_empty_statement():
    d = _dossier()
    con = Conclusion.create("旧表述", author="analyst_a", id="CON-1")
    d.conclusions.append(con)
    _apply_repair(d, con, {"conclusions": _mix()})
    assert con.statement == "正常结论甲"
    assert len(d.conclusions) == 1
    assert len(d.parse_drops) >= 2
    assert _reasons(d) >= {_NOT_OBJECT, _EMPTY_STMT}
    assert {r["conclusion_id"] for r in d.parse_drops
            if r["reason"] in {_NOT_OBJECT, _EMPTY_STMT}} == {""}


def test_five_reasons_are_pairwise_distinct():
    d = _dossier()
    record_parse_drop(d, conclusion_id="C", author="a", ev={}, kind="not_object")
    record_parse_drop(d, conclusion_id="C", author="a", ev={}, kind="missing_id")
    record_parse_drop(
        d, conclusion_id="C", author="a", ev={}, kind="missing_segment",
        segment_id="NOPE")
    record_parse_drop(
        d, conclusion_id="", author="a", ev="x", kind="conclusion_not_object")
    record_parse_drop(
        d, conclusion_id="", author="a", ev={}, kind="conclusion_empty_statement")
    reasons = [r["reason"] for r in d.parse_drops]
    assert len(reasons) == 5
    assert len(set(reasons)) == 5
    assert reasons == [
        "证据条目不是对象（渲染层拿不到）",
        "未给出 segment_id",
        "引用段落不存在（segment_id=NOPE）",
        _NOT_OBJECT,
        _EMPTY_STMT,
    ]


def test_unknown_kind_still_raises():
    with pytest.raises(ValueError):
        record_parse_drop(
            _dossier(), conclusion_id="", author="a", ev={}, kind="no_such_kind")


def _insuff_with_blank_drop(d: Dossier) -> str:
    con = Conclusion.create("资料不足", author="mainstream", id="CON-X")
    con.status = "insufficient"
    d.conclusions.append(con)
    md = render_report_md(d, HashChain(), [])
    assert "成因缺失（异常）" in md
    return md


def test_ingress_blank_id_does_not_satisfy_cause():
    d = _dossier()
    ingest_external_judgment(d, {"agent": "外部", "conclusions": [
        "不是对象", {"statement": "  "},
    ]})
    assert d.parse_drops
    assert all(not r["conclusion_id"] for r in d.parse_drops)
    _insuff_with_blank_drop(d)


def test_repair_blank_id_does_not_satisfy_cause():
    d = _dossier()
    con = Conclusion.create("旧表述", author="analyst_a", id="CON-1")
    d.conclusions.append(con)
    _apply_repair(d, con, {"conclusions": ["不是对象", {"statement": "   "}]})
    assert d.parse_drops
    assert all(not r["conclusion_id"] for r in d.parse_drops)
    _insuff_with_blank_drop(d)


def test_three_normal_rewrites_keep_the_first_and_count_unused():
    d = _dossier()
    con = Conclusion.create("旧表述", author="analyst_a", id="CON-1")
    d.conclusions.append(con)
    ev = EvidenceNode.create(con.id, "累计回款512万元", [_SEG], author="analyst_a")
    d.add_evidence(ev)
    data = {"conclusions": [
        {"statement": "第一条改写", "evidence": [
            {"segment_id": _SEG, "quote": "累计回款512万元"}]},
        {"statement": "第二条改写", "evidence": [
            {"segment_id": _SEG, "quote": "累计回款512万元"}]},
        {"statement": "第三条改写", "evidence": [
            {"segment_id": _SEG, "quote": "累计回款512万元"}]},
    ]}
    unused = _apply_repair(d, con, data)
    assert con.statement == "第一条改写"
    assert "第二条改写" not in con.statement
    assert unused == 2
    assert d.accounting["n_unused"] == 2


def test_entry_drops_do_not_change_official_json(tmp_path):
    from app.export.official import export_official

    d = _dossier()
    con = Conclusion.create("有支撑", author="m", id="CON-1")
    d.conclusions.append(con)
    text = d.sources[0].segments[0].text
    d.add_evidence(EvidenceNode.create(con.id, text[:8], [_SEG], id="EV-1"))
    d.sources[0].meta["doc_id"] = "doc_001"
    runs = [({"question_id": "q1", "question": "Q"}, d)]
    a = export_official(runs, tmp_path / "a")
    record_parse_drop(
        d, conclusion_id="", author="m", ev="x", kind="conclusion_not_object")
    b = export_official(runs, tmp_path / "b")
    for key in ("evidence", "conclusions", "confidence", "conflict_resolution"):
        assert a[key].read_bytes() == b[key].read_bytes()


def test_analyst_empty_event_payload_has_only_error(tmp_path):
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

    class Fixed:
        def __init__(self):
            self.call_log: list = []
            self.total_tokens_used = 0

        def chat(self, *a, **k):
            self.call_log.append(1)
            self.total_tokens_used += 1
            return SimpleNamespace(content=ok)

    class Selective(Analyst):
        def analyze(self, dossier, focus_segment_ids=None):
            if self.name == "technologist":
                from app.agents.base import extract_json
                data = extract_json('{"conclusions":[]}')
                return self._materialize(data, dossier, raw='{"conclusions":[]}')
            return super().analyze(dossier)

    client = Fixed()
    roster = [
        ("mainstream", "主流视角", None),
        ("redteam", "质疑视角", None),
        ("technologist", "技术视角", None),
    ]
    analysts = [Selective(n, p, client, "m") for n, p, _ in roster]
    result = run_case(
        RunSpec(case_dir=case, out_dir=case / "out", probe=False, roster=roster),
        RunDeps(client=client, analysts=analysts),
    )
    events = [r for r in result.chain.records if r.event == "analyst_empty"]
    assert len(events) == 1
    assert set(events[0].payload) == {"error"}
