"""机械归并闸（app/core/merge_mechanical + arbiter 补一轮）。

治的病：归并判据「语义高度相近」整个交给模型，本地 14B 判得保守 → bi 案例
实测 24 条主流结论**归并 0 组**，客户拿到没去重的清单（同一客户同一话题写三遍），
一致性分量被单署名压死在 1/3。这些测试锁两件事：**该并的并上**（且产生跨人会签、
并要活到 report.json），**判不清的绝不并**（错并比留重复严重得多）。
"""

from types import SimpleNamespace

import pytest

from app.agents.arbiter import Coordinator
from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType)
from app.core.merge_mechanical import enabled, mechanical_groups, merge_key
from tests.test_collab import ScriptedClient


def _dossier() -> Dossier:
    d = Dossier(question="星辰数智各客户项目是否存在延期、回款或人员流失风险？")
    src = Source.create("账目", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="客户C 应收账款计提坏账 43,100 元，质保金尚未到期。"))
    src.segments.append(Segment(
        id="SRC1#s2", source_id="SRC1",
        text="客户B 项目组 6 人劳动合同于 2026-03-05 到期，在岗率 96.8%。"))
    d.add_source(src)
    d.panel = ["mainstream", "technologist"]

    def add(cid, statement, author, quote, seg):
        d.conclusions.append(Conclusion.create(statement, author=author, id=cid))
        d.add_evidence(EvidenceNode.create(cid, quote, [seg], id=f"EV-{cid}"))

    # 该并的一组：同主体 × 同议题 × 同极性，且分属两名分析师
    add("CON-a1", "客户C 项目存在回款风险，因为应收账款账龄超过两年",
        "mainstream", "客户C 应收账款计提坏账 43,100 元", "SRC1#s1")
    add("CON-a2", "客户C 存在回款风险，因为质保金尚未到期",
        "technologist", "质保金尚未到期", "SRC1#s1")
    # 回款风险 ≠ 坏账风险（钱回不来 vs 已确认损失）：同主体同极性也不许并
    add("CON-a3", "客户C 存在坏账风险，因为计提坏账 43,100 元",
        "mainstream", "客户C 应收账款计提坏账 43,100 元", "SRC1#s1")
    # 不该并的四种：跨主体 / 极性正反同现 / 一句谈两议题 / 无主体标签
    add("CON-b1", "客户B 不存在人员流失风险", "mainstream",
        "在岗率 96.8%", "SRC1#s2")
    add("CON-b2", "客户C 不存在人员流失风险", "mainstream",
        "质保金尚未到期", "SRC1#s1")
    add("CON-c1", "客户D 不存在延期，但存在回款风险", "mainstream",
        "质保金尚未到期", "SRC1#s1")
    add("CON-c2", "客户E 存在延期与回款风险", "mainstream",
        "在岗率 96.8%", "SRC1#s2")
    add("CON-c3", "整体来看合作情况尚可", "mainstream",
        "在岗率 96.8%", "SRC1#s2")
    # 无证据挂载：不参与归并（组结论不该替空结论背书）
    d.conclusions.append(Conclusion.create(
        "客户C 存在回款风险，因为应收账款高企", author="mainstream", id="CON-d1"))
    return d


ALL = ["CON-a1", "CON-a2", "CON-a3", "CON-b1", "CON-b2", "CON-c1", "CON-c2",
       "CON-c3", "CON-d1"]
# 无证据挂载的结论在 _is_active 就被出清，进不了归并环节
ACTIVE = [i for i in ALL if i != "CON-d1"]


def test_only_the_mechanically_identical_pair_groups():
    d = _dossier()
    assert mechanical_groups(d, ALL) == [["CON-a1", "CON-a2"]]
    # 五道「不并」逐个锁死
    assert merge_key(d, "CON-a3") != merge_key(d, "CON-a1")  # 回款 ≠ 坏账
    assert merge_key(d, "CON-b1") != merge_key(d, "CON-b2")   # 跨主体
    assert merge_key(d, "CON-c1") is None                     # 极性判不出
    assert merge_key(d, "CON-c2") is None                     # 一句两议题
    assert merge_key(d, "CON-c3") is None                     # 无主体标签
    assert merge_key(d, "CON-d1") is None                     # 无证据


def test_mechanical_merge_produces_cross_author_signoff():
    """LLM 一组合并都没做时，机械闸补上，并真的产生跨分析师会签。"""
    d = _dossier()
    coord = Coordinator(ScriptedClient([
        '{"groups": [' + ",".join(
            '{"statement": "%s", "member_ids": ["%s"]}' % (c, c) for c in ACTIVE)
        + ']}']), "m")
    active = coord.merge_conclusions(d, list(ACTIVE))

    assert len(active) == len(ACTIVE) - 1, "24→20 那类收敛：一组两条并成一条"
    new_ids = [i for i in active if i not in ALL]
    assert len(new_ids) == 1
    group = d.conclusion(new_ids[0])
    assert group.authors == ["mainstream", "technologist"]   # 会签出现
    assert group.confidence_parts == {}                      # 置信度稍后统一算
    assert d.conclusion("CON-a1").status == "merged"
    assert d.conclusion("CON-a1").group_id == group.id       # 守恒闸可回溯
    assert d.conclusion("CON-a2").group_id == group.id
    # 证据转挂到组，成员原证据留痕
    assert {e.conclusion_id for e in d.evidences_of(group.id)} == {group.id}
    rec = d.accounting["mechanical_merge"]
    assert rec["n_mech_groups"] == 1 and rec["n_members_absorbed"] == 2
    assert rec["n_cross_author_groups"] == 1
    assert rec["n_llm_groups"] == 0


