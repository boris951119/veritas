"""C-148：仲裁上下文接线＋轻裁——守护格。

默认开（未设 env）＝oral_misread／date_offset 走程序轻裁（tie 形态、不叫
模型、双方保留多数意见、理由结构化进 basis）；true_oppose／other 走 LLM
仲裁但提示词尾部拼程序侧上下文片段（分流判定／归并闸否决史／质证留痕）；
accounting["arbitration"] 逐对留痕并折进 conflict_trace.json 顶层节。
env VERITAS_ARB_CONTEXT=0 ＝与改前逐字节同形（无轻裁路、无片段、
accounting 无键）。仲裁公式／证据强度一行不动（冲突数值线 STOP）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.agents.arbiter import Coordinator
from app.core.arbitration_face import (
    ACCOUNTING_KEY,
    ROUTE_LIGHT,
    ROUTE_LLM,
    arb_enabled,
    arb_route,
    arbitrate_light,
    build_context,
    merge_veto_face,
    rebuttal_face,
    write_accounting,
)
from app.core.conflicts import ConflictPair, apply_resolution
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceNode,
    Segment,
    Source,
    SourceType,
)
from app.export.official import export_official
from app.pipeline import RunDeps, RunSpec, run_case
from tests.test_collab import ScriptedClient
from tests.test_c143_trace_report_face import _dossier_with_numbers
from tests.test_c147_rebuttal_rounds import (
    _CLEAN_A1,
    _CLEAN_B1,
    _CLEAN_A2,
    _CLEAN_B2,
    _PANEL_EMPTY,
    _deps_full,
    _two_ids,
)


def _two_misread_ids(text: str) -> tuple[str, str]:
    """误读对夹具自证：回款句＝甲方、交付句＝乙方。"""
    a = b = None
    for cid, stmt in re.findall(
            r"\[(CON-[0-9a-f]+)\]（[^）]*）([^\n]+)", text):
        if "回款" in stmt:
            a = cid
        elif "交付" in stmt:
            b = cid
    assert a and b, f"夹具自证失败：{text[:200]}"
    return a, b


# ------------------------------------------------ 夹具


def _pair_dossier() -> Dossier:
    """同主体极性对立（true_oppose 构造件）＋在卷信源段。"""
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


def _misread_dossier() -> tuple[Dossier, ConflictPair]:
    """议题维不相交的一对（triage ③→oral_misread 构造件；同主体、有证据）。"""
    d = Dossier(question="客户B的经营情况如何？")
    src = Source.create("经营纪要", SourceType.NEWS, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="客户B的回款出现逾期，公司已启动催收；交付进度符合合同约定。",
        index=0))
    d.sources.append(src)
    ca = Conclusion.create("客户B回款存在风险", author="a0")
    cb = Conclusion.create("客户B交付进度符合预期", author="a1")
    d.conclusions.extend([ca, cb])
    d.add_evidence(EvidenceNode.create(
        ca.id, "客户B的回款出现逾期", ["SRC1#s1"]))
    d.add_evidence(EvidenceNode.create(
        cb.id, "交付进度符合合同约定", ["SRC1#s1"]))
    return d, ConflictPair(a_id=ca.id, b_id=cb.id, topic="经营情况")


_ARBITRATE_HEAD = "程序证据强度对比"


# ------------------------------------------------ 开关


def test_a_default_on_and_env_off(monkeypatch):
    """默认开＝True；env VERITAS_ARB_CONTEXT=0 关；config.json 叠加。"""
    monkeypatch.delenv("VERITAS_ARB_CONTEXT", raising=False)
    assert arb_enabled() is True
    monkeypatch.setenv("VERITAS_ARB_CONTEXT", "0")
    assert arb_enabled() is False
    monkeypatch.setenv("VERITAS_ARB_CONTEXT", "1")
    assert arb_enabled() is True


def test_a2_settings_field_and_config_overlay(tmp_path, monkeypatch):
    """字段必须真在 Settings 上（hasattr 回退会遮「字段丢失」）；config.json
    overlay 经 from_json 真入口叠加。"""
    from app.config import Settings

    monkeypatch.delenv("VERITAS_ARB_CONTEXT", raising=False)
    s = Settings()
    assert s.arb_context is True, "出厂默认必须在字段上＝True"
    (tmp_path / "config.json").write_text(
        '{"arb_context": false}', encoding="utf-8")
    assert Settings.from_json(tmp_path / "config.json").arb_context is False
    (tmp_path / "config.json").write_text(
        '{"arb_context": true}', encoding="utf-8")
    assert Settings.from_json(tmp_path / "config.json").arb_context is True


# ------------------------------------------------ 路由（纯机械）


def test_b_route_light_and_llm():
    d, _ = _pair_dossier()
    pos, neg = d.conclusions[0], d.conclusions[1]
    # true_oppose → LLM 仲裁（带上下文片段）
    r1 = arb_route(ConflictPair(a_id=pos.id, b_id=neg.id), d)
    assert r1["route"] == ROUTE_LLM
    assert r1["triage_class"] == "true_oppose"
    d2, mis = _misread_dossier()
    # 议题维不相交 → oral_misread → 轻裁
    r2 = arb_route(mis, d2)
    assert r2["route"] == ROUTE_LIGHT
    assert r2["triage_class"] == "oral_misread"
    assert r2["triage_reason_code"] == "pair_topic_disjoint"


# ------------------------------------------------ 轻裁（tie 形态）


def test_c_light_resolution_tie_and_no_false_inequality():
    d, mis = _misread_dossier()
    route = arb_route(mis, d)
    res = arbitrate_light(mis, d, {"a": "甲质证", "b": "乙质证"}, route)
    mis.resolution = res  # 与管线同口径：由调用方挂载到 pair.resolution
    assert res.winner_id == "tie" and res.method == "tie"
    assert res.decision_path == "tie"
    assert "程序轻裁" in res.rationale
    assert "oral_misread" in res.rationale
    assert set(res.evidence_weight) == {mis.a_id, mis.b_id}
    assert res.rebuts == {"a": "甲质证", "b": "乙质证"}
    basis = res.basis
    assert basis["route"] == ROUTE_LIGHT
    assert basis["triage_class"] == "oral_misread"
    # 假不等式不许进 basis：轻裁不保证强度差 ≤ margin，文案里不许出现该句式
    assert "≤" not in str(basis.get("type_applies")), basis["type_applies"]
    assert "只对比不裁决" in str(basis.get("type_applies"))
    assert "双方均未排除" in str(basis.get("loser_excluded"))
    # 落卷：双方保留 majority，无少数意见；链上重启条件在场
    assert apply_resolution(mis, d) is None
    assert d.conclusion(mis.a_id).status == "majority"
    assert d.conclusion(mis.b_id).status == "majority"
    assert mis.resolution.to_dict().get("重启条件")


def test_c2_light_with_wild_strength_gap_still_no_false_claim():
    d, mis = _misread_dossier()
    # 把乙方证据降级成弱证据，强度差拉大也要不撒谎
    for ev in d.evidences_of(mis.b_id):
        ev.level = ev.level.__class__("D")
    route = arb_route(mis, d)
    res = arbitrate_light(mis, d, {}, route)
    ta = str(res.basis["type_applies"])
    assert "≤" not in ta
    assert "≤ 0.20" not in ta


# ------------------------------------------------ 上下文片段（程序侧）


def test_d_context_fragment_faces():
    d, mis = _misread_dossier()
    route = arb_route(mis, d)
    # ① 无否决史＋无质证行 → 缺省行
    ctx = build_context(mis, d, route)
    assert "仲裁上下文（程序侧，可复算" in ctx
    assert "oral_misread" in ctx and "pair_topic_disjoint" in ctx
    assert "归并闸否决史：无" in ctx
    # ② 归并闸否决史在场（两成员同入被否决组）
    d.accounting = {"merge_gate": {"blocked": [{
        "id": "MERGE-0003", "member_ids": [mis.a_id, mis.b_id],
        "fail_legs": ["polarity_opposed"]}]}}
    veto = merge_veto_face(d, [mis.a_id, mis.b_id])
    assert veto and veto[0]["group_id"] == "MERGE-0003"
    ctx2 = build_context(mis, d, route, veto=veto)
    assert "MERGE-0003" in ctx2 and "polarity_opposed" in ctx2
    # ③ 质证留痕（多轮行摘要进片段）
    rb_rows = [{"pair_id": mis.id, "escalation": "multi_round",
                "rounds": [
                    {"round": 1, "side": "a", "text": "甲一", "chars": 2,
                     "gate_ok": True, "repaired": False,
                     "quote_flags": 0, "ref_flags": 0},
                    {"round": 2, "side": "b", "text": "乙二", "chars": 2,
                     "gate_ok": False, "repaired": True,
                     "quote_flags": 1, "ref_flags": 0}]}]
    face = rebuttal_face(mis.id, rb_rows)
    assert face["rounds_used"] == 2 and face["gate_flags"] == 1
    assert face["repaired"] == 1
    ctx3 = build_context(mis, d, route, rb_rows=rb_rows)
    assert "2 轮" in ctx3 and "闸旗 1 项" in ctx3


# ------------------------------------------------ 管线接线（默认开／关）


def _conflict_resp_pair(a_id: str, b_id: str, desc: str) -> str:
    return ('{"conflicts": [{"a": "%s", "b": "%s", "topic": "t", '
            '"description": "%s"}]}' % (a_id, b_id, desc))


def _case_tree(tmp_path: Path) -> None:
    (tmp_path / "manifest.yaml").write_text(
        "question: 客户B的回款情况如何？\n"
        "sources:\n  - file: reb.md\n    type: news\n", encoding="utf-8")
    (tmp_path / "reb.md").write_text(
        "# 回款\n\n客户B的回款出现逾期，现金流承压，公司已启动催收。\n",
        encoding="utf-8")


def _misread_case_tree(tmp_path: Path) -> None:
    (tmp_path / "manifest.yaml").write_text(
        "question: 客户B的经营情况如何？\n"
        "sources:\n  - file: reb.md\n    type: news\n", encoding="utf-8")
    (tmp_path / "reb.md").write_text(
        "# 经营\n\n客户B的回款出现逾期，公司已启动催收；"
        "交付进度符合合同约定。\n", encoding="utf-8")


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
_PANEL_MISREAD_A = json.dumps({"conclusions": [{
    "statement": "客户B回款存在风险",
    "evidence": [{"quote": "客户B的回款出现逾期", "segment_id": "SRC1#s1",
                  "relation": "correlation", "level": "A",
                  "note": "直接引证"}]}]}, ensure_ascii=False)
_PANEL_MISREAD_B = json.dumps({"conclusions": [{
    "statement": "客户B交付进度符合预期",
    "evidence": [{"quote": "交付进度符合合同约定", "segment_id": "SRC1#s1",
                  "relation": "correlation", "level": "A",
                  "note": "直接引证"}]}]}, ensure_ascii=False)
_EDGES_EMPTY = '{"edges": []}'


def _arbitrate_resp(messages) -> str:
    a_id = re.search(r"\[(CON-[0-9a-f]+)\]",
                     messages[-1]["content"]).group(1)
    return '{"winner": "%s", "rationale": "甲方证据等级占优"}' % a_id


def test_e_pipeline_default_on_true_oppose_with_context(
        monkeypatch, tmp_path):
    """默认开＋真对立：LLM 仲裁收到程序侧片段；逐对留痕 llm_enriched。"""
    monkeypatch.delenv("VERITAS_ARB_CONTEXT", raising=False)
    monkeypatch.delenv("VERITAS_MULTI_REBUTTAL", raising=False)
    _case_tree(tmp_path)

    def _merge_keep_separate(messages):
        pos, neg = _two_ids(messages[-1]["content"])
        return ('{"groups": [{"statement": "客户B存在回款风险", '
                '"member_ids": ["%s"]}, {"statement": "客户B不存在回款风险", '
                '"member_ids": ["%s"]}]}' % (pos, neg))

    def _conflict(messages):
        pos, neg = _two_ids(messages[-1]["content"])
        return _conflict_resp_pair(pos, neg, "对回款状态判断对立")

    client = ScriptedClient([
        _merge_keep_separate, _conflict,
        _CLEAN_A1, _CLEAN_B1, _CLEAN_A2, _CLEAN_B2, _arbitrate_resp,
        _EDGES_EMPTY,
    ])
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out", probe=False),
        _deps_full(client, panels=(_PANEL_POS, _PANEL_NEG, _PANEL_EMPTY)))
    d = result.dossier
    arb = (d.accounting or {}).get(ACCOUNTING_KEY)
    assert isinstance(arb, dict), "默认开必须写 accounting[arbitration]"
    assert arb["n_pairs"] == 1 and arb["n_llm"] == 1 and arb["n_light"] == 0
    row = arb["pairs"][0]
    assert row["route"] == ROUTE_LLM
    assert row["llm_called"] is True and row["context_included"] is True
    assert row["resolved"] is True and row["winner_id"]
    # 仲裁提示词尾部必须拼上程序侧片段（分流判定行在场）
    arb_calls = [c for c in client.calls
                 if _ARBITRATE_HEAD in c["messages"][-1]["content"]]
    assert len(arb_calls) == 1
    content = arb_calls[0]["messages"][-1]["content"]
    assert "仲裁上下文（程序侧，可复算" in content
    assert "true_oppose" in content
    assert result.chain.verify_chain().ok


def test_e2_pipeline_light_route_skips_arbitrate_llm(
        monkeypatch, tmp_path):
    """默认开＋误读对：不叫仲裁模型、tie 落卷、双方保持 majority。"""
    monkeypatch.delenv("VERITAS_ARB_CONTEXT", raising=False)
    _misread_case_tree(tmp_path)

    def _merge_keep_separate(messages):
        a_id, b_id = _two_misread_ids(messages[-1]["content"])
        return ('{"groups": [{"statement": "客户B回款存在风险", '
                '"member_ids": ["%s"]}, {"statement": "客户B交付进度符合预期", '
                '"member_ids": ["%s"]}]}' % (a_id, b_id))

    def _conflict(messages):
        a_id, b_id = _two_misread_ids(messages[-1]["content"])
        return _conflict_resp_pair(a_id, b_id, "两个判断并陈")

    client = ScriptedClient([
        _merge_keep_separate, _conflict,
        _CLEAN_A1, _CLEAN_B1, _EDGES_EMPTY,
    ])
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out", probe=False),
        _deps_full(client, panels=(
            _PANEL_MISREAD_A, _PANEL_MISREAD_B, _PANEL_EMPTY)))
    d = result.dossier
    arb = (d.accounting or {}).get(ACCOUNTING_KEY)
    assert isinstance(arb, dict)
    assert arb["n_pairs"] == 1 and arb["n_light"] == 1 and arb["n_llm"] == 0
    row = arb["pairs"][0]
    assert row["route"] == ROUTE_LIGHT
    assert row["llm_called"] is False and row["context_included"] is False
    assert row["resolved"] is True and row["winner_id"] == "tie"
    assert row["method"] == "tie"
    # 仲裁模型调用一次都不许发生（仲裁提示词标记零在场）
    assert not [c for c in client.calls
                if _ARBITRATE_HEAD in c["messages"][-1]["content"]]
    # 消解落卷：tie 形态，双方保持 majority
    pair_dict = d.conflicts[0]
    assert pair_dict["resolution"]["method"] == "tie"
    assert pair_dict["resolution"]["winner_id"] == "tie"
    assert "程序轻裁" in pair_dict["resolution"]["rationale"]
    assert result.chain.verify_chain().ok


def test_e3_env_off_old_path_with_arbitrate(monkeypatch, tmp_path):
    """env=0：误读对照旧走 LLM 仲裁、提示词无片段、accounting 无键。"""
    monkeypatch.setenv("VERITAS_ARB_CONTEXT", "0")
    _misread_case_tree(tmp_path)

    def _merge_keep_separate(messages):
        a_id, b_id = _two_misread_ids(messages[-1]["content"])
        return ('{"groups": [{"statement": "客户B回款存在风险", '
                '"member_ids": ["%s"]}, {"statement": "客户B交付进度符合预期", '
                '"member_ids": ["%s"]}]}' % (a_id, b_id))

    def _conflict(messages):
        a_id, b_id = _two_misread_ids(messages[-1]["content"])
        return _conflict_resp_pair(a_id, b_id, "两个判断并陈")

    client = ScriptedClient([
        _merge_keep_separate, _conflict,
        _CLEAN_A1, _CLEAN_B1, _arbitrate_resp, _EDGES_EMPTY,
    ])
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out", probe=False),
        _deps_full(client, panels=(
            _PANEL_MISREAD_A, _PANEL_MISREAD_B, _PANEL_EMPTY)))
    d = result.dossier
    assert ACCOUNTING_KEY not in (d.accounting or {}), \
        "关旗不许写 arbitration 键"
    arb_calls = [c for c in client.calls
                 if _ARBITRATE_HEAD in c["messages"][-1]["content"]]
    assert len(arb_calls) == 1, "关旗＝误读对照旧走 LLM 仲裁"
    content = arb_calls[0]["messages"][-1]["content"]
    assert "仲裁上下文" not in content, "关旗＝提示词与改前逐字节同形"
    assert content.rstrip().endswith("冲突说明：两个判断并陈")
    assert result.chain.verify_chain().ok


# ------------------------------------------------ 白名单／折叠／导出面


def test_f_both_kept_whitelists_register_arbitration():
    src = Path("app/pipeline.py").read_text(encoding="utf-8")
    anchors = src.count('kept = {k: v for k, v in (dossier.accounting or {}).items()')
    assert anchors == 2, "两处 kept 白名单（早退＋主路径）都在场"
    for window in src.split('kept = {k: v for k, v in (dossier.accounting or {}).items()')[1:]:
        head = window[:1800]
        assert '"arbitration"' in head, "白名单 1800 字窗内必须登记 arbitration"


def _arb_row(pair_id: str) -> dict:
    return {"pair_id": pair_id, "a_id": "CON-a", "b_id": "CON-b",
            "triage_class": "oral_misread",
            "triage_reason_code": "pair_topic_disjoint",
            "route": ROUTE_LIGHT, "context_included": False,
            "llm_called": False, "merge_veto_groups": [],
            "resolved": True, "winner_id": "tie", "method": "tie",
            "decision_path": "tie"}


def test_h_fold_and_export_face(monkeypatch, tmp_path):
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    d = _dossier_with_numbers(["40%", "60%"])
    assert isinstance(write_accounting(
        d, rows=[_arb_row("CFL-test0001")], n_pairs=1), dict)
    official = tmp_path / "official"
    paths = export_official(
        [({"question_id": "q1", "question": d.question}, d)], official)
    payload = json.loads(
        paths["conflict_trace"].read_text(encoding="utf-8"))
    section = payload.get("arbitration")
    assert isinstance(section, dict), "回放面必须带 arbitration 节"
    assert section["n_light"] == 1 and section["n_llm"] == 0
    assert section["pairs"][0]["route"] == ROUTE_LIGHT
    assert section["pairs"][0]["method"] == "tie"
    # 空态分支同形：零对也带 arbitration 节
    d2 = _dossier_with_numbers([])
    assert isinstance(write_accounting(d2, rows=[], n_pairs=0), dict)
    official2 = tmp_path / "official2"
    paths2 = export_official(
        [({"question_id": "q2", "question": d2.question}, d2)], official2)
    payload2 = json.loads(
        paths2["conflict_trace"].read_text(encoding="utf-8"))
    assert payload2.get("arbitration", {}).get("empty_state") is True
    assert payload2.get("arbitration", {}).get("n_pairs") == 0


def test_h2_accounting_key_absent_when_env_off(monkeypatch):
    monkeypatch.setenv("VERITAS_ARB_CONTEXT", "0")
    d = _dossier_with_numbers(["40%", "60%"])
    assert write_accounting(d, rows=[], n_pairs=0) is None
    assert ACCOUNTING_KEY not in (d.accounting or {})


def test_i_write_accounting_counts():
    d = _dossier_with_numbers(["40%", "60%"])
    rows = [_arb_row("CFL-a"),
            dict(_arb_row("CFL-b"), route=ROUTE_LLM, llm_called=True)]
    payload = write_accounting(d, rows=rows, n_pairs=2)
    assert payload["n_light"] == 1 and payload["n_llm"] == 1
    assert "轻裁 1" in payload["detail"]
