"""C-139：树17 引用验收打回循环（机器验收闸）测试。

覆盖：五码触发打回、上限行为（默认 3／硬顶 5）、到顶剪枝＋披露不静默、
关旗零改、无交卷盒不启用、显式 focus（second_pass 形状）不启用、
重写提示只含失败原因＋盒内编号（禁金标 id）、unparsable 可回放。
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from app.core.evidence import Dossier, Segment, Source, SourceType

BOX = ["DOC1#s1", "DOC1#s2", "DOC2#s1"]
PAIRS = {"conflicts": [
    {"support_id": "DOC1#s1", "oppose_id": "DOC1#s2", "preferred": "support"},
]}

GOOD_PAYLOAD = """{"conclusions": [
  {"statement": "官方通报遇难12人",
   "evidence": [{"quote": "事故已造成12人遇难", "segment_id": "DOC1#s1",
                 "relation": "correlation", "level": "B", "note": "通报"}]},
  {"statement": "记者统计为8人",
   "evidence": [{"quote": "遇难人数为8人", "segment_id": "DOC1#s2",
                 "relation": "correlation", "level": "C", "note": "现场"}]}
]}"""

# 只犯一条：引用在卷不在盒（DOC2#s2），quote 与该段逐字一致 → 仅 out_of_box
OUT_ONLY_PAYLOAD = """{"conclusions": [
  {"statement": "带外一条",
   "evidence": [{"quote": "另有说法流传", "segment_id": "DOC2#s2",
                 "relation": "correlation", "level": "C", "note": "带外"}]}
]}"""

# 三码混合：带外 DOC2#s2＋编造 DOC9#s9＋引文对不上 DOC1#s1
BAD_MIXED_PAYLOAD = """{"conclusions": [
  {"statement": "混合问题结论",
   "evidence": [
     {"quote": "另有说法流传", "segment_id": "DOC2#s2",
      "relation": "correlation", "level": "C", "note": "带外"},
     {"quote": "随便一句", "segment_id": "DOC9#s9",
      "relation": "correlation", "level": "D", "note": "编造"},
     {"quote": "这句话原文里完全没有", "segment_id": "DOC1#s1",
      "relation": "correlation", "level": "B", "note": "对不上"}
   ]}
]}"""

ONE_SIDED_PAYLOAD = """{"conclusions": [
  {"statement": "只引 support 侧",
   "evidence": [{"quote": "事故已造成12人遇难", "segment_id": "DOC1#s1",
                 "relation": "correlation", "level": "B"}]}
]}"""


class Scripted:
    """脚本应答桩：按序返回、记录每次调用的 messages。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append([dict(m) for m in messages])
        return SimpleNamespace(content=self.responses.pop(0))


def _dossier() -> Dossier:
    d = Dossier(question="事故遇难人数是多少？")
    src = Source.create("官方通报", SourceType.REPORT, id="DOC1")
    src.segments = [
        Segment(id="DOC1#s1", source_id="DOC1",
                text="官方通报：2026年3月1日，事故已造成12人遇难。"),
        Segment(id="DOC1#s2", source_id="DOC1",
                text="现场记者统计：遇难人数为8人，与官方通报存在出入。"),
    ]
    d.add_source(src)
    src2 = Source.create("评论", SourceType.WEB, id="DOC2")
    src2.segments = [
        Segment(id="DOC2#s1", source_id="DOC2",
                text="评论认为双方数字差异源于统计口径不同。"),
        Segment(id="DOC2#s2", source_id="DOC2", text="盒外段落：另有说法流传。"),
    ]
    d.add_source(src2)
    d.accounting = {
        "kg_submit_active": True,
        "kg_submit": {"rank_order": list(BOX), "k": len(BOX),
                      "conflict_pairs": PAIRS},
        "kg_focus_segment_ids": list(BOX),
    }
    return d


def _analyst(client, **kw):
    from app.agents.base import Analyst
    from app.config import Settings

    return Analyst(name=kw.pop("name", "mainstream"),
                   persona="主流研判分析师", model="m", client=client,
                   settings=Settings(**{"cite_accept": True, **kw}))


