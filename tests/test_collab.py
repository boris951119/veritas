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
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, Segment, Source, SourceType,
)
from app.pipeline import run_case
from app.pipeline import RunDeps, RunSpec

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


def _analyst_name_from_messages(messages) -> str:
    """从系统提示词首句「你是一名{persona}。」反查 DEFAULT_ROSTER 的 name。"""
    for msg in messages or []:
        if not isinstance(msg, dict) or msg.get("role") != "system":
            continue
        content = str(msg.get("content") or "")
        if not content.startswith("你是一名"):
            continue
        rest = content[len("你是一名"):]
        for name, persona in DEFAULT_ROSTER:
            if rest.startswith(persona + "。"):
                return name
    raise KeyError("无法从 messages 识别分析师身份")


class ScriptedClient:
    """按脚本队列响应；队列项可为文本、异常或 callable(messages)->str。

    by_name 非空时按分析师名各取各的队列（身份只从 messages 认）；
    未传或空则仍走 responses.pop(0)。
    """

    def __init__(self, responses=None, by_name: dict | None = None):
        self.responses = list(responses or [])
        self.by_name = (
            {name: list(queue) for name, queue in by_name.items()}
            if by_name else None
        )
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "messages": messages,
                           "json_mode": json_mode})
        if self.by_name is not None:
            name = _analyst_name_from_messages(messages)
            queue = self.by_name.get(name)
            if not queue:
                raise KeyError(f"分析师 {name!r} 没有剩余脚本响应")
            item = queue.pop(0)
        else:
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
            id=f"EV-{i}",
            level=EvidenceLevel.A if i == 0 else EvidenceLevel.C))
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
    client = ScriptedClient(by_name={
        "mainstream": [PANEL_JSON],
        "redteam": [RuntimeError("429 网关抖动")],
        "technologist": [PANEL_JSON],
    })
    panel = build_panel(client=client, model="m")
    results = run_panel(dossier, panel)
    assert set(results["_failures"]) == {"redteam"}
    assert len(dossier.conclusions) == 4      # 其余两人照常


def test_run_case_all_analysts_fail_raises(tmp_path):
    _case(tmp_path)
    client = ScriptedClient([RuntimeError("网关全挂")] * 3)
    with pytest.raises(RuntimeError, match="全部分析师研判失败"):
        run_case(RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out"),
             RunDeps(client=client))


# -- 归并 ---------------------------------------------------------------------


def test_merge_merges_synonyms_and_keeps_provenance():
    d = _dossier_with_two_conclusions()
    # 第三条同义结论（乙的翻版，另一分析师）。
    # C-145：LLM 归并组要过硬约束闸（同主体×同指标），故组内两条文案带
    # 客户标签＋窄议题维（本测试锁的是溯源／去重机制，不是闸本身）；
    # CON-1 文案只在本格内改写，不动共享夹具（仲裁格钉着「结论乙」）。
    d.conclusion("CON-1").statement = "客户B存在回款风险"
    con = Conclusion.create("客户B的回款存在困难", author="a2", id="CON-2")
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
    # 同引文去重：CON-1 与 CON-2 摘的是同一段原话 → 组内只保留一条
    assert len(group.evidence_ids) == 1
    assert d.conclusion("CON-1").status == "merged"
    # 重复引文留在成员结论上作溯源，不随组重复计数
    assert len(d.evidences_of("CON-2")) == 1
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
    """两组结论挂不同信源、文案语义不同，强度差 >0.20 → 有胜方与少数意见。"""
    (tmp_path / "manifest.yaml").write_text(
        "question: 固态电池 2030 能否规模上车？\n"
        "sources:\n"
        "  - file: density.md\n    type: paper\n"
        "  - file: yield.md\n    type: news\n",
        encoding="utf-8")
    (tmp_path / "density.md").write_text(
        "# 密度\n\n2025 年行业测评显示，半固态电池包的能量密度显著高于传统"
        "液态锂离子电池，头部厂商已在高端车型上小批量装车验证。\n",
        encoding="utf-8")
    (tmp_path / "yield.md").write_text(
        "# 良率\n\n产线良率是当前最大瓶颈，全固态电芯的中试良率尚不足百分之四十，"
        "与能量密度测评不是同一份材料。\n",
        encoding="utf-8")
    panel = """{"conclusions": [
  {"statement": "固态电池2030年前难以在乘用车上规模量产",
   "evidence": [{"quote": "全固态电芯的中试良率尚不足百分之四十",
                 "segment_id": "SRC2#s1", "relation": "correlation",
                 "level": "D", "note": "良率瓶颈"}]},
  {"statement": "固态电池能量密度优势已获装车验证",
   "evidence": [{"quote": "能量密度显著高于传统液态锂离子电池",
                 "segment_id": "SRC1#s1", "relation": "correlation",
                 "level": "A", "note": "直接引证"}]}
]}"""
    merge = lambda messages: '{"groups": [' \
        '{"statement": "良率瓶颈使2030年前难以规模量产", "member_ids": [%s]},' \
        '{"statement": "能量密度优势已获装车验证", "member_ids": [%s]}]}' % (
            ",".join(sorted(_ids_in_dedup(messages, "难以"))),
            ",".join(sorted(_ids_in_dedup(messages, "优势"))))

    def conflict(messages):
        text = messages[-1]["content"]
        weak = re.findall(r"\[(CON-[0-9a-f]+)\].*难以", text)
        strong = re.findall(r"\[(CON-[0-9a-f]+)\].*优势", text)
        return '{"conflicts": [{"a": "%s", "b": "%s", "topic": "量产前景", ' \
               '"description": "对量产时间表判断对立"}]}' % (weak[0], strong[0])

    def arbitrate(messages):
        a_id = re.search(r"\[(CON-[0-9a-f]+)\]", messages[-1]["content"]).group(1)
        return '{"winner": "%s", "rationale": "甲方证据等级与质证占优"}' % a_id

    client = ScriptedClient(
        [panel] * 3 + [merge, conflict, "甲方质证文本", "乙方质证文本", arbitrate])
    result = run_case(RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out"),
             RunDeps(client=client))

    # 归并：6 条 → 2 组。密度组挂论文 A 级、良率组挂新闻 D 级，强度差 >0.20，
    # 破平给出胜方，败方保留为少数意见。tie 形状仍由 test_c 钉住。
    assert len(result.dossier.conflicts) == 1
    pair = ConflictPair.from_dict(result.dossier.conflicts[0])
    assert pair.resolution.winner_id != "tie"
    losers = [c for c in result.dossier.conclusions if c.status == "dissent"]
    assert losers and losers[0].id != pair.resolution.winner_id
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
