"""C-17：零结论要分得清是哪种零，空 id 留痕不许配上成因。"""

import json
from pathlib import Path
from types import SimpleNamespace

from app.agents.base import Analyst
from app.core.evidence import Conclusion, Dossier, Segment, Source, SourceType
from app.core.hashchain import HashChain
from app.core.panel_attrition import apply_panel_attrition, failures_from_panel_results
from app.pipeline import render_report_md


def _dossier() -> Dossier:
    d = Dossier(question="客户回款如何？")
    src = Source.create("账", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text="客户B累计回款512万元。"))
    d.add_source(src)
    return d


class _One:
    def __init__(self, content: str):
        self.content = content
        self.call_log = []
        self.total_tokens_used = 0

    def chat(self, *a, **k):
        self.call_log.append(1)
        return SimpleNamespace(content=self.content)


def _feed(content: str) -> Dossier:
    d = _dossier()
    Analyst("mainstream", "主流", _One(content), "stub-model").analyze(d)
    return d


_SHAPES = {
    "缺 conclusions 键": '{"answers":["只有句子"]}',
    "元素全非对象": '{"conclusions":["只有句子"]}',
    "元素有对象但 statement 全空": '{"conclusions":[{"statement":"  "}]}',
    "conclusions 空列表": '{"conclusions":[]}',
    "conclusions 非列表": '[{"statement":"顶层数组"}]',
}


def test_five_shapes_leave_five_distinct_marks():
    seen = []
    for expect, content in _SHAPES.items():
        d = _feed(content)
        assert len(d.empty_runs) == 1
        run = d.empty_runs[0]
        assert run["shape"] == expect
        assert run["author"] == "mainstream"
        assert run["model"] == "stub-model"
        assert run["content_chars"] == len(content)
        assert run["head"] == content[:120]
        assert run["tail"] == content[-80:]
        seen.append(run["shape"])
    assert len(set(seen)) == 5


def test_successful_delivery_does_not_open_empty_run():
    content = (
        '{"conclusions":[{"statement":"客户B累计回款512万元",'
        '"evidence":[{"quote":"累计回款512万元","segment_id":"SRC1#s1",'
        '"relation":"correlation","level":"B","note":"回款"}]}]}'
    )
    d = _feed(content)
    assert d.empty_runs == []
    assert len(d.conclusions) == 1


def test_bad_neighbors_do_not_drop_the_valid_conclusion():
    content = (
        '{"conclusions":[{"statement":""},'
        '{"statement":"合法结论一句话","evidence":[]},"字符串"]}'
    )
    d = _feed(content)
    assert [c.statement for c in d.conclusions] == ["合法结论一句话"]
    assert d.empty_runs == []
    assert len(d.parse_drops) == 2
    assert {r["conclusion_id"] for r in d.parse_drops} == {""}
    reasons = {r["reason"] for r in d.parse_drops}
    assert reasons == {"结论条目非法：非对象", "结论条目 statement 为空"}
    assert "未给出 segment_id" not in reasons
    assert not any("引用段落不存在" in r for r in reasons)


def test_blank_conclusion_id_does_not_satisfy_cause():
    d = _dossier()
    con = Conclusion.create("资料不足", author="mainstream", id="CON-X")
    con.status = "insufficient"
    d.conclusions.append(con)
    d.parse_drops.append({
        "conclusion_id": "",
        "author": "mainstream",
        "segment_id": "",
        "quote_head": "",
        "reason": "结论条目 statement 为空",
    })
    d.empty_runs.append({
        "author": "other", "model": "m", "content_chars": 1,
        "top_keys": [], "shape": "conclusions 空列表", "head": "{", "tail": "}",
    })
    md = render_report_md(d, HashChain(), [])
    assert "成因缺失（异常）" in md


def test_excerpt_stays_within_cap_and_off_disk():
    huge = "甲" * 50000
    content = '{"answers":["' + huge + '"]}'
    d = _feed(content)
    run = d.empty_runs[0]
    assert len(run["head"]) + len(run["tail"]) <= 200
    blob = json.dumps(d.to_dict(), ensure_ascii=False)
    assert huge not in blob
    bare = _dossier()
    before = len(json.dumps(bare.to_dict(), ensure_ascii=False))
    assert len(blob) - before <= 200 * 1 + 800


def test_empty_runs_roundtrip_and_old_reports_load_empty(tmp_path):
    d = _feed('{"conclusions":[]}')
    again = Dossier.from_dict(d.to_dict())
    assert again.empty_runs == d.empty_runs
    legacy = d.to_dict()
    legacy.pop("empty_runs")
    assert Dossier.from_dict(legacy).empty_runs == []
    # 自建一份没有 empty_runs 键的旧报告。干净 clone 上 cases/out 是 0 份。
    body = {
        "question": "旧报告没有空交付字段",
        "sources": [],
        "conclusions": [],
        "accounting": {},
    }
    text = json.dumps(body, ensure_ascii=False)
    assert "empty_runs" not in text
    fixture = tmp_path / "report.json"
    fixture.write_text(text, encoding="utf-8")
    assert Dossier.from_json(fixture).empty_runs == []
    loaded = 0
    for path in Path("cases").glob("*/out*/report.json"):
        if "out_offline" in path.parts:
            continue
        loaded += 1
        hist = Dossier.from_json(path)
        assert hist.empty_runs == []
    print(f"historical report.json scanned: {loaded}")


