"""契约 E：人机闭环 HTTP（改结论 / 推翻裁决 + human 入链）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents.base import Analyst
from app.core.conflicts import ConflictPair, Resolution, apply_resolution
from app.core.evidence import Dossier
from app.pipeline import run_case
from app.pipeline import RunDeps, RunSpec
from app.server import create_app

PANEL_JSON = """{"conclusions": [
  {"statement": "结论甲偏乐观",
   "evidence": [{"quote": "全固态电芯的中试良率尚不足百分之四十",
                 "segment_id": "SRC1#s1", "relation": "correlation",
                 "level": "B", "note": "x"}]},
  {"statement": "结论乙偏悲观",
   "evidence": [{"quote": "能量密度显著高于传统液态锂离子电池",
                 "segment_id": "SRC1#s1", "relation": "correlation",
                 "level": "A", "note": "y"}]}
]}"""


class FakeClient:
    def chat(self, model, messages, json_mode=False):
        return SimpleNamespace(content=PANEL_JSON)


@pytest.fixture
def case_app(tmp_path):
    cases_root = tmp_path / "cases"
    case_dir = cases_root / "demo"
    case_dir.mkdir(parents=True)
    (case_dir / "manifest.yaml").write_text(
        "question: Q\n"
        "sources:\n  - file: a.md\n    type: paper\n", encoding="utf-8")
    (case_dir / "a.md").write_text(
        "# 摘要\n\n全固态电芯的中试良率尚不足百分之四十。"
        "能量密度显著高于传统液态锂离子电池。\n", encoding="utf-8")
    single = [Analyst("mainstream", "测", FakeClient(), "m")]
    run_case(RunSpec(case_dir=case_dir, out_dir=case_dir / "out"),
             RunDeps(client=FakeClient(), analysts=single))
    # 人工注入一条已消解冲突，供 override 测
    dossier = Dossier.from_json(case_dir / "out" / "report.json")
    maj = [c for c in dossier.conclusions if c.status == "majority"
           and dossier.evidences_of(c.id)]
    if len(maj) >= 2:
        pair = ConflictPair(
            id="CFL-http", a_id=maj[0].id, b_id=maj[1].id, topic="t",
            resolution=Resolution(winner_id=maj[0].id, rationale="初裁"))
        apply_resolution(pair, dossier)
        dossier.conflicts = [pair.to_dict()]
        dossier.to_json(case_dir / "out" / "report.json")
    app = create_app(cases_root=cases_root)
    return TestClient(app), "demo", dossier


def test_http_edit_conclusion_and_chain(case_app):
    """深化后：POST /api/conclusion/edit 改文案并以 human 事件入链。"""
    client, case, dossier = case_app
    cid = next(c.id for c in dossier.conclusions if c.status == "majority")
    r = client.post("/api/conclusion/edit", json={
        "case": case, "conclusion_id": cid, "statement": "人工改写结论",
    })
    assert r.status_code == 200
    body = r.json()
    updated = next(c for c in body["dossier"]["conclusions"] if c["id"] == cid)
    assert updated["statement"] == "人工改写结论"
    synth = body["dossier"]["synthesis"]
    blob = synth["headline"] + "".join(p["gloss"] for p in synth.get("points") or [])
    assert "人工改写结论" in blob
    assert any("人工修改" in n for n in (synth.get("gate_notes") or []))
    chain_path = None
    # 再读 dossier 确认；chain 事件通过再次校验接口旁证：落盘后 verify 仍 ok
    r2 = client.get("/api/dossier", params={"case": case})
    assert r2.status_code == 200
    assert r2.json()["chain"]["ok"] is True


def test_http_override_conflict(case_app):
    """深化后：POST /api/conflict/override 可改胜方并反映到 dossier。"""
    client, case, dossier = case_app
    if not dossier.conflicts:
        pytest.skip("案例不足两条结论，无法构造冲突")
    pair = dossier.conflicts[0]
    loser = pair["b_id"] if pair["resolution"]["winner_id"] == pair["a_id"] \
        else pair["a_id"]
    r = client.post("/api/conflict/override", json={
        "case": case, "conflict_id": pair["id"], "winner_id": loser,
    })
    assert r.status_code == 200
    body = r.json()
    stored = next(c for c in body["dossier"]["conflicts"] if c["id"] == pair["id"])
    assert stored["resolution"]["winner_id"] == loser


def test_http_edit_unknown_conclusion_404(case_app):
    """深化后：不存在的结论 id 返回 404，detail 指明结论缺失（非路由 Not Found）。"""
    client, case, _ = case_app
    r = client.post("/api/conclusion/edit", json={
        "case": case, "conclusion_id": "CON-nope", "statement": "x",
    })
    assert r.status_code == 404
    detail = str(r.json().get("detail") or "")
    assert "结论" in detail or "CON-nope" in detail
