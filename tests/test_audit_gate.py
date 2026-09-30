"""机械核对闸端到端：管线入链、报告警示段、工作台审计与人工修改亮灯。

覆盖第一批闸（前提/计算/溯源/守恒/质证仲裁引用）在真实管线与
HTTP 端点上的接线——零 key、零网络。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents.base import Analyst
from app.pipeline import run_case
from app.pipeline import RunDeps, RunSpec
from app.server import create_app

PANEL_JSON = """{"conclusions": [
  {"statement": "截至2026年3月，客户B回款率为40%，缺口768万元",
   "evidence": [{"quote": "合同金额1,280万元，累计回款512万元",
                 "segment_id": "SRC1#s1", "relation": "correlation",
                 "level": "B", "note": "计算:512/1280=40%；1280-512=768"}]}
]}"""


class FakeClient:
    def chat(self, model, messages, json_mode=False):
        return SimpleNamespace(content=PANEL_JSON)


@pytest.fixture
def case_dir(tmp_path):
    case_dir = tmp_path / "cases" / "demo"
    case_dir.mkdir(parents=True)
    (case_dir / "manifest.yaml").write_text(
        "question: 客户B的回款情况如何？\n"
        "sources:\n  - file: a.md\n    type: report\n", encoding="utf-8")
    (case_dir / "a.md").write_text(
        "# 台账\n\n客户B合同金额1,280万元，累计回款512万元，"
        "合同签订于2026年3月。\n", encoding="utf-8")
    return case_dir


def test_pipeline_audits_in_chain_and_report(case_dir):
    result = run_case(RunSpec(case_dir=case_dir, out_dir=case_dir / "out"),
                      RunDeps(client=FakeClient(),
                              analysts=[Analyst("mainstream", "测", FakeClient(), "m")]))
    events = {r.event for r in result.chain.records}
    assert {"premise_check", "numeric_audit", "discourse_audit"} <= events
    # 正确算式 + 数字全部可溯源 → 报告警示段亮绿灯
    assert "机械核对警示" in result.report_md
    assert "全部通过" in result.report_md
    assert result.chain.verify_chain().ok


def test_pipeline_flags_wrong_calculation(case_dir):
    """模型把 40% 心算成 45%：算式复算红牌 + 报告可见。"""
    bad = PANEL_JSON.replace("512/1280=40%", "512/1280=45%") \
                    .replace("回款率为40%", "回款率为45%")
    class BadClient:
        def chat(self, model, messages, json_mode=False):
            return SimpleNamespace(content=bad)

    result = run_case(RunSpec(case_dir=case_dir, out_dir=case_dir / "out"),
                      RunDeps(client=BadClient(),
                              analysts=[Analyst("mainstream", "测", BadClient(), "m")]))
    md = result.report_md
    assert "🔴" in md and "复算不符" in md
    audit = [f for f in _audit_of(result) if f["kind"] == "calc"]
    assert audit and audit[0]["severity"] == "high"


def _audit_of(result) -> list[dict]:
    from app.core.audit import audit_all

    return audit_all(result.dossier)


@pytest.fixture
def client(case_dir):
    single = [Analyst("mainstream", "测", FakeClient(), "m")]
    run_case(RunSpec(case_dir=case_dir, out_dir=case_dir / "out"),
             RunDeps(client=FakeClient(), analysts=single))
    app = create_app(cases_root=case_dir.parent)
    return TestClient(app), case_dir


def test_dossier_payload_carries_audit(client):
    api, _ = client
    data = api.get("/api/dossier", params={"case": "demo"}).json()
    assert "audit" in data
    assert data["audit"]["n_flags"] == len(data["audit"]["flags"])
    assert data["audit"]["n_high"] == 0


def test_human_edit_introducing_outside_number_flags(client):
    """人工把结论改成含来源外数字：修改照常入链，但 op.flags 当场亮黄灯，
    且下次读取的 audit 里带着 human_edit 标记（警示不消失）。"""
    api, case_dir = client
    data = api.get("/api/dossier", params={"case": "demo"}).json()
    con_id = data["dossier"]["conclusions"][0]["id"]

    resp = api.post("/api/conclusion/edit", json={
        "case": "demo", "conclusion_id": con_id,
        "statement": "客户B回款率40%，另有坏账300万元"}).json()
    assert resp["op"]["n_new_flags"] >= 1
    assert any(f["kind"] == "provenance" and f.get("human_edit")
               for f in resp["op"]["flags"])
    # 链事件带审计计数
    chain_line = (case_dir / "out" / "chain.jsonl").read_text(
        encoding="utf-8").strip().splitlines()[-1]
    assert "conclusion_edit" in chain_line and "n_new_flags" in chain_line
    # 派生视图：重新读取仍能看到该来源外数字警示
    after = api.get("/api/dossier", params={"case": "demo"}).json()
    assert any(f["kind"] == "provenance" and f["value"] == "300万"
               for f in after["audit"]["flags"])