def test_empty_runs_do_not_change_official_json(tmp_path):
    from app.export.official import export_official

    d = _dossier()
    d.conclusions.append(Conclusion.create("有支撑", author="m", id="CON-1"))
    text = d.sources[0].segments[0].text
    from app.core.evidence import EvidenceNode
    d.add_evidence(EvidenceNode.create(
        "CON-1", text[:20], ["SRC1#s1"], id="EV-1"))
    d.sources[0].meta["doc_id"] = "doc_001"
    runs = [({"question_id": "q1", "question": "Q"}, d)]
    a = export_official(runs, tmp_path / "a")
    d.empty_runs.append({
        "author": "m", "model": "x", "content_chars": 3,
        "top_keys": [], "shape": "conclusions 空列表", "head": "{}", "tail": "{}",
    })
    b = export_official(runs, tmp_path / "b")
    for key in ("evidence", "conclusions", "confidence", "conflict_resolution"):
        assert a[key].read_bytes() == b[key].read_bytes()


def test_three_empty_shapes_show_on_the_attrition_line():
    d = _dossier()
    roster = ["a", "b", "c"]
    payloads = [
        ("a", '{"conclusions":[]}'),
        ("b", '{"answers":["x"]}'),
        ("c", '{"conclusions":["只有句子"]}'),
    ]
    for name, content in payloads:
        Analyst(name, "视角", _One(content), "stub-model").analyze(d)
    assert len(d.empty_runs) >= 1
    fails = failures_from_panel_results(roster, {n: [] for n in roster})
    apply_panel_attrition(d, roster, fails)
    md = render_report_md(d, HashChain(), [])
    line = next(x for x in md.splitlines() if x.startswith("**编队减员**"))
    assert "conclusions 空列表" in line
    assert "缺 conclusions 键" in line
    assert "元素全非对象" in line
    assert "空交付明细" in md


_ROSTER = ["sinker", "mainstream", "technologist", "redteam"]


def test_non_list_wording_splits_without_changing_the_ledger():
    """j) 非列表文案带 type=；缺键与 None 仍同句；账的键、条数、短因不动。"""
    from app.core.panel_attrition import _short_reason

    missing = failures_from_panel_results(_ROSTER, {})
    none_val = failures_from_panel_results(
        _ROSTER, {n: None for n in _ROSTER})
    as_dict = failures_from_panel_results(
        _ROSTER, {n: {"conclusions": []} for n in _ROSTER})
    as_str = failures_from_panel_results(
        _ROSTER, {n: "gateway timeout" for n in _ROSTER})
    empty_list = failures_from_panel_results(
        _ROSTER, {n: [] for n in _ROSTER})

    miss_msg = set(missing.values())
    none_msg = set(none_val.values())
    dict_msg = set(as_dict.values())
    str_msg = set(as_str.values())
    assert miss_msg == none_msg and len(miss_msg) == 1
    assert len(dict_msg) == 1 and len(str_msg) == 1
    assert dict_msg != str_msg
    assert dict_msg != miss_msg and str_msg != miss_msg
    assert "type=" in next(iter(dict_msg))
    assert "type=" in next(iter(str_msg))
    for fails in (missing, none_val, as_dict, as_str):
        assert len(fails) == 4
        assert set(fails) == set(_ROSTER)
        assert {_short_reason(v) for v in fails.values()} == {"空交付"}
    assert set(empty_list.values()) == {"empty: 零结论交付"}
    assert len(empty_list) == 4
    assert set(empty_list) == set(_ROSTER)


def test_failed_chain_event_caps_content_head_at_200(tmp_path):
    """l) 链上 analyst_failed 的 content_head 恰为响应前 200 字。"""
    from app.pipeline import RunDeps, RunSpec, run_case

    raw = "这不是 JSON，也没有花括号。" * 60
    assert len(raw) > 200
    case = tmp_path / "cap"
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

    class _Fixed:
        def __init__(self, content: str):
            self.content = content
            self.call_log: list = []
            self.total_tokens_used = 0

        def chat(self, *a, **k):
            self.call_log.append(1)
            self.total_tokens_used += 1
            return SimpleNamespace(content=self.content)

    good = _Fixed(ok)
    bad = _Fixed(raw)
    roster = [
        ("mainstream", "主流视角", None),
        ("redteam", "质疑视角", None),
        ("technologist", "技术视角", None),
    ]
    analysts = [
        Analyst("mainstream", "主流视角", good, "m"),
        Analyst("redteam", "质疑视角", bad, "m"),
        Analyst("technologist", "技术视角", good, "m"),
    ]
    result = run_case(
        RunSpec(case_dir=case, out_dir=case / "out", probe=False, roster=roster),
        RunDeps(client=good, analysts=analysts),
    )
    failed = [r for r in result.chain.records if r.event == "analyst_failed"]
    assert len(failed) == 1
    head = failed[0].payload["content_head"]
    assert head
    assert len(head) == 200
    assert head == raw[:200]


def test_failed_event_keeps_a_content_head():
    from app.agents.panel import run_panel

    raw = "这不是 JSON" + ("。\n" * 40)
    d = _dossier()
    analyst = Analyst("mainstream", "主流", _One(raw), "stub-model")
    results = run_panel(d, [analyst])
    err = results["_failures"]["mainstream"]
    head = str(getattr(analyst, "last_raw", "") or "")[:200]
    assert "JSON" in err or "ValueError" in err
    assert head
    assert len(head) <= 200
    assert raw[:20] in head
