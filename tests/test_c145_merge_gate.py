"""C-145：归并硬约束闸（同主体×同指标×可核验才合）——守护格。

闸随 ``VERITAS_CONFLICT_TRACE``（C-145a 起出厂默认开；＝0 全关＝改前行为）。
只看 LLM 语义归并段提出的 ≥2 人组（机械归并键已含三腿，不重复过闸）。
锁定五件事：四条腿逐个否决且留痕、该合的照合、旗关＝旧行为（错组照并＝
A/B 对照）、白名单两处登记（键活到 report.json）、交卷回放面带 merge_gate 节。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.agents.arbiter import Coordinator
from app.core.conflict_trace import apply_conflict_trace
from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType)
from app.core.merge_gate import ACCOUNTING_KEY, check_group, gate_active
from tests.test_collab import ScriptedClient


def _dossier_with(*rows: tuple[str, str, str, bool]) -> Dossier:
    """rows＝(cid, statement, author, with_evidence)；证据统一挂 SRC1#s1。"""
    d = Dossier(question="星辰数智各客户项目是否存在回款风险？")
    src = Source.create("账目", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="客户B 应收账款回款存在困难，客户C 情形类似。"))
    d.add_source(src)
    for cid, statement, author, with_ev in rows:
        d.conclusions.append(
            Conclusion.create(statement, author=author, id=cid))
        if with_ev:
            d.add_evidence(EvidenceNode.create(
                cid, "客户B 应收账款回款存在困难", ["SRC1#s1"], id=f"EV-{cid}"))
    return d


def _merge_stub(*groups: tuple[str, ...]) -> ScriptedClient:
    body = ",".join(
        '{"statement": "合并组%d", "member_ids": [%s]}'
        % (i, ",".join(f'"{m}"' for m in g))
        for i, g in enumerate(groups))
    return ScriptedClient(['{"groups": [%s]}' % body])


# -- 旗随 C-145a 出厂默认 -----------------------------------------------------


def test_a_gate_follows_factory_flag(monkeypatch):
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    assert gate_active() is True, "C-145a 起默认开＝闸默认在场"
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "0")
    assert gate_active() is False, "env=0 ＝闸与留痕全关"


# -- 四条腿逐个否决且留痕 ------------------------------------------------------


def test_b_subject_mismatch_dissolved_with_trace(monkeypatch):
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    d = _dossier_with(("CON-0", "客户B存在回款风险", "a0", True),
                      ("CON-1", "客户C存在回款风险", "a1", True))
    active = Coordinator(_merge_stub(("CON-0", "CON-1")), "m").merge_conclusions(
        d, ["CON-0", "CON-1"])
    assert sorted(active) == ["CON-0", "CON-1"], "跨主体组不许并"
    assert all(c.status == "majority" for c in d.conclusions)
    rec = d.accounting[ACCOUNTING_KEY]
    assert rec["n_groups_checked"] == 1 and rec["n_blocked"] == 1
    row = rec["blocked"][0]
    assert row["fail_legs"] == ["subject_mismatch"]
    assert row["member_ids"] == ["CON-0", "CON-1"]
    payload = apply_conflict_trace(d, enabled=True)
    assert payload["merge_gate"]["n_blocked"] == 1, "回放面 payload 须带闸节"


def test_c_missing_subject_dissolved(monkeypatch):
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    d = _dossier_with(("CON-0", "项目存在回款风险", "a0", True),
                      ("CON-1", "项目回款存在困难", "a1", True))
    active = Coordinator(_merge_stub(("CON-0", "CON-1")), "m").merge_conclusions(
        d, ["CON-0", "CON-1"])
    assert sorted(active) == ["CON-0", "CON-1"]
    rec = d.accounting[ACCOUNTING_KEY]
    assert rec["blocked"][0]["fail_legs"] == ["missing_subject"]


def test_d_missing_metric_dissolved(monkeypatch):
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    d = _dossier_with(("CON-0", "客户B经营承压明显", "a0", True),
                      ("CON-1", "客户B经营面临压力", "a1", True))
    active = Coordinator(_merge_stub(("CON-0", "CON-1")), "m").merge_conclusions(
        d, ["CON-0", "CON-1"])
    assert sorted(active) == ["CON-0", "CON-1"]
    rec = d.accounting[ACCOUNTING_KEY]
    assert rec["blocked"][0]["fail_legs"] == ["missing_metric"]