def test_mechanical_merge_survives_llm_failure():
    """语义归并挂掉只降级掉那一段，机械闸照常补——不许整段归并消失。"""
    d = _dossier()
    coord = Coordinator(ScriptedClient([RuntimeError("模型超时")]), "m")
    active = coord.merge_conclusions(d, list(ACTIVE))
    assert len(active) == len(ACTIVE) - 1
    assert d.conclusion("CON-a1").status == "merged"


def test_kill_switch_disables_mechanical_merge(monkeypatch):
    monkeypatch.setenv("VERITAS_MECH_MERGE", "0")
    assert enabled() is False
    d = _dossier()
    coord = Coordinator(ScriptedClient([RuntimeError("模型超时")]), "m")
    active = coord.merge_conclusions(d, list(ACTIVE))
    assert sorted(active) == sorted(ACTIVE)      # 一条都没并
    # 停用也要留痕：A/B 对照组得能自证"这轮没开"，而不是查无记录
    assert "停用" in d.accounting["mechanical_merge"]["note"]


def test_early_exit_still_records():
    """活跃结论不足 2 条时也要记账——否则「没跑归并」和「没记录」在产物里长一样。"""
    d = _dossier()
    coord = Coordinator(ScriptedClient([]), "m")
    active = coord.merge_conclusions(d, ["CON-a1"])
    assert active == ["CON-a1"]
    rec = d.accounting["mechanical_merge"]
    assert rec["n_mech_groups"] == 0 and "未进入归并" in rec["note"]


def test_no_merge_when_nothing_is_identical():
    """组内没有重复 → 原样返回，且披露「未触发」而不是不吭声。"""
    d = _dossier()
    subset = ["CON-b1", "CON-b2", "CON-c3"]
    coord = Coordinator(ScriptedClient([
        '{"groups": [{"statement": "x", "member_ids": ["CON-b1"]},'
        '             {"statement": "y", "member_ids": ["CON-b2"]},'
        '             {"statement": "z", "member_ids": ["CON-c3"]}]}']), "m")
    active = coord.merge_conclusions(d, subset)
    assert sorted(active) == sorted(subset)
    assert d.accounting["mechanical_merge"]["n_mech_groups"] == 0
    assert "未触发" in d.accounting["mechanical_merge"]["note"]


if __name__ == "__main__":
    pytest.main([__file__, "-q"])


# -------------------------------------------------- 管线级接缝（产物里必须看得见）

A_JSON = '{"conclusions": [{"statement": "客户C 项目存在回款风险，因为应收账款账龄超过两年",' \
         '"evidence": [{"quote": "应收账款账龄超过两年", "segment_id": "SRC1#s1",' \
         '"relation": "correlation", "level": "A", "note": ""}]}]}'
B_JSON = '{"conclusions": [{"statement": "客户C 存在回款风险，因为质保金尚未到期",' \
         '"evidence": [{"quote": "质保金尚未到期", "segment_id": "SRC1#s1",' \
         '"relation": "correlation", "level": "B", "note": ""}]}]}'


class RoleClient:
    """按调用方给桩响应：两名分析师各交一条同主体同议题结论，归并与冲突段空转。"""

    def __init__(self):
        self.n_analyst = 0

    def chat(self, model, messages, json_mode=False):
        sys = str(messages[0].get("content", ""))
        if "协调员" in sys:
            return SimpleNamespace(content='{"groups": []}')      # 语义归并一组都不合
        if "分歧审查员" in sys or "冲突" in sys:
            return SimpleNamespace(content='{"conflicts": []}')
        self.n_analyst += 1
        return SimpleNamespace(content=A_JSON if self.n_analyst == 1 else B_JSON)


def _case(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        "question: 星辰数智各客户项目是否存在回款或坏账风险？\n"
        "sources:\n  - file: c.md\n    type: report\n", encoding="utf-8")
    (tmp_path / "c.md").write_text(
        "# 账目\n\n截至2025年3月31日，客户C 应收账款账龄超过两年，质保金尚未到期。\n",
        encoding="utf-8")


def test_pipeline_persists_merge_record(tmp_path):
    """机械归并必须活到 report.json：管线收尾按白名单挑账本键，漏挑就等于没做。"""
    import json

    from app.agents.base import Analyst
    from app.pipeline import RunDeps, RunSpec, run_case

    _case(tmp_path)
    client = RoleClient()
    analysts = [Analyst("mainstream", "主流视角", client, "m"),
                Analyst("technologist", "技术视角", client, "m")]
    result = run_case(RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out"),
                      RunDeps(client=client, analysts=analysts))

    rec = json.loads(
        (tmp_path / "out" / "report.json").read_text(encoding="utf-8")
    )["accounting"]["mechanical_merge"]
    assert rec["n_mech_groups"] == 1 and rec["n_cross_author_groups"] == 1

    group = [c for c in result.dossier.conclusions
             if c.status == "majority" and len(c.authors) >= 2]
    assert len(group) == 1, "两条同主体同议题结论应并成一条两人会签"
    assert group[0].confidence_parts["n_authors"] == 2
    assert group[0].confidence > 0.3, "会签后一致性分量应把置信度抬出单署名区间"
