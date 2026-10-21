"""C-13：结论依赖边＋中间结论层＋依赖传播（判据 a–l）。

ScriptedClient 复用 tests.test_collab（不复制第四份）。零真模型。
"""

from __future__ import annotations

import json
import signal
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.base import Analyst
from app.core.confidence import conclude_confidence
from app.core.dependency import (
    NOTE_AB,
    NOTE_FAILED,
    NOTE_NARROW,
    affected_downstream,
    apply_validated_edges,
    extract_dependencies,
    refresh_premise_broken,
    validate_dependency_edge,
)
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    Segment,
    Source,
    SourceType,
)
from app.core.reasoning_graph import build_reasoning_graph
from app.pipeline import RunDeps, RunSpec, render_report_md, run_case
from app.server import create_app
from tests.test_agents_pipeline import GOOD_BAD_JSON
from tests.test_collab import ScriptedClient

ROOT = Path(__file__).resolve().parents[1]


def _src_dossier(*stmts: str) -> Dossier:
    d = Dossier(question="Q", panel=["a0", "a1"])
    src = Source.create("T", SourceType.PAPER, credibility=0.8, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="全固态电芯的中试良率尚不足百分之四十。",
        locator="段 1"))
    d.add_source(src)
    for i, stmt in enumerate(stmts):
        cid = f"CON-{chr(ord('A') + i)}"
        con = Conclusion.create(stmt, author=f"a{i % 2}", id=cid)
        d.conclusions.append(con)
        d.add_evidence(EvidenceNode.create(
            cid, "全固态电芯的中试良率尚不足百分之四十",
            ["SRC1#s1"], level=EvidenceLevel.B, id=f"EV-{chr(ord('A') + i)}"))
    return d


# -- a ------------------------------------------------------------------


def test_a_five_illegal_edges_each_disclosed():
    d = _src_dossier("甲", "乙", "丙")
    d.conclusion("CON-C").status = "merged"
    raw = [
        {"from": "CON-A", "to": "CON-NOPE", "why": "缺 id"},
        {"from": "CON-A", "to": "CON-A", "why": "自环"},
        {"from": "CON-A", "to": "CON-B", "why": "先落合法再造二节点环"},
        {"from": "CON-B", "to": "CON-A", "why": "二节点环"},
        {"from": "CON-B", "to": "CON-C", "why": "指向 merged"},
    ]
    # 三节点环单独：A←B←C←A
    d2 = _src_dossier("甲", "乙", "丙", "丁")
    # 先合法 A←B、B←C，再 C←A 成三环——用 validate 单条即可
    d2.conclusion("CON-B").depends_on = ["CON-A"]
    d2.conclusion("CON-C").depends_on = ["CON-B"]
    r3 = validate_dependency_edge(d2, "CON-A", "CON-C")
    assert r3 is not None and "成环" in r3

    accepted, disclosures = apply_validated_edges(d, raw)
    # 合法那条 CON-A→CON-B 应留下；其余四拒
    assert any(e["from"] == "CON-A" and e["to"] == "CON-B" for e in accepted)
    kinds = "｜".join(disclosures)
    assert "id 不存在" in kinds
    assert "自环" in kinds
    assert "成环" in kinds
    assert "majority" in kinds  # 指向 merged 的拒收文案必含 majority 要求
    assert any("merged" in d for d in disclosures)
    # 脏边不进 depends_on
    assert "CON-NOPE" not in d.conclusion("CON-A").depends_on
    assert "CON-A" not in d.conclusion("CON-A").depends_on
    assert "CON-C" not in (d.conclusion("CON-B").depends_on or [])
    # 五种拒收各至少一条披露（含上面三节点环那条）
    assert len(disclosures) >= 4
    assert r3 not in (None, "")


# -- b ------------------------------------------------------------------


