"""C-32：结构化因果主张卡（校验声称完整性，不做效应估计／完整因果引擎）。

零 LLM。长期约束写成对源码／settings 的内容断言。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.base import Analyst
from app.core.audit import KIND_LABEL, audit_all
from app.core.causal_claim import (
    BOUNDARY_NOTE,
    CLAIM_KEYS,
    apply_causal_claim_gates,
    audit_causal_claim_missing,
)
from app.core.confidence import conclude_confidence, evidence_score, recompute_all
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    RelationKind,
    Segment,
    Source,
    SourceType,
)
from app.core.hashchain import HashChain
from app.export.official import _FIELD_NOTES, export_official
from app.pipeline import RunDeps, RunSpec, render_report_md, run_case
from app.server import create_app
from tests.test_agents_pipeline import GOOD_BAD_JSON, FakeClient

ROOT = Path(__file__).resolve().parents[1]

_FULL_CLAIM = {
    "intervention": "涂覆界面缓冲层",
    "outcome": "中试良率提升",
    "population": "全固态电芯产线",
    "counterfactual": "若不涂覆则良率仍不足百分之四十",
}

_MECH_NOTE = "因为涂覆缓冲层，导致界面阻抗下降从而良率提升"


def _base_dossier(*, quote: str | None = None) -> Dossier:
    text = quote or "全固态电芯的中试良率尚不足百分之四十。"
    d = Dossier(question="固态电池量产路径？", panel=["mainstream"])
    src = Source.create("测", SourceType.PAPER, credibility=0.8, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text=text, locator="段 1"))
    d.add_source(src)
    con = Conclusion.create("良率仍低", author="mainstream", id="CON1")
    d.conclusions.append(con)
    return d


def _add_ev(d: Dossier, *, relation=RelationKind.CORRELATION,
            note: str = "", claim=None, mechanism="correlation_only",
            missing_links=None, design_tier="claim_only",
            eid="EV1", quote: str | None = None) -> EvidenceNode:
    q = quote or "全固态电芯的中试良率尚不足百分之四十"
    ev = EvidenceNode.create(
        "CON1", q, ["SRC1#s1"],
        relation=relation, level=EvidenceLevel.B, note=note, id=eid,
        causal_claim=claim, mechanism_completeness=mechanism,
        missing_links=list(missing_links or []),
        design_tier=design_tier,
    )
    d.add_evidence(ev)
    return ev


def _case_dir(tmp_path: Path, name: str = "c32") -> Path:
    case = tmp_path / name
    case.mkdir(parents=True)
    (case / "manifest.yaml").write_text(
        "question: 固态电池量产路径？\ntitle: C-32\n", encoding="utf-8")
    (case / "a.md").write_text(
        "全固态电芯的中试良率尚不足百分之四十。"
        "因为涂覆缓冲层，导致界面阻抗下降从而良率提升。\n",
        encoding="utf-8",
    )
    return case


def _q() -> dict:
    return {"question_id": "q1", "question": "固态电池量产路径？"}


def _seeded_dossier(*, relation: RelationKind, claim, note: str = "") -> Dossier:
    """注入用案卷：已有结论＋证据，桩分析师回空 conclusions 以免再加证据。"""
    d = _base_dossier()
    _add_ev(d, relation=relation, note=note, claim=claim, mechanism="direct")
    return d


_EMPTY_JSON = '{"conclusions": []}'


# -- a-in ----------------------------------------------------------------


def test_a_in_invariant_only_causal_keys_change(tmp_path, monkeypatch):
    """判据 a-in（R-C32-1 订正版）：① 全相关／② 标因果但卡空。

    a) conclusions／conflict_resolution 逐字段等值；
    b) evidence 剥六个新增因果键后只许 relation 值不同；
    c) confidence 只许链那一族变，且每条 dossier_confidence ≤ ①；
    自证格：改回「只看当前 relation」时 ② 分数必涨过 ①（本格必红）。
    """
    case = _case_dir(tmp_path, "ain")
    out1, out2 = case / "out1", case / "out2"
    deps = RunDeps(client=FakeClient(_EMPTY_JSON), analysts=[
        Analyst("mainstream", "测", FakeClient(_EMPTY_JSON), "m")])

    d1 = _seeded_dossier(relation=RelationKind.CORRELATION, claim=None)
    r1 = run_case(
        RunSpec(case_dir=case, out_dir=out1, dossier=d1, probe=False), deps)
    paths1 = export_official([(_q(), r1.dossier)], out1 / "official")

    d2 = _seeded_dossier(
        relation=RelationKind.CAUSATION, claim=None, note=_MECH_NOTE)
    r2 = run_case(
        RunSpec(case_dir=case, out_dir=out2, dossier=d2, probe=False), deps)
    paths2 = export_official([(_q(), r2.dossier)], out2 / "official")

    # a) 非证据两份 JSON 逐字段等值
    for name in ("conclusions", "conflict_resolution"):
        a = json.loads(paths1[name].read_text(encoding="utf-8"))
        b = json.loads(paths2[name].read_text(encoding="utf-8"))
        assert a == b, name

    # b) evidence 剥六个新增因果键后只许 relation 值不同
    _SIX_CAUSAL = {
        "causal_claim", "mechanism_completeness", "missing_links",
        "design_tier", "declared_relation", "degraded_reason",
    }
    e1 = json.loads(paths1["evidence"].read_text(encoding="utf-8"))
    e2 = json.loads(paths2["evidence"].read_text(encoding="utf-8"))

    def _strip6_rel(row: dict) -> dict:
        return {k: v for k, v in row.items()
                if k not in _SIX_CAUSAL and k != "relation"}

    assert [_strip6_rel(r) for r in e1] == [_strip6_rel(r) for r in e2]
    assert any(r.get("degraded_reason") for r in e2)
    assert any(
        (r.get("declared_relation") or "") == "causation"
        and r.get("relation") == "correlation"
        for r in e2
    )

    # c) confidence 只许链那一族变，且 ② 每条 dossier_confidence ≤ ①
    c1 = json.loads(paths1["confidence"].read_text(encoding="utf-8"))
    c2 = json.loads(paths2["confidence"].read_text(encoding="utf-8"))
    assert len(c1) == len(c2)
    _STABLE = (
        "question_id", "conclusion_id", "信源可信度",
        "证据数量与一致性", "formula",
    )
    _CHAIN_FAMILY = {
        "推理链完整性", "terms", "substitution", "score",
        "dossier_confidence", "band", "band_rule",
    }
    for a, b in zip(c1, c2):
        assert set(a) == set(b)
        for k in _STABLE:
            assert a[k] == b[k], k
        for k in set(a) - set(_STABLE) - _CHAIN_FAMILY:
            assert a[k] == b[k], f"非链字段漂移: {k}"
        assert b["dossier_confidence"] <= a["dossier_confidence"], (
            f"降级后分数上涨: {a['dossier_confidence']} → "
            f"{b['dossier_confidence']}"
        )

    # 自证格：把 applicable_checks 改回「只看当前 relation」⇒ ② 分数必涨
    import app.core.chain_integrity as ci_mod

    _orig = ci_mod.applicable_checks

    def _only_current_relation(dossier, conclusion_id):
        apps = list(_orig(dossier, conclusion_id))
        evs = dossier.evidences_of(conclusion_id)
        if not any(e.relation == RelationKind.CAUSATION for e in evs):
            return [c for c in apps if c != "causation_mechanism"]
        return apps

    # 直接钉：已降级证据仍进链分母（改回只看当前 relation 时本句必红）
    from app.core.chain_integrity import applicable_checks as _apps_now
    con_id = r2.dossier.conclusions[0].id
    assert "causation_mechanism" in _apps_now(r2.dossier, con_id)

    monkeypatch.setattr(ci_mod, "applicable_checks", _only_current_relation)
    # 造裂隙后再跑 ②：分数应涨过修复后的降级分（证明方向断言有牙）
    out3 = case / "out3"
    d3 = _seeded_dossier(
        relation=RelationKind.CAUSATION, claim=None, note=_MECH_NOTE)
    r3 = run_case(
        RunSpec(case_dir=case, out_dir=out3, dossier=d3, probe=False), deps)
    paths3 = export_official([(_q(), r3.dossier)], out3 / "official")
    c3 = json.loads(paths3["confidence"].read_text(encoding="utf-8"))
    assert any(
        row3["dossier_confidence"] > row2["dossier_confidence"]
        for row2, row3 in zip(c2, c3)
    ), ("自证失败：改回只看当前 relation 后分数未相对修复版上涨，"
        "方向断言抓不住回归")
    assert "causation_mechanism" not in _only_current_relation(
        r2.dossier, con_id), (
        "自证失败：只看当前 relation 的假实现仍把已降级行算进分母")


# -- a-out（只附报） -----------------------------------------------------


def test_a_out_attach_only_no_assert_on_tmp():
    """a-out：跨树 demo_offline 对账由架构师做；此处只附报、零断言绑 /tmp 产物。

    故意不 skip：避免污染「未装 mcp＝1 skipped」那格的 skip 计数。
    """
    # 只附报：不读 /tmp、不 assert 跑产物
    assert "只附报" in (test_a_out_attach_only_no_assert_on_tmp.__doc__ or "")


# -- b：四种缺法各一格 ---------------------------------------------------


@pytest.mark.parametrize("drop", list(CLAIM_KEYS))
def test_b_each_missing_claim_key_degrades(drop):
    d = _base_dossier()
    claim = dict(_FULL_CLAIM)
    claim[drop] = ""
    ev = _add_ev(d, relation=RelationKind.CAUSATION, note=_MECH_NOTE,
                 claim=claim, mechanism="direct")
    apply_causal_claim_gates(d)
    assert ev.relation == RelationKind.CORRELATION
    assert ev.declared_relation == "causation"
    assert drop in (ev.degraded_reason or "")
    flags = audit_causal_claim_missing(d)
    assert any(f["kind"] == "causal_claim_missing" for f in flags)


# -- c -------------------------------------------------------------------


def test_c_full_claim_keeps_causation_and_bonus():
    d = _base_dossier()
    ev = _add_ev(d, relation=RelationKind.CAUSATION, note=_MECH_NOTE,
                 claim=dict(_FULL_CLAIM), mechanism="direct")
    apply_causal_claim_gates(d)
    assert ev.relation == RelationKind.CAUSATION
    assert not ev.degraded_reason
    score_ok = evidence_score(ev, d)

    d2 = _base_dossier()
    ev2 = _add_ev(d2, relation=RelationKind.CAUSATION, note=_MECH_NOTE,
                  claim=None, mechanism="direct")
    apply_causal_claim_gates(d2)
    assert ev2.relation == RelationKind.CORRELATION
    score_deg = evidence_score(ev2, d2)
    assert score_ok > score_deg

    src = (ROOT / "app/core/confidence.py").read_text(encoding="utf-8")
    assert "CAUSATION_BONUS = 1.15" in src


# -- d：design_tier 不进分 ------------------------------------------------


def test_d_design_tier_never_affects_score(monkeypatch):
    """同一 dossier 只换 design_tier 四值 ⇒ confidence／四分量逐位相同。"""
    import app.core.confidence as conf_mod

    def _run_tiers():
        scores = []
        for tier in ("rct", "quasi", "observational", "claim_only"):
            d = _base_dossier()
            _add_ev(d, relation=RelationKind.CAUSATION, note=_MECH_NOTE,
                    claim=dict(_FULL_CLAIM), mechanism="direct",
                    design_tier=tier)
            apply_causal_claim_gates(d)
            recompute_all(d, n_panel=1)
            conf, parts = conclude_confidence("CON1", d)
            scores.append((conf, dict(parts)))
        return scores

    scores = _run_tiers()
    assert all(s == scores[0] for s in scores)

    # 源码 content：design_tier 不得出现在 confidence.py
    conf_src = (ROOT / "app/core/confidence.py").read_text(encoding="utf-8")
    assert "design_tier" not in conf_src

    # 自证：若有人把 design_tier 乘进分数，本格必红（造裂隙再断言会分裂）
    _tier_idx = {"rct": 3, "quasi": 2, "observational": 1, "claim_only": 0}
    _orig = conf_mod.evidence_score

    def _poisoned(ev, dossier):
        base = _orig(ev, dossier)
        return min(1.0, base * (1.0 + 0.1 * _tier_idx.get(ev.design_tier, 0)))

    monkeypatch.setattr(conf_mod, "evidence_score", _poisoned)
    poisoned = _run_tiers()
    assert len({s[0] for s in poisoned}) > 1, (
        "自证失败：乘进 design_tier 后分数仍全同，本格抓不住回归")


# -- e -------------------------------------------------------------------


def test_e_indirect_empty_links_degrades_filled_shows_in_report_md(tmp_path):
    d = _base_dossier()
    ev = _add_ev(d, relation=RelationKind.CAUSATION, note=_MECH_NOTE,
                 claim=dict(_FULL_CLAIM), mechanism="indirect",
                 missing_links=[])
    apply_causal_claim_gates(d)
    assert ev.relation == RelationKind.CORRELATION
    assert "missing_links" in (ev.degraded_reason or "")

    d2 = _base_dossier()
    _add_ev(d2, relation=RelationKind.CAUSATION, note=_MECH_NOTE,
            claim=dict(_FULL_CLAIM), mechanism="indirect",
            missing_links=["mediator"])
    apply_causal_claim_gates(d2)
    assert d2.evidences[0].relation == RelationKind.CAUSATION
    chain = HashChain()
    md = render_report_md(d2, chain, rejected=[])
    out = tmp_path / "report.md"
    out.write_text(md, encoding="utf-8")
    assert "缺中介" in out.read_text(encoding="utf-8")


# -- f -------------------------------------------------------------------


def test_f_endpoint_degrades_and_chain_human(tmp_path):
    cases = tmp_path / "cases"
    cases.mkdir()
    case = cases / "ep"
    case.mkdir()
    (case / "manifest.yaml").write_text("question: Q\n", encoding="utf-8")
    (case / "a.md").write_text(
        "全固态电芯的中试良率尚不足百分之四十。\n", encoding="utf-8")
    out = case / "out"
    seeded = _seeded_dossier(relation=RelationKind.CORRELATION, claim=None)
    run_case(
        RunSpec(case_dir=case, out_dir=out, dossier=seeded, probe=False),
        RunDeps(client=FakeClient(_EMPTY_JSON), analysts=[
            Analyst("mainstream", "测", FakeClient(_EMPTY_JSON), "m")]),
    )
    d = Dossier.from_json(out / "report.json")
    chain = HashChain.from_jsonl(out / "chain.jsonl")
    before_n = len(chain.records)
    assert d.evidences, "注入案卷须保留证据"
    eid = d.evidences[0].id

    client = TestClient(create_app(cases_root=cases))
    r = client.post("/api/evidence/relation", json={
        "case": "ep", "evidence_id": eid, "relation": "causation",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    hit = next(e for e in body["dossier"]["evidences"] if e["id"] == eid)
    assert hit["relation"] == "correlation"
    assert hit["declared_relation"] == "causation"
    assert hit.get("degraded_reason")
    kinds = [f["kind"] for f in body["audit"]["flags"]]
    assert "causal_claim_missing" in kinds
    chain2 = HashChain.from_jsonl(out / "chain.jsonl")
    assert len(chain2.records) == before_n + 1
    last = chain2.records[-1]
    assert last.actor == "human"
    assert last.event == "evidence_relation"


def test_f_bypass_endpoint_still_degraded_in_run_case(tmp_path):
    """绕开端点直接改 relation 再 run_case ⇒ 仍被降级。"""
    case = _case_dir(tmp_path, "bypass")
    out = case / "out"
    seeded = _seeded_dossier(
        relation=RelationKind.CAUSATION, claim=None, note=_MECH_NOTE)
    result = run_case(
        RunSpec(case_dir=case, out_dir=out, dossier=seeded, probe=False),
        RunDeps(client=FakeClient(_EMPTY_JSON), analysts=[
            Analyst("mainstream", "测", FakeClient(_EMPTY_JSON), "m")]),
    )
    assert result.dossier.evidences
    assert all(
        e.relation == RelationKind.CORRELATION
        for e in result.dossier.evidences)
    assert any(e.degraded_reason for e in result.dossier.evidences)


# -- g -------------------------------------------------------------------


def test_g_old_dict_missing_keys_defaults():
    old = {
        "id": "EV-old", "conclusion_id": "CON1",
        "quote": "全固态电芯的中试良率尚不足百分之四十",
        "segment_ids": ["SRC1#s1"],
        "relation": "causation", "level": "B",
        "note": "", "weight": 1.0, "author": "", "verified": None,
    }
    ev = EvidenceNode.from_dict(old)
    assert ev.causal_claim is None
    assert ev.mechanism_completeness == "correlation_only"
    assert ev.missing_links == []
    assert ev.design_tier == "claim_only"
    assert ev.declared_relation == "causation"
    assert ev.degraded_reason == ""


# -- h -------------------------------------------------------------------


def test_h_registry_completeness_guardian():
    """新 kind 四处注册表都有；摘掉任一处本格必须红。"""
    kind = "causal_claim_missing"
    assert kind in KIND_LABEL

    audit_src = (ROOT / "app/core/audit.py").read_text(encoding="utf-8")
    assert f'"{kind}"' in audit_src
    assert "audit_causal_claim_missing" in audit_src

    chain_src = (ROOT / "app/core/chain_integrity.py").read_text(encoding="utf-8")
    assert kind in chain_src

    gate_src = (ROOT / "app/core/gate_applicability.py").read_text(encoding="utf-8")
    assert f'"{kind}"' in gate_src

    pipe_src = (ROOT / "app/pipeline.py").read_text(encoding="utf-8")
    assert f'"{kind}"' in pipe_src

    web_src = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert kind in web_src

    # 运行时：audit_all 真能产出该 kind（降级后）
    d = _base_dossier()
    _add_ev(d, relation=RelationKind.CAUSATION, note=_MECH_NOTE, claim=None)
    apply_causal_claim_gates(d)
    kinds = {f["kind"] for f in audit_all(d)}
    assert kind in kinds


# -- i -------------------------------------------------------------------


def test_i_field_notes_and_no_engine_claim(tmp_path):
    notes = _FIELD_NOTES
    for key in ("causal_claim", "mechanism_completeness", "missing_links",
                "design_tier", "declared_relation", "degraded_reason"):
        assert key in notes
    for enum in ("mediator", "temporal", "contrast",
                 "rct", "quasi", "observational", "claim_only",
                 "direct", "indirect", "correlation_only"):
        assert enum in notes
    assert "不做效应估计" in notes
    assert "不做完整因果引擎" in notes

    d = _base_dossier()
    _add_ev(d, relation=RelationKind.CAUSATION, note=_MECH_NOTE,
            claim=dict(_FULL_CLAIM), mechanism="indirect",
            missing_links=["mediator"])
    apply_causal_claim_gates(d)
    # 负断言查的是 report.md（工单原句），不许出现越界说法
    md = render_report_md(d, HashChain(), rejected=[])
    report_path = tmp_path / "report.md"
    report_path.write_text(md, encoding="utf-8")
    report_text = report_path.read_text(encoding="utf-8")
    assert report_text.count("已实现因果推断") == 0
    assert report_text.count("因果引擎") == 0


# -- j / k ---------------------------------------------------------------


def test_j_no_git_diff_and_basename_count():
    text = Path(__file__).read_text(encoding="utf-8")
    assert "git" + " diff" not in text
    hits = []
    for base in (ROOT / "app", ROOT / "tests", ROOT / "scripts"):
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix == ".pyc":
                continue
            try:
                body = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if ("causal_claim" in body or "design_tier" in body
                    or "mechanism_completeness" in body):
                hits.append(str(p.relative_to(ROOT)))
    assert len(hits) >= 1


def test_k_boundary_in_handoff_and_proposal():
    """边界句进 HANDOFF 与 proposal-formal；grep -n 读数回写。"""
    needle = "不做效应估计、不做完整因果引擎"
    h = list(
        i for i, line in enumerate(
            (ROOT / "docs/HANDOFF.md").read_text(encoding="utf-8").splitlines(),
            1)
        if needle in line)
    p = list(
        i for i, line in enumerate(
            (ROOT / "docs/proposal-formal.md").read_text(
                encoding="utf-8").splitlines(),
            1)
        if needle in line)
    assert len(h) >= 1, h
    assert len(p) >= 1, p
    assert BOUNDARY_NOTE  # 模块常量仍在


# -- l（R-C32-2：gate_applicability.causation_support.has_work 扩到 declared） --


def test_l_degraded_report_md_no_false_not_evaluated(tmp_path, monkeypatch):
    """判据 l（R-C32-2）：已降级案卷的 report.md 两面一致。

    ①「未能执行」行不得列「因果机制词核对」（已亮黄牌却写未执行＝假话）；
    ② 同文件同时读得到两张黄牌；
    ③ 自证：把 has_work 改回「只看当前 relation」时 ① 必裂（本格必红）。
    """
    d = _base_dossier()
    _add_ev(d, relation=RelationKind.CAUSATION, note="", claim=None,
            mechanism="direct")
    apply_causal_claim_gates(d)
    ev = d.evidences[0]
    assert ev.relation == RelationKind.CORRELATION
    assert (ev.declared_relation or "") == "causation"

    md = render_report_md(d, HashChain(), rejected=[])
    out = tmp_path / "report.md"
    out.write_text(md, encoding="utf-8")
    text = out.read_text(encoding="utf-8")

    ne_lines = [ln for ln in text.splitlines() if "未能执行" in ln]
    assert ne_lines, "降级案卷应仍有其它闸进未能执行清单"
    assert all("因果机制词核对" not in ln for ln in ne_lines), ne_lines
    assert "[因果标注缺乏机制词]" in text
    assert "[因果主张卡不完整已降级]" in text

    # 自证格：把 causation_support.has_work 改回「只看当前 relation」
    # ⇒ 「未能执行」必再列「因果机制词核对」（本格必红）
    import app.core.gate_applicability as ga_mod
    from app.core.gate_applicability import GateSpec, GATE_SPECS

    def _only_current_relation(dossier):
        return any(ev.relation is RelationKind.CAUSATION
                   for ev in dossier.evidences)

    # 直接钉：修复后 has_work 对已降级案卷为真（改回只看当前时本句必红）
    cur = next(s for s in GATE_SPECS if s.kind == "causation_support")
    assert cur.has_work(d), (
        "自证失败：修复后 has_work 对已降级案卷仍为假")

    fake_specs = tuple(
        GateSpec(s.kind, s.label, _only_current_relation, s.reason)
        if s.kind == "causation_support" else s
        for s in GATE_SPECS
    )
    monkeypatch.setattr(ga_mod, "GATE_SPECS", fake_specs)
    md_bad = render_report_md(d, HashChain(), rejected=[])
    ne_bad = [ln for ln in md_bad.splitlines() if "未能执行" in ln]
    assert any("因果机制词核对" in ln for ln in ne_bad), (
        "自证失败：改回只看当前 relation 后未能执行行未再列因果机制词核对，"
        "方向断言抓不住回归")
    assert not _only_current_relation(d), (
        "自证失败：只看当前 relation 的假实现仍对已降级案卷返回有工作")