def _acc(d: Dossier) -> dict:
    return (d.accounting or {}).get("cite_accept", {}).get("mainstream", {})


# ---------------------------------------------------------------- 启用条件

def test_flag_default_off_and_env(monkeypatch):
    from app.core.tree17_accept import cite_accept_attempts, cite_accept_enabled

    assert cite_accept_enabled(None) is False
    assert cite_accept_enabled(SimpleNamespace(cite_accept=False)) is False
    assert cite_accept_enabled(SimpleNamespace(cite_accept=True)) is True
    monkeypatch.setenv("VERITAS_CITE_ACCEPT", "1")
    assert cite_accept_enabled(None) is True
    monkeypatch.delenv("VERITAS_CITE_ACCEPT_ATTEMPTS", raising=False)
    assert cite_accept_attempts(None) == 3
    assert cite_accept_attempts(SimpleNamespace(cite_accept_attempts=9)) == 5
    assert cite_accept_attempts(SimpleNamespace(cite_accept_attempts=0)) == 3
    monkeypatch.setenv("VERITAS_CITE_ACCEPT_ATTEMPTS", "2")
    assert cite_accept_attempts(None) == 2


def test_gate_off_zero_behavior_change():
    """关旗：坏 payload 原样物化、单次调用、无 accounting 键＝逐字旧路。"""
    from app.agents.base import Analyst
    from app.config import Settings

    d = _dossier()
    client = Scripted([BAD_MIXED_PAYLOAD])
    a = Analyst(name="mainstream", persona="p", model="m", client=client,
                settings=Settings(cite_accept=False))
    a.analyze(d)
    assert len(client.calls) == 1
    assert "cite_accept" not in (d.accounting or {})
    # 带外证据原样进卷（旧行为）
    assert any("DOC2#s2" in (e.segment_ids or []) for e in d.evidences)


def test_gate_noop_without_kg_submit():
    """旗开但无交卷盒（测试树未跑）→ 闸不启用、单次调用。"""
    d = _dossier()
    d.accounting = {}
    client = Scripted([BAD_MIXED_PAYLOAD])
    a = _analyst(client)
    a.analyze(d)
    assert len(client.calls) == 1
    assert "cite_accept" not in (d.accounting or {})


def test_gate_skips_explicit_focus_round():
    """显式 focus（second_pass／multi_box 定向轮形状）→ 闸不在范围。"""
    d = _dossier()
    client = Scripted([BAD_MIXED_PAYLOAD])
    a = _analyst(client)
    a.analyze(d, focus_segment_ids=["DOC1#s1"])
    assert len(client.calls) == 1
    assert "cite_accept" not in (d.accounting or {})


# ---------------------------------------------------------------- 五码打回

def test_out_of_box_retry_then_pass():
    d = _dossier()
    client = Scripted([OUT_ONLY_PAYLOAD, GOOD_PAYLOAD])
    a = _analyst(client)
    cons = a.analyze(d)
    acc = _acc(d)
    assert acc["attempts"] == 2 and acc["final_ok"] is True
    assert acc["attempts_log"][0]["codes"] == ["out_of_box"]
    assert len(client.calls) == 2
    # 通过轮的 payload 才进案卷：带外证据不得残留
    assert all(
        sid != "DOC2#s2"
        for e in d.evidences for sid in (e.segment_ids or []))
    assert len(cons) == 2


def test_five_codes_each_trigger_retry():
    d = _dossier()
    empty = '{"conclusions": []}'
    client = Scripted([empty, BAD_MIXED_PAYLOAD, ONE_SIDED_PAYLOAD,
                       GOOD_PAYLOAD])
    a = _analyst(client, cite_accept_attempts=4)
    a.analyze(d)
    acc = _acc(d)
    assert acc["attempts"] == 4
    assert acc["attempts_log"][0]["codes"] == ["empty_cite"]
    assert set(acc["attempts_log"][1]["codes"]) == {
        "out_of_box", "anchor_miss", "unverifiable", "conflict_one_sided"}
    assert acc["attempts_log"][2]["codes"] == ["conflict_one_sided"]
    assert acc["final_ok"] is True
    assert len(client.calls) == 4