def test_b_extract_exception_zero_edges_run_case(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        "question: 固态电池 2030 能否规模上车？\n"
        "sources:\n  - file: a.md\n    type: paper\n", encoding="utf-8")
    (tmp_path / "a.md").write_text(
        "# 摘要\n\n本次测评显示固态电池的能量密度显著高于液态锂离子电池，"
        "但成本仍高于预期。\n", encoding="utf-8")
    # 分析师一次成功；依赖抽取抛异常
    client = ScriptedClient([GOOD_BAD_JSON, RuntimeError("依赖抽取失败")])
    single = [Analyst("mainstream", "测", client, "m")]
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out", probe=False),
        RunDeps(client=client, analysts=single))
    assert (tmp_path / "out" / "report.json").is_file()
    assert (tmp_path / "out" / "report.md").is_file()
    dep = (result.dossier.accounting or {}).get("dependency") or {}
    assert dep.get("n_edges") == 0
    blob = "｜".join(str(x) for x in (dep.get("disclosures") or []))
    assert dep.get("note") == NOTE_FAILED
    assert NOTE_FAILED in blob
    g = build_reasoning_graph(result.dossier)
    assert "nodes" in g and "edges" in g
    assert not any(e["kind"] == "depends_on" for e in g["edges"])


# -- c ------------------------------------------------------------------


def test_c_transitive_closure_chain_and_diamond():
    d = _src_dossier("A", "B", "C", "D")
    # A←B←C←D（D 依赖 C …）
    d.conclusion("CON-B").depends_on = ["CON-A"]
    d.conclusion("CON-C").depends_on = ["CON-B"]
    d.conclusion("CON-D").depends_on = ["CON-C"]
    assert affected_downstream("CON-A", d) == ["CON-B", "CON-C", "CON-D"]

    d2 = _src_dossier("A", "B", "C", "D")
    # 菱形 A←B、A←C、B←D、C←D
    d2.conclusion("CON-B").depends_on = ["CON-A"]
    d2.conclusion("CON-C").depends_on = ["CON-A"]
    d2.conclusion("CON-D").depends_on = ["CON-B", "CON-C"]
    out = affected_downstream("CON-A", d2)
    assert out == ["CON-B", "CON-C", "CON-D"]
    assert out.count("CON-D") == 1


# -- d ------------------------------------------------------------------


def test_d_cycle_protection_terminates():
    d = _src_dossier("A", "B", "C")
    # 绕过校验直接塞环
    d.conclusion("CON-A").depends_on = ["CON-C"]
    d.conclusion("CON-B").depends_on = ["CON-A"]
    d.conclusion("CON-C").depends_on = ["CON-B"]

    def _boom(signum, frame):
        raise TimeoutError("affected_downstream 未在时限内终止")

    old = signal.signal(signal.SIGALRM, _boom)
    signal.alarm(2)
    try:
        out = affected_downstream("CON-A", d)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    assert len(out) == len(set(out))
    assert set(out) <= {"CON-A", "CON-B", "CON-C"}
    assert "CON-A" not in out  # 不含种子自身


# -- e ------------------------------------------------------------------


def _http_case(tmp_path):
    cases = tmp_path / "cases"
    case_dir = cases / "demo"
    out = case_dir / "out"
    out.mkdir(parents=True)
    d = _src_dossier("甲前提", "乙依赖甲", "丙旁支")
    d.conclusion("CON-B").depends_on = []
    from app.core.hashchain import HashChain
    d.to_json(out / "report.json")
    HashChain().to_jsonl(out / "chain.jsonl")
    api = TestClient(create_app(cases_root=cases))
    return api, "demo", d, out


