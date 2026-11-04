"""C-147：多轮质证（真对立＋同主体跨表述进 2..N 轮对打）——守护格。

默认开（未设 env）＝真对立对强制进 ≥2 轮对打、逐轮过引文逐字＋引用存在性
闸（未过打回一稿）、逐轮留痕进 accounting["rebuttal"] 并折进
conflict_trace.json 顶层 rebuttal 节；oral_misread／date_offset 轻标不进。
env VERITAS_MULTI_REBUTTAL=0 ＝与改前逐字节同形（accounting 无键、单轮
旧路、仲裁输入不变）。仲裁公式／证据强度一行不动（冲突数值线 STOP）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.agents.arbiter import Coordinator
from app.core.conflicts import ConflictPair, Resolution
from app.core.discourse_check import audit_discourse
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceNode,
    Segment,
    Source,
    SourceType,
)
from app.core.rebuttal_rounds import (
    ACCOUNTING_KEY,
    escalation_for,
    joined_rebuts,
    multiround_enabled,
    rounds_requested,
    write_accounting,
)
from app.export.official import export_official
from app.pipeline import RunDeps, RunSpec, run_case
from tests.test_collab import ScriptedClient
from tests.test_c143_trace_report_face import (
    _case_dir, _dossier_with_numbers,
)


# ------------------------------------------------ 夹具


def _pair_dossier() -> Dossier:
    """同主体极性对立的一对结论（true_oppose 构造件）＋在卷信源段。"""
    d = Dossier(question="客户B的回款情况如何？")
    src = Source.create("回款纪要", SourceType.NEWS, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="客户B的回款出现逾期，现金流承压，公司已启动催收。",
        index=0))
    d.sources.append(src)
    ca = Conclusion.create("客户B存在回款风险", author="a0")
    cb = Conclusion.create("客户B不存在回款风险", author="a1")
    d.conclusions.extend([ca, cb])
    d.add_evidence(EvidenceNode.create(
        ca.id, "客户B的回款出现逾期", ["SRC1#s1"]))
    d.add_evidence(EvidenceNode.create(
        cb.id, "客户B的回款出现逾期", ["SRC1#s1"]))
    return d, ConflictPair(a_id=ca.id, b_id=cb.id, topic="回款风险")


_CLEAN_A1 = "对方证据等级存疑，未触及回款合同原件，主张不成立。"
_CLEAN_B1 = "对方未见付款凭证，逾期事实另有口径，应按合同原文核对。"
_CLEAN_A2 = "坚持原判：对方仅重申口径，未举出反证文件。"
_CLEAN_B2 = "补充口径：以催收记录为准，不能仅凭单方说法定性。"
_REBUTTAL_HEAD = "你原本以"


# ------------------------------------------------ 开关与轮数


def test_a_default_on_and_env_off(monkeypatch):
    """默认开＝True／轮数 (2,'')；env=0 全关；轮数夹取 [2,6] 有说明。"""
    monkeypatch.delenv("VERITAS_MULTI_REBUTTAL", raising=False)
    monkeypatch.delenv("VERITAS_REBUTTAL_ROUNDS", raising=False)
    assert multiround_enabled() is True
    assert rounds_requested() == (2, "")
    monkeypatch.setenv("VERITAS_MULTI_REBUTTAL", "0")
    assert multiround_enabled() is False
    monkeypatch.setenv("VERITAS_MULTI_REBUTTAL", "1")
    monkeypatch.setenv("VERITAS_REBUTTAL_ROUNDS", "5")
    assert rounds_requested() == (5, "")
    monkeypatch.setenv("VERITAS_REBUTTAL_ROUNDS", "99")
    val, note = rounds_requested()
    assert val == 6 and "超上限" in note
    monkeypatch.setenv("VERITAS_REBUTTAL_ROUNDS", "1")
    val, note = rounds_requested()
    assert val == 2 and "低于下限" in note


# ------------------------------------------------ 分流路由（四腿）


def test_d_escalation_routes_four_legs():
    d, _ = _pair_dossier()
    pos = d.conclusions[0]
    neg = d.conclusions[1]
    # ① 真对立（极性表机械可证）→ 强制进
    esc = escalation_for(ConflictPair(a_id=pos.id, b_id=neg.id), d)
    assert esc["escalate"] and esc["triage_class"] == "true_oppose"
    assert esc["escalation_reason"] == "true_oppose_forced"
    assert esc["semantic_upgrade"] is False
    # ② 逐字同句 → oral_misread 不进（轻标）
    same = Conclusion.create("客户B存在回款风险", author="a2")
    d.conclusions.append(same)
    esc2 = escalation_for(ConflictPair(a_id=pos.id, b_id=same.id), d)
    assert not esc2["escalate"]
    assert esc2["triage_class"] == "oral_misread"
    assert esc2["escalation_reason"] == "class_not_escalated:oral_misread"
    # ③ other＋同主体标签 → 语义侧吃进（跨表述对立）
    s1 = Conclusion.create("客户B回款进展平稳", author="a0")
    s2 = Conclusion.create("客户B回款节奏需要关注", author="a1")
    d.conclusions.extend([s1, s2])
    esc3 = escalation_for(ConflictPair(a_id=s1.id, b_id=s2.id), d)
    assert esc3["escalate"] and esc3["triage_class"] == "other"
    assert esc3["semantic_upgrade"] is True
    assert esc3["escalation_reason"] == "semantics_eat_other_same_subject"
    # ④ other＋无主体标签 → 不进
    t1 = Conclusion.create("整体局面平稳", author="a0")
    t2 = Conclusion.create("整体局面存在变数", author="a1")
    d.conclusions.extend([t1, t2])
    esc4 = escalation_for(ConflictPair(a_id=t1.id, b_id=t2.id), d)
    assert not esc4["escalate"] and esc4["triage_class"] == "other"
    assert esc4["escalation_reason"] == "other_subject_unknown"


# ------------------------------------------------ 多轮对打＋逐轮闸＋打回


def test_b_multiround_flow_and_reply_template():
    d, pair = _pair_dossier()
    client = ScriptedClient(
        [_CLEAN_A1, _CLEAN_B1, _CLEAN_A2, _CLEAN_B2])
    coord = Coordinator(client, "m", personas={"a0": "怀疑派", "a1": "核查派"})
    rebuts, rows = coord.run_rebuttals_multiround(d, pair, rounds=2)
    assert len(rows) == 4, "2 轮 × 2 侧＝4 条逐轮行"
    assert [r["round"] for r in rows] == [1, 1, 2, 2]
    assert [r["side"] for r in rows] == ["a", "b", "a", "b"]
    assert all(r["gate_ok"] for r in rows)
    assert all(not r["repaired"] for r in rows)
    assert set(rebuts) == {"a", "b"}
    assert "第1轮：" in rebuts["a"] and "第2轮：" in rebuts["a"]
    # 第 2 轮提示词看得到对方上一轮（REBUTTAL_REPLY_TEMPLATE）
    rebut_calls = [c for c in client.calls
                   if c["messages"][0]["content"].startswith(_REBUTTAL_HEAD)]
    assert len(rebut_calls) == 4
    round2 = [c for c in rebut_calls if "质证第 2 轮" in c["messages"][0]["content"]]
    assert len(round2) == 2
    assert all("对方上一轮质证" in c["messages"][0]["content"] for c in round2)
    # Resolution.rebuts 形状不变（{side: str}）——audit_discourse 可直接扫
    assert isinstance(rebuts["a"], str)


def test_c_round_gate_bites_and_repairs_once():
    d, pair = _pair_dossier()
    bad = ("对方在 CON-9999 里引述「客户B已全额付清所有款项」，与原文矛盾。")
    client = ScriptedClient([bad, _CLEAN_A1, _CLEAN_B1, _CLEAN_A2, _CLEAN_B2])
    coord = Coordinator(client, "m", personas={"a0": "怀疑派", "a1": "核查派"})
    rebuts, rows = coord.run_rebuttals_multiround(d, pair, rounds=2)
    a_r1 = next(r for r in rows if r["side"] == "a" and r["round"] == 1)
    assert a_r1["repaired"] is True, "第一稿未过闸必须打回一稿"
    assert a_r1["gate_ok"] is True, "打回稿过了闸＝收下"
    # 引文闸＋引用存在性闸都咬到了坏稿（client.calls 里能对上第一稿）
    first_bad = client.calls[0]["messages"][0]["content"]
    assert "CON-9999" not in first_bad  # 坏稿在模型侧，不在提示词侧
    from app.core.discourse_check import rebuttal_text_flags
    flags = rebuttal_text_flags(d, bad, conflict_id=pair.id, side="a")
    kinds = {f["kind"] for f in flags}
    assert {"rebut_quote", "rebut_ref"} <= kinds, "两道闸都要咬到"
    # 打回提示词带了闸旗原文
    repair_calls = [c for c in client.calls
                    if "上一稿未过机械闸" in c["messages"][0]["content"]]
    assert len(repair_calls) == 1
    assert "CON-9999" in repair_calls[0]["messages"][0]["content"]


def test_c2_audit_discourse_scans_joined_multiround_text():
    d, pair = _pair_dossier()
    bad_round = "第1轮：" + _CLEAN_A1 + "；第2轮：见「客户B已全额付清所有款项」。"
    pair.resolution = Resolution(
        winner_id=pair.a_id, method="arbitration", rationale="r",
        evidence_weight={}, rebuts={"a": bad_round, "b": _CLEAN_B2})
    d.conflicts.append(pair.to_dict())
    flags = audit_discourse(d)
    assert any(f["kind"] == "rebut_quote" and f["side"] == "a" for f in flags), \
        "事后黄旗必须照扫多轮拼接文本"


# ------------------------------------------------ 管线接线（默认开／关）


def _deps_full(client, panels=None):
    """三分析师各自独立 client（panel 并行抢共享队列＝跨进程不定）；
    协调段（归并／判读／质证／仲裁）走传入的共享 client（串行）。"""
    from app.agents.base import Analyst
    from app.agents.panel import DEFAULT_ROSTER
    panels = panels or (_PANEL_POS, _PANEL_NEG, _PANEL_EMPTY)
    analysts = [
        Analyst(name, persona, ScriptedClient([resp]), "m")
        for (name, persona), resp in zip(DEFAULT_ROSTER, panels)]
    return RunDeps(client=client, analysts=analysts)


def _two_ids(text: str) -> tuple[str, str]:
    pos = neg = None
    for cid, stmt in re.findall(
            r"\[(CON-[0-9a-f]+)\]（[^）]*）([^\n]+)", text):
        if "不存在" in stmt:
            neg = cid
        elif "存在回款风险" in stmt:
            pos = cid
    assert pos and neg, f"夹具自证失败：{text[:200]}"
    return pos, neg


def _case_tree(tmp_path: Path) -> None:
    (tmp_path / "manifest.yaml").write_text(
        "question: 客户B的回款情况如何？\n"
        "sources:\n  - file: reb.md\n    type: news\n", encoding="utf-8")
    (tmp_path / "reb.md").write_text(
        "# 回款\n\n客户B的回款出现逾期，现金流承压，公司已启动催收。\n",
        encoding="utf-8")


_PANEL_POS = json.dumps({"conclusions": [{
    "statement": "客户B存在回款风险",
    "evidence": [{"quote": "客户B的回款出现逾期", "segment_id": "SRC1#s1",
                  "relation": "correlation", "level": "A",
                  "note": "直接引证"}]}]}, ensure_ascii=False)
_PANEL_NEG = json.dumps({"conclusions": [{
    "statement": "客户B不存在回款风险",
    "evidence": [{"quote": "客户B的回款出现逾期", "segment_id": "SRC1#s1",
                  "relation": "correlation", "level": "D",
                  "note": "同段反读"}]}]}, ensure_ascii=False)
# 默认编队三人（mainstream／redteam／technologist）：第三位空交付
_PANEL_EMPTY = '{"conclusions": []}'
_EDGES_EMPTY = '{"edges": []}'


def _merge_resp(messages) -> str:
    pos, neg = _two_ids(messages[-1]["content"])
    return ('{"groups": [{"statement": "客户B存在回款风险", '
            '"member_ids": ["%s"]}, {"statement": "客户B不存在回款风险", '
            '"member_ids": ["%s"]}]}' % (pos, neg))


def _conflict_resp(messages) -> str:
    pos, neg = _two_ids(messages[-1]["content"])
    return ('{"conflicts": [{"a": "%s", "b": "%s", "topic": "回款风险", '
            '"description": "对回款状态判断对立"}]}' % (pos, neg))


def _arbitrate_resp(messages) -> str:
    a_id = re.search(r"\[(CON-[0-9a-f]+)\]",
                     messages[-1]["content"]).group(1)
    return '{"winner": "%s", "rationale": "甲方证据等级占优"}' % a_id


def test_e_pipeline_default_on_multiround(monkeypatch, tmp_path):
    monkeypatch.delenv("VERITAS_MULTI_REBUTTAL", raising=False)
    monkeypatch.delenv("VERITAS_REBUTTAL_ROUNDS", raising=False)
    _case_tree(tmp_path)
    client = ScriptedClient([
        _merge_resp, _conflict_resp,
        _CLEAN_A1, _CLEAN_B1, _CLEAN_A2, _CLEAN_B2, _arbitrate_resp,
        _EDGES_EMPTY,
    ])
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out", probe=False),
        _deps_full(client))
    d = result.dossier
    acc = (d.accounting or {}).get(ACCOUNTING_KEY)
    assert isinstance(acc, dict), "默认开必须写 accounting[rebuttal]"
    assert acc["n_pairs"] == 1 and acc["n_escalated"] == 1
    row = acc["pairs"][0]
    assert row["escalation"] == "multi_round"
    assert row["escalation_reason"] == "true_oppose_forced"
    assert row["rounds_requested"] == 2 and row["rounds_used"] == 2
    assert len(row["rounds"]) == 4 and all(r["gate_ok"] for r in row["rounds"])
    assert row["lean"]["resolved"] is True and row["lean"]["winner_id"]
    pair_dict = d.conflicts[0]
    rebuts = pair_dict["resolution"]["rebuts"]
    assert "第1轮：" in rebuts["a"] and "第2轮：" in rebuts["a"]
    assert result.chain.verify_chain().ok
    # 逐轮调用形状：4 次质证，其中 2 次是第 2 轮回打模板
    rebut_calls = [c for c in client.calls
                   if c["messages"][0]["content"].startswith(_REBUTTAL_HEAD)]
    assert len(rebut_calls) == 4
    assert sum(1 for c in rebut_calls if "质证第 2 轮" in
               c["messages"][0]["content"]) == 2


def test_e2_pipeline_env_off_single_round_identical(monkeypatch, tmp_path):
    monkeypatch.setenv("VERITAS_MULTI_REBUTTAL", "0")
    _case_tree(tmp_path)
    client = ScriptedClient([
        _merge_resp, _conflict_resp,
        _CLEAN_A1, _CLEAN_B1, _arbitrate_resp, _EDGES_EMPTY,
    ])
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out", probe=False),
        _deps_full(client))
    d = result.dossier
    assert ACCOUNTING_KEY not in (d.accounting or {}), \
        "关旗不许写 rebuttal 键"
    rebuts = d.conflicts[0]["resolution"]["rebuts"]
    assert rebuts == {"a": _CLEAN_A1, "b": _CLEAN_B1}, \
        "关旗＝旧单轮旧形状（无轮次前缀、仲裁输入不变）"
    assert result.chain.verify_chain().ok


def test_g_pipeline_empty_state(monkeypatch, tmp_path):
    monkeypatch.delenv("VERITAS_MULTI_REBUTTAL", raising=False)
    (tmp_path / "manifest.yaml").write_text(
        "question: 多主体概况？\n"
        "sources:\n  - file: reb.md\n    type: news\n", encoding="utf-8")
    (tmp_path / "reb.md").write_text(
        "# 概况\n\n客户A回款正常。客户C交付进度符合预期。\n",
        encoding="utf-8")
    panel_a = json.dumps({"conclusions": [{
        "statement": "客户A存在回款风险",
        "evidence": [{"quote": "客户A回款正常", "segment_id": "SRC1#s1",
                      "relation": "correlation", "level": "B",
                      "note": "同段反读"}]}]}, ensure_ascii=False)
    panel_b = json.dumps({"conclusions": [{
        "statement": "客户C交付进度符合预期",
        "evidence": [{"quote": "客户C交付进度符合预期", "segment_id": "SRC1#s1",
                      "relation": "correlation", "level": "A",
                      "note": "直接引证"}]}]}, ensure_ascii=False)
    client = ScriptedClient([
        '{"groups": []}', '{"conflicts": []}', _EDGES_EMPTY])
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out", probe=False),
        _deps_full(client, panels=(panel_a, panel_b, _PANEL_EMPTY)))
    acc = (result.dossier.accounting or {}).get(ACCOUNTING_KEY)
    assert isinstance(acc, dict)
    assert acc["empty_state"] is True and acc["n_pairs"] == 0
    assert "未检出" in acc["detail"]


# ------------------------------------------------ 白名单／折叠／导出面


def test_f_both_kept_whitelists_register_rebuttal():
    src = Path("app/pipeline.py").read_text(encoding="utf-8")
    anchors = src.count('kept = {k: v for k, v in (dossier.accounting or {}).items()')
    assert anchors == 2, "两处 kept 白名单（早退＋主路径）都在场"
    for window in src.split('kept = {k: v for k, v in (dossier.accounting or {}).items()')[1:]:
        head = window[:1700]
        assert '"rebuttal"' in head, "白名单 1700 字窗内必须登记 rebuttal"


def test_h_fold_and_export_face(monkeypatch, tmp_path):
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    d = _dossier_with_numbers(["40%", "60%"])
    rows = [{"pair_id": "CFL-test0001", "a_id": "CON-a", "b_id": "CON-b",
             "triage_class": "true_oppose", "triage_reason_code": "x",
             "escalation": "multi_round",
             "escalation_reason": "true_oppose_forced",
             "semantic_upgrade": False, "rounds_requested": 2,
             "rounds_used": 2,
             "rounds": [{"round": 1, "side": "a", "conclusion_id": "CON-a",
                         "text": _CLEAN_A1, "chars": len(_CLEAN_A1),
                         "gate_ok": True, "repaired": False,
                         "quote_flags": 0, "ref_flags": 0}],
             "lean": {"resolved": True, "winner_id": "CON-a",
                      "method": "arbitration"}}]
    assert isinstance(write_accounting(
        d, rows=rows, n_pairs=1, rounds=2), dict)
    official = tmp_path / "official"
    paths = export_official(
        [({"question_id": "q1", "question": d.question}, d)], official)
    payload = json.loads(
        paths["conflict_trace"].read_text(encoding="utf-8"))
    section = payload.get("rebuttal")
    assert isinstance(section, dict), "回放面必须带 rebuttal 节"
    assert section["n_escalated"] == 1
    assert section["pairs"][0]["escalation"] == "multi_round"
    assert section["pairs"][0]["lean"]["resolved"] is True
    # C-143 空态句逐字保住（同一面、两节并存互不污染）
    assert "1 题均未检出冲突对或事实对撞" in payload.get("detail", "")
    # 空态分支同形：零对零质证也带 rebuttal 节
    d2 = _dossier_with_numbers([])
    assert isinstance(write_accounting(
        d2, rows=[], n_pairs=0, rounds=2), dict)
    official2 = tmp_path / "official2"
    paths2 = export_official(
        [({"question_id": "q2", "question": d2.question}, d2)], official2)
    payload2 = json.loads(
        paths2["conflict_trace"].read_text(encoding="utf-8"))
    assert payload2.get("rebuttal", {}).get("empty_state") is True
    assert payload2.get("rebuttal", {}).get("n_pairs") == 0


def test_h2_accounting_key_absent_when_env_off(monkeypatch):
    monkeypatch.setenv("VERITAS_MULTI_REBUTTAL", "0")
    d = _dossier_with_numbers(["40%", "60%"])
    assert write_accounting(
        d, rows=[], n_pairs=0, rounds=2) is None
    assert ACCOUNTING_KEY not in (d.accounting or {})


def test_i_joined_rebuts_shape():
    rows = [
        {"round": 1, "side": "a", "text": "甲一"},
        {"round": 1, "side": "b", "text": "乙一"},
        {"round": 2, "side": "a", "text": "甲二"},
    ]
    out = joined_rebuts(rows)
    assert out == {"a": "第1轮：甲一；第2轮：甲二", "b": "第1轮：乙一"}