def test_unparsable_is_replayable_code():
    d = _dossier()
    client = Scripted(["不是 JSON 的回复", GOOD_PAYLOAD])
    a = _analyst(client)
    a.analyze(d)
    acc = _acc(d)
    assert acc["attempts_log"][0]["codes"] == ["unparsable"]
    assert acc["final_ok"] is True


# ---------------------------------------------------------------- 上限行为

def test_cap_default_three_prunes_and_discloses():
    d = _dossier()
    client = Scripted([BAD_MIXED_PAYLOAD] * 3)
    a = _analyst(client)
    a.analyze(d)
    acc = _acc(d)
    assert len(client.calls) == 3
    assert acc["attempts"] == 3 and acc["maxed_out"] is True
    assert acc["final_ok"] is False
    assert acc["codes_final"] == ["out_of_box", "anchor_miss",
                                  "unverifiable", "conflict_one_sided"]
    # 独立复核带外＝0（机械剪枝落了）：不靠程序自盖章
    box_set = set(BOX)
    oob = [sid for e in d.evidences
           for sid in (e.segment_ids or []) if sid not in box_set]
    assert oob == []
    # 盒内证据保留、结论未蒸发光（披露面仍在）
    assert d.evidences
    assert d.conclusions


def test_cap_hard_max_five_via_config():
    d = _dossier()
    client = Scripted([BAD_MIXED_PAYLOAD] * 5)
    a = _analyst(client, cite_accept_attempts=9)
    a.analyze(d)
    assert len(client.calls) == 5
    assert _acc(d)["attempts_cap"] == 5


def test_cap_with_unparsable_only_discloses_empty():
    d = _dossier()
    client = Scripted(["垃圾"] * 3)
    a = _analyst(client)
    cons = a.analyze(d)
    acc = _acc(d)
    assert acc["maxed_out"] is True and acc["final_ok"] is False
    assert acc["codes_final"] == ["unparsable"]
    assert cons == [] and d.empty_runs


# ---------------------------------------------------------------- 重写提示卫生

def test_retry_prompt_only_failure_reason_and_box_ids():
    d = _dossier()
    client = Scripted([BAD_MIXED_PAYLOAD, GOOD_PAYLOAD])
    a = _analyst(client)
    a.analyze(d)
    assert len(client.calls) == 2
    base = client.calls[0][1]["content"]
    retry = client.calls[1][1]["content"]
    assert retry.startswith(base)  # 原约束与盒内资料原样保留，只追加
    suffix = retry[len(base):]
    assert "引用验收·打回第 1 次" in suffix
    assert "资料清单不变" in suffix
    # 禁金标 id：追加面里出现的所有编号 ⊆ 盒 ∪ 模型自己引错的编号
    bad = {"DOC2#s2", "DOC9#s9"}
    toks = set(re.findall(r"DOC[\w#]*", suffix))
    assert toks <= set(BOX) | bad


def test_retry_prompt_lists_pair_discipline():
    d = _dossier()
    client = Scripted([ONE_SIDED_PAYLOAD, GOOD_PAYLOAD])
    a = _analyst(client)
    a.analyze(d)
    retry = client.calls[1][1]["content"]
    assert "只引用了一侧" in retry
    assert "support" in retry and "oppose" in retry


def test_first_pass_success_records_attempts_one():
    d = _dossier()
    client = Scripted([GOOD_PAYLOAD])
    a = _analyst(client)
    a.analyze(d)
    acc = _acc(d)
    assert acc["attempts"] == 1 and acc["final_ok"] is True
    assert len(client.calls) == 1


def test_pair_with_side_outside_box_not_enforced():
    """成对一侧不在交卷盒＝引用面不可达：只披露不执行（不触发打回）。"""
    d = _dossier()
    d.accounting["kg_submit"]["conflict_pairs"] = {"conflicts": [
        {"support_id": "DOC1#s1", "oppose_id": "DOC9#out",
         "preferred": "support"}]}
    client = Scripted([GOOD_PAYLOAD])
    a = _analyst(client)
    a.analyze(d)
    acc = _acc(d)
    assert acc["attempts"] == 1 and acc["final_ok"] is True
    assert acc["attempts_log"][0]["unenforceable_pairs_n"] == 1