def test_e_api_depends_add_and_reject_cycle(tmp_path):
    api, case, _d, out = _http_case(tmp_path)
    chain0 = (out / "chain.jsonl").read_text(encoding="utf-8").count("\n")
    r = api.post("/api/conclusion/depends", json={
        "case": case, "from": "CON-B", "to": "CON-A", "action": "add",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    b = next(c for c in body["dossier"]["conclusions"] if c["id"] == "CON-B")
    assert "CON-A" in b["depends_on"]
    chain1 = (out / "chain.jsonl").read_text(encoding="utf-8")
    assert "conclusion_depends" in chain1
    assert chain1.count("\n") > chain0
    # 重载仍在
    reloaded = Dossier.from_json(out / "report.json")
    assert "CON-A" in reloaded.conclusion("CON-B").depends_on

    # 再加会成环的边：B←A（A 依赖 B）而 B 已依赖 A
    n_before = len(chain1.splitlines())
    r2 = api.post("/api/conclusion/depends", json={
        "case": case, "from": "CON-A", "to": "CON-B", "action": "add",
    })
    assert r2.status_code == 422
    chain2 = (out / "chain.jsonl").read_text(encoding="utf-8")
    assert len(chain2.splitlines()) == n_before
    # 边未写入
    reloaded2 = Dossier.from_json(out / "report.json")
    assert "CON-B" not in reloaded2.conclusion("CON-A").depends_on


# -- f ------------------------------------------------------------------


def test_f_upstream_evidence_cleared_marks_broken_keeps_downstream(tmp_path):
    api, case, _d, out = _http_case(tmp_path)
    # 先加边 B←A
    r = api.post("/api/conclusion/depends", json={
        "case": case, "from": "CON-B", "to": "CON-A", "action": "add",
    })
    assert r.status_code == 200
    # 删上游 A 全部证据
    r2 = api.post("/api/evidence/remove", json={
        "case": case, "evidence_id": "EV-A",
    })
    assert r2.status_code == 200, r2.text
    body = r2.json()
    cons = {c["id"]: c for c in body["dossier"]["conclusions"]}
    assert "CON-B" in cons  # 下游仍在
    assert "CON-A" in cons["CON-B"].get("premise_broken", [])
    md = render_report_md(
        Dossier.from_json(out / "report.json"),
        __import__("app.core.hashchain", fromlist=["HashChain"]).HashChain.from_jsonl(
            out / "chain.jsonl"),
        [])
    assert "前提失效" in md
    assert "CON-A" in md


# -- g ------------------------------------------------------------------


def test_g_depends_does_not_change_confidence():
    d = _src_dossier("甲", "乙")
    before = {
        c.id: conclude_confidence(c.id, d, n_panel=2)
        for c in d.conclusions
    }
    d.conclusion("CON-B").depends_on = ["CON-A"]
    mid = {
        c.id: conclude_confidence(c.id, d, n_panel=2)
        for c in d.conclusions
    }
    d.conclusion("CON-B").depends_on = []
    after = {
        c.id: conclude_confidence(c.id, d, n_panel=2)
        for c in d.conclusions
    }
    for cid in before:
        assert mid[cid][0] == before[cid][0]
        assert mid[cid][1] == before[cid][1]
        assert after[cid][0] == before[cid][0]
        assert after[cid][1] == before[cid][1]


# -- h / h′ -------------------------------------------------------------


def test_h_reasoning_graph_regression_shape():
    from tests.test_reasoning_graph import _base_dossier, _EDGE_KINDS, _NODE_KINDS

    d = _base_dossier()
    g = build_reasoning_graph(d)
    for n in g["nodes"]:
        assert n["kind"] in _NODE_KINDS
        if n["kind"] == "conclusion":
            assert "is_premise" in n
            # 无 depends_on 时均为 False
            assert n["is_premise"] is False
        else:
            assert "is_premise" not in n
    for e in g["edges"]:
        assert e["kind"] in (_EDGE_KINDS | {"depends_on"})
        # 本夹具无依赖边
        assert e["kind"] != "depends_on"

    # 加边后只允许多 depends_on 边与 is_premise 真值变化
    d.conclusion("CON-1").depends_on = ["CON-0"]
    g2 = build_reasoning_graph(d)
    new_kinds = {e["kind"] for e in g2["edges"]} - {e["kind"] for e in g["edges"]}
    assert new_kinds <= {"depends_on"}
    prem = [n for n in g2["nodes"] if n["id"] == "CON-0"][0]
    assert prem.get("is_premise") is True
    assert not any(n.get("kind") == "intermediate" for n in g2["nodes"])


def test_h_prime_reasoning_graph_test_count_unchanged():
    n = int(subprocess.run(
        ["grep", "-c", "^def test_", "tests/test_reasoning_graph.py"],
        cwd=ROOT, text=True, capture_output=True,
    ).stdout.strip())
    assert n == 6


# -- i ------------------------------------------------------------------


def test_i_old_dict_from_dict_defaults():
    legacy = {
        "id": "CON-x", "statement": "旧形态",
        "author": "a", "authors": [], "group_id": "",
        "status": "majority", "evidence_ids": [],
        "confidence": 0.1, "confidence_parts": {}, "dissent": [],
        # 无 depends_on / premise_broken
    }
    con = Conclusion.from_dict(legacy)
    assert con.depends_on == []
    assert con.premise_broken == []


# -- j ------------------------------------------------------------------


def test_j_c25_instant_stat_assert_gone():
    """#87：C-25 不得再常驻「对 app/ 瞬时状态」断言；面字面用拼接避免本文件触 k。"""
    needle = "git" + " diff --stat app/"
    text = (ROOT / "tests/test_c25_errors_sensitivity.py").read_text(
        encoding="utf-8")
    assert text.count(needle) == 0
    n2 = int(subprocess.run(
        ["grep", "-c", "本文件仅含", "app/core/evidence.py"],
        cwd=ROOT, text=True, capture_output=True,
    ).stdout.strip() or "0")
    assert n2 == 0


# -- k ------------------------------------------------------------------


def test_k_no_instant_vcs_stat_assert_in_this_file():
    needle = "git" + " diff"
    text = Path(__file__).read_text(encoding="utf-8")
    assert text.count(needle) == 0


# -- l ------------------------------------------------------------------


def test_l_render_wording_true_in_report_md():
    d = _src_dossier("甲", "乙")
    d.conclusion("CON-B").depends_on = ["CON-A"]
    d.accounting["dependency"] = {
        "n_edges": 1,
        "accepted": [{"from": "CON-B", "to": "CON-A", "why": "测"}],
        "rejected": [],
        "disclosures": [NOTE_NARROW, NOTE_AB],
        "note": NOTE_AB,
    }
    # 上游失效
    for ev in list(d.evidences_of("CON-A")):
        d.remove_evidence(ev.id)
    d.conclusion("CON-A").confidence = 0.0
    refresh_premise_broken(d)
    from app.core.hashchain import HashChain
    md = render_report_md(d, HashChain(), [])
    assert NOTE_NARROW in md
    assert NOTE_AB in md
    assert "/api/conclusion/depends" in md
    assert "report.md" in md  # 点名工件，不用「本文件」
    assert "本文件" not in md
    assert "前提失效" in md
    # 不许写成「已实现中间推理层」
    assert "已实现中间推理层" not in md


def test_p_in_scripted_extract_builds_premise_nodes():
    """架构师 p-in：ScriptedClient 喂固定边 → depends_on≥1、is_premise≥1。"""
    d = _src_dossier("甲", "乙", "丙")
    payload = json.dumps({
        "edges": [
            {"from": "CON-B", "to": "CON-A", "why": "乙以甲为前提"},
            {"from": "CON-C", "to": "CON-A", "why": "丙以甲为前提"},
        ]
    })
    client = ScriptedClient([payload])
    rec = extract_dependencies(d, client, "m")
    assert rec["n_edges"] >= 1
    assert NOTE_AB in "｜".join(rec.get("disclosures") or [])
    g = build_reasoning_graph(d)
    assert any(e["kind"] == "depends_on" for e in g["edges"])
    assert any(n.get("is_premise") for n in g["nodes"] if n["kind"] == "conclusion")


def test_source_guards_no_sleep_no_score_official_touch():
    src = (ROOT / "app/core/dependency.py").read_text(encoding="utf-8")
    assert "sleep(" not in src
    n = int(subprocess.run(
        ["grep", "-c", "def build_reasoning_graph(", "app/core/reasoning_graph.py"],
        cwd=ROOT, text=True, capture_output=True,
    ).stdout.strip())
    assert n == 1