def test_e_polarity_opposed_dissolved(monkeypatch):
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    d = _dossier_with(("CON-0", "客户B存在回款风险", "a0", True),
                      ("CON-1", "客户B不存在回款风险", "a1", True))
    active = Coordinator(_merge_stub(("CON-0", "CON-1")), "m").merge_conclusions(
        d, ["CON-0", "CON-1"])
    assert sorted(active) == ["CON-0", "CON-1"], "正反判断交冲突面，不并为已一致"
    rec = d.accounting[ACCOUNTING_KEY]
    assert rec["blocked"][0]["fail_legs"] == ["polarity_opposed"]


def test_f_unverifiable_member_blocks():
    d = _dossier_with(("CON-0", "客户B存在回款风险", "a0", True),
                      ("CON-1", "客户B的回款存在困难", "a1", False))
    check = check_group(d, ["CON-0", "CON-1"])
    assert not check["ok"] and check["fail_legs"] == ["unverifiable"]


# -- 该合的照合 ---------------------------------------------------------------


def test_g_legit_group_still_merges(monkeypatch):
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    d = _dossier_with(("CON-0", "客户B存在回款风险", "a0", True),
                      ("CON-1", "客户B的回款存在困难", "a1", True))
    active = Coordinator(_merge_stub(("CON-0", "CON-1")), "m").merge_conclusions(
        d, ["CON-0", "CON-1"])
    assert len(active) == 1 and active[0] not in {"CON-0", "CON-1"}
    group = d.conclusion(active[0])
    assert group.authors == ["a0", "a1"], "该合的合：跨人会签不丢"
    rec = d.accounting[ACCOUNTING_KEY]
    assert rec["n_groups_checked"] == 1 and rec["n_blocked"] == 0


# -- 旗关＝改前行为（A/B 对照）-------------------------------------------------


def test_h_flag_off_old_merge_behavior(monkeypatch):
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "0")
    d = _dossier_with(("CON-0", "客户B存在回款风险", "a0", True),
                      ("CON-1", "客户C存在回款风险", "a1", True))
    active = Coordinator(_merge_stub(("CON-0", "CON-1")), "m").merge_conclusions(
        d, ["CON-0", "CON-1"])
    assert len(active) == 1, "旗关＝错组照并（改前行为，供 A/B 对照）"
    assert d.accounting.get(ACCOUNTING_KEY) is None, "旗关不写闸键"


# -- 白名单两处登记（键活到 report.json）---------------------------------------


def test_i_both_whitelists_carry_merge_gate():
    src = (Path(__file__).resolve().parents[1] / "app" / "pipeline.py"
           ).read_text(encoding="utf-8")
    anchor = "kept = {k: v for k, v in (dossier.accounting or {}).items()"
    spots = [i for i in range(len(src)) if src.startswith(anchor, i)]
    assert len(spots) == 2, "管线恰两处 kept 白名单"
    for i in spots:
        window = src[i:i + 1700]
        assert '"merge_gate"' in window, "两处白名单都须登记 merge_gate"


# -- 交卷回放面带 merge_gate 节（C-143 展示面衔接）-----------------------------


def test_j_export_face_carries_merge_gate_section(monkeypatch, tmp_path):
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    from app.agents.base import Analyst
    from app.export.official import export_official
    from app.pipeline import RunDeps, RunSpec, run_case
    from tests.test_c143_trace_report_face import (
        _case_dir, _dossier_with_numbers, FakeClient, _EMPTY_JSON,
    )

    d = _dossier_with_numbers(["40%", "60%"])
    out = tmp_path / "out"
    # 协同段只在 ≥2 名分析师时跑（归并早退记账由此可达）
    deps = RunDeps(client=FakeClient(_EMPTY_JSON), analysts=[
        Analyst("mainstream", "测", FakeClient(_EMPTY_JSON), "m"),
        Analyst("technologist", "测", FakeClient(_EMPTY_JSON), "m")])
    r = run_case(
        RunSpec(case_dir=_case_dir(tmp_path), out_dir=out, dossier=d,
                probe=False),
        deps)
    assert isinstance((r.dossier.accounting or {}).get("merge_gate"), dict)
    official = out / "official"
    export_official(
        [({"question_id": "q1", "question": d.question}, r.dossier)],
        official)
    payload = json.loads(
        (official / "conflict_trace.json").read_text(encoding="utf-8"))
    section = payload.get("merge_gate")
    assert isinstance(section, dict), "回放面必须带 merge_gate 节"
    assert section["n_groups_checked"] == 0 and section["n_blocked"] == 0
    assert payload.get("records"), "对撞夹具自证：records 仍在（三类分布不受闸污染）"
    assert "merge_gate＝" not in payload.get("detail", ""), "零否决不加否决句"
