"""第 2 周协同层：编队并行、归并、冲突检测、质证、仲裁与少数意见。"""

import re
from types import SimpleNamespace

import pytest

from app.agents.arbiter import Coordinator
from app.agents.base import Analyst
from app.agents.panel import DEFAULT_ROSTER, build_panel, run_panel
from app.core.conflicts import (
    ConflictPair,
    Resolution,
    apply_resolution,
    validate_conflict,
)
from app.core.evidence import Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType
from app.pipeline import run_case

PANEL_JSON = """{"conclusions": [
  {"statement": "固态电池2030年前难以在乘用车上规模量产",
   "evidence": [{"quote": "全固态电芯的中试良率尚不足百分之四十",
                 "segment_id": "SRC1#s1", "relation": "correlation",
                 "level": "B", "note": "良率瓶颈"}]},
  {"statement": "固态电池能量密度优势已获装车验证",
   "evidence": [{"quote": "能量密度显著高于传统液态锂离子电池",
                 "segment_id": "SRC1#s1", "relation": "correlation",
                 "level": "A", "note": "直接引证"}]}
]}"""


class ScriptedClient:
    """按脚本队列响应；队列项可为文本、异常或 callable(messages)->str。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "messages": messages,
                           "json_mode": json_mode})
        item = self.responses.pop(0)
        if callable(item):
            item = item(messages)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(content=item)


def _case(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        "question: 固态电池 2030 能否规模上车？\n"
        "sources:\n  - file: a.md\n    type: paper\n", encoding="utf-8")
    (tmp_path / "a.md").write_text(
        "# 摘要\n\n2025 年行业测评显示，半固态电池包的能量密度显著高于传统"
        "液态锂离子电池，头部厂商已在高端车型上小批量装车验证。产线良率是当前"
        "最大瓶颈，全固态电芯的中试良率尚不足百分之四十。\n", encoding="utf-8")


def _dossier_with_two_conclusions() -> Dossier:
    d = Dossier(question="Q")
    src = Source.create("T", SourceType.PAPER, credibility=0.8, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="能量密度显著高于传统液态锂离子电池。全固态电芯的中试良率尚不足百分之四十。",
        locator="段 1"))
    d.add_source(src)
    for i, stmt in enumerate(("结论甲", "结论乙")):
        con = Conclusion.create(stmt, author=f"a{i}", id=f"CON-{i}")
        d.conclusions.append(con)
        d.add_evidence(EvidenceNode.create(
            f"CON-{i}", "全固态电芯的中试良率尚不足百分之四十", ["SRC1#s1"],
            id=f"EV-{i}"))
    return d


def _ids_in(messages) -> list[str]:
    text = messages[-1]["content"]
    return re.findall(r"\[(CON-[0-9a-f]+)\]", text)


# -- 编队并行 ---------------------------------------------------------------


def test_panel_builds_default_three_perspectives():
    panel = build_panel(client=None, model="m")
    assert [a.name for a in panel] == ["mainstream", "redteam", "technologist"]
    assert len({a.persona for a in panel}) == 3  # 视角互异


def test_panel_parallel_all_materialize(tmp_path):
    _case(tmp_path)
    from app.ingest.case_loader import load_case

    dossier = load_case(tmp_path)
    panel = build_panel(client=ScriptedClient([PANEL_JSON] * 3), model="m")
    results = run_panel(dossier, panel)
    assert not results["_failures"]
    assert len(dossier.conclusions) == 6      # 3 分析师 × 2 结论
    assert len(dossier.evidences) == 6
    assert dossier.panel == ["mainstream", "redteam", "technologist"]


def test_panel_single_failure_degrades(tmp_path):
    _case(tmp_path)
    from app.ingest.case_loader import load_case

    dossier = load_case(tmp_path)
    client = ScriptedClient([PANEL_JSON, RuntimeError("429 网关抖动"), PANEL_JSON])
    panel = build_panel(client=client, model="m")
    results = run_panel(dossier, panel)
    assert set(results["_failures"]) == {"redteam"}
    assert len(dossier.conclusions) == 4      # 其余两人照常


def test_run_case_all_analysts_fail_raises(tmp_path):
    _case(tmp_path)
    client = ScriptedClient([RuntimeError("网关全挂")] * 3)
    with pytest.raises(RuntimeError, match="全部分析师研判失败"):
        run_case(tmp_path, out_dir=tmp_path / "out", client=client)


# -- 归并 ---------------------------------------------------------------------


def test_merge_merges_synonyms_and_keeps_provenance():
    d = _dossier_with_two_conclusions()
    # 第三条同义结论（乙的翻版，另一分析师）
    con = Conclusion.create("结论乙的另一种说法", author="a2", id="CON-2")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON-2", "全固态电芯的中试良率尚不足百分之四十",
                                       ["SRC1#s1"], id="EV-2"))
    coord = Coordinator(ScriptedClient([
        '{"groups": [{"statement": "合并后的乙", "member_ids": ["CON-1", "CON-2"]},'
        '             {"statement": "结论甲", "member_ids": ["CON-0"]}]}'
    ]), "m")
    active = coord.merge_conclusions(d, ["CON-0", "CON-1", "CON-2"])
    assert sorted(active) == ["CON-0", sorted(active)[1]]
    group_id = [i for i in active if i != "CON-0"][0]
    group = d.conclusion(group_id)
    assert group.authors == ["a1", "a2"]
    assert len(group.evidence_ids) == 2        # 成员证据全部转挂
    assert d.conclusion("CON-1").status == "merged"
    assert d.evidences_of("CON-1") == []       # 证据已不挂在成员上
    assert {e.conclusion_id for e in d.evidences_of(group_id)} == {group_id}


def test_merge_degrades_to_noop_on_bad_output():
    d = _dossier_with_two_conclusions()
    coord = Coordinator(ScriptedClient(['{"groups": "不是列表"}']), "m")
    active = coord.merge_conclusions(d, ["CON-0", "CON-1"])
    assert sorted(active) == ["CON-0", "CON-1"]  # 降级：全部原样保留
    assert d.conclusion("CON-1").status == "majority"


# -- 冲突检测 / 仲裁 / 少数意见 --------------------------------------------------


def test_detect_conflicts_filters_illegal_pairs():
    d = _dossier_with_two_conclusions()
    coord = Coordinator(ScriptedClient([
        '{"conflicts": ['
        '{"a": "CON-0", "b": "CON-1", "topic": "量产前景", "description": "对立"},'
        '{"a": "CON-0", "b": "CON-0", "topic": "自己对自己", "description": "非法"},'
        '{"a": "CON-0", "b": "CON-9", "topic": "不存在", "description": "非法"}'
        ']}'
    ]), "m")
    pairs = coord.detect_conflicts(d, ["CON-0", "CON-1"])
    assert len(pairs) == 1
    assert (pairs[0].a_id, pairs[0].b_id) == ("CON-0", "CON-1")


def test_arbitrate_and_apply_keeps_dissent():
    d = _dossier_with_two_conclusions()
    pair = ConflictPair(a_id="CON-0", b_id="CON-1", topic="量产前景")
    coord = Coordinator(ScriptedClient([
        '{"winner": "CON-0", "rationale": "甲方证据等级更高且质证击中乙方断章"}'
    ]), "m")
    resolution = coord.arbitrate(d, pair, rebuts={"a": "乙方引文断章", "b": "甲方样本不足"})
    assert resolution.winner_id == "CON-0"
    assert resolution.evidence_weight == {"CON-0": resolution.evidence_weight["CON-0"],
                                          "CON-1": resolution.evidence_weight["CON-1"]}
    pair.resolution = resolution
    assert apply_resolution(pair, d) is None
    assert d.conclusion("CON-1").status == "dissent"          # 败方保留为少数意见
    assert d.conclusion("CON-0").dissent[0]["conclusion_id"] == "CON-1"
    assert d.conclusion("CON-0").dissent[0]["statement"] == "结论乙"


def test_apply_tie_keeps_both_majority():
    d = _dossier_with_two_conclusions()
    pair = ConflictPair(a_id="CON-0", b_id="CON-1",
                        resolution=Resolution(winner_id="tie", method="tie",
                                              rationale="势均力敌"))
    assert apply_resolution(pair, d) is None
    assert d.conclusion("CON-0").status == "majority"
    assert d.conclusion("CON-1").status == "majority"


def test_apply_rejects_illegal_winner():
    d = _dossier_with_two_conclusions()
    pair = ConflictPair(a_id="CON-0", b_id="CON-1",
                        resolution=Resolution(winner_id="CON-9", rationale="x"))
    problems = apply_resolution(pair, d)
    assert problems and "winner 非法" in problems["problems"][0]
    assert d.conclusion("CON-1").status == "majority"  # 簿记未动


def test_arbitrate_failure_leaves_unresolved():
    d = _dossier_with_two_conclusions()
    pair = ConflictPair(a_id="CON-0", b_id="CON-1")
    coord = Coordinator(ScriptedClient([RuntimeError("仲裁超时")]), "m")
    assert coord.arbitrate(d, pair) is None
    assert pair.resolution is None


def test_rebuttal_single_side_failure_degrades():
    d = _dossier_with_two_conclusions()
    pair = ConflictPair(a_id="CON-0", b_id="CON-1")
    coord = Coordinator(ScriptedClient([
        "甲方质证：乙方引文断章", RuntimeError("乙方质证超时"),
    ]), "m", personas={"a0": "怀疑派"})
    rebuts = coord.run_rebuttals(d, pair)
    assert set(rebuts) == {"a"}
    assert "断章" in rebuts["a"]


# -- 端到端（脚本化全流程）------------------------------------------------------


def test_run_case_full_collaboration_pipeline(tmp_path):
    _case(tmp_path)
    merge = lambda messages: '{"groups": [' \
        '{"statement": "良率瓶颈使2030年前难以规模量产", "member_ids": [%s]},' \
        '{"statement": "能量密度优势已获装车验证", "member_ids": [%s]}]}' % (
            ",".join(sorted(_ids_in_dedup(messages, "难以"))),
            ",".join(sorted(_ids_in_dedup(messages, "优势"))))

    def conflict(messages):
        ids = sorted({i for item in messages[-1]["content"].split("\n")
                      for i in re.findall(r"\[(CON-[0-9a-f]+)\]", item)})
        return '{"conflicts": [{"a": "%s", "b": "%s", "topic": "量产前景", ' \
               '"description": "对量产时间表判断对立"}]}' % (ids[0], ids[1])

    def arbitrate(messages):
        a_id = re.search(r"\[(CON-[0-9a-f]+)\]", messages[-1]["content"]).group(1)
        return '{"winner": "%s", "rationale": "甲方证据等级与质证占优"}' % a_id

    client = ScriptedClient(
        [PANEL_JSON] * 3 + [merge, conflict, "甲方质证文本", "乙方质证文本", arbitrate])
    result = run_case(tmp_path, out_dir=tmp_path / "out", client=client)

    # 归并：6 条 → 2 组（每组 3 分析师署名）
    assert len(result.dossier.conflicts) == 1
    pair = ConflictPair.from_dict(result.dossier.conflicts[0])
    assert pair.resolution.winner_id == pair.a_id
    # 败方组降为少数意见，胜方挂 dissent 记录
    losers = [c for c in result.dossier.conclusions if c.status == "dissent"]
    assert losers and losers[0].id == pair.b_id
    events = [r.event for r in result.chain.records]
    assert {"merged", "conflicts_detected", "conflict_resolved"} <= set(events)
    assert result.chain.verify_chain().ok
    md = result.report_md
    assert "分歧识别与消解" in md and "少数意见（依规保留）" in md
    # report.json 可回读且含冲突记录
    from app.core.evidence import Dossier as D
    reloaded = D.from_json(tmp_path / "out" / "report.json")
    assert reloaded.conflicts and reloaded.panel == ["mainstream", "redteam", "technologist"]


def _ids_in_dedup(messages, keyword: str) -> list[str]:
    """从归并提示文本里抽取含关键词语句的结论 id。"""
    out = []
    for line in messages[-1]["content"].split("\n"):
        ids = re.findall(r"\[(CON-[0-9a-f]+)\]", line)
        if ids and keyword in line:
            out.extend(ids)
    return out
