"""研判进度：落盘 progress.json + 管线各环节耗时。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.core.run_progress import (
    RunProgress, STEP_LABELS, ensure_progress, get_active_progress,
    set_active_progress,
)
from types import SimpleNamespace

from app.agents.base import Analyst
from app.pipeline import RunDeps, RunSpec, run_case


class _FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.call_log: list = []
        self.total_tokens_used = 0

    def chat(self, model, messages, json_mode=False):
        self.call_log.append({"model": model})
        return SimpleNamespace(content=self.content)


_PANEL_JSON = """{"conclusions": [
  {"statement": "能量密度占优",
   "evidence": [{"quote": "能量密度显著高于液态锂离子电池",
                 "segment_id": "SRC1#s1",
                 "relation": "correlation", "level": "A", "note": "直接引证"}]}
]}"""


def test_run_progress_stages_and_elapsed(tmp_path: Path):
    set_active_progress(None)
    prog = RunProgress(tmp_path)
    with prog.stage("ingest", hint="1/2 a.pdf"):
        time.sleep(0.05)
        prog.note(file="a.pdf", index=1, total=2)
    with prog.stage("material"):
        time.sleep(0.02)
        prog.note(n_selected=3, n_total=10)
    prog.complete(elapsed_s=0.1)

    path = tmp_path / "progress.json"
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["step"] == "done"
    assert data["elapsed_s"] >= 0.05
    ids = [s["id"] for s in data["steps"]]
    assert ids == ["ingest", "material", "done"]
    ingest = data["steps"][0]
    assert ingest["status"] == "done"
    assert ingest["elapsed_s"] >= 0.05
    assert ingest["label"] == STEP_LABELS["ingest"]
    assert ingest["detail"]["file"] == "a.pdf"
    assert data["steps"][1]["detail"]["n_selected"] == 3


def test_ensure_progress_reuses_active(tmp_path: Path):
    set_active_progress(None)
    a = ensure_progress(tmp_path)
    b = ensure_progress(tmp_path / "other")
    assert a is b
    assert get_active_progress() is a
    set_active_progress(None)


def test_progress_api_without_report(tmp_path: Path):
    """开跑瞬间只有 progress.json，接口仍应可读。"""
    from fastapi.testclient import TestClient

    from app.server import create_app

    case = tmp_path / "c1"
    out = case / "out_offline"
    out.mkdir(parents=True)
    (case / "manifest.yaml").write_text("question: q\nsources: []\n",
                                        encoding="utf-8")
    (out / "progress.json").write_text(json.dumps({
        "step": "ingest", "elapsed_s": 1.2,
        "steps": [{"id": "ingest", "label": "读取资料并切片",
                   "status": "running", "elapsed_s": 1.2}],
    }), encoding="utf-8")
    client = TestClient(create_app(cases_root=tmp_path))
    r = client.get("/api/progress", params={"case": "c1", "out": "out_offline"})
    assert r.status_code == 200
    assert r.json()["step"] == "ingest"
    assert r.json()["steps"][0]["elapsed_s"] == 1.2


def test_pipeline_writes_step_timings(tmp_path: Path):
    """离线桩跑完整管线 → progress.json 含读取切片/BM25/分析师等环节秒数。"""
    set_active_progress(None)
    (tmp_path / "manifest.yaml").write_text(
        "question: 固态电池能量密度如何？\n"
        "sources:\n  - file: a.md\n    type: paper\n",
        encoding="utf-8",
    )
    (tmp_path / "a.md").write_text(
        "# 摘要\n\n本次测评显示固态电池的能量密度显著高于液态锂离子电池。\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    fake = _FakeClient(_PANEL_JSON)
    single = [Analyst("mainstream", "测试角色", fake, "test-model")]
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=out),
        RunDeps(client=fake, analysts=single),
    )
    assert (out / "progress.json").is_file()
    prog = json.loads((out / "progress.json").read_text(encoding="utf-8"))
    assert prog["step"] == "done"
    step_ids = [s["id"] for s in prog["steps"] if s["id"] != "done"]
    for need in ("ingest", "hygiene", "material", "panel", "citation",
                 "finalize", "chair"):
        assert need in step_ids, f"missing step {need}: {step_ids}"
    for s in prog["steps"]:
        if s["id"] == "done":
            continue
        assert s["status"] == "done"
        assert isinstance(s["elapsed_s"], (int, float))
        assert s["elapsed_s"] >= 0
    material = next(s for s in prog["steps"] if s["id"] == "material")
    assert material["label"] == STEP_LABELS["material"]
    assert "n_selected" in (material.get("detail") or {})
    ingest = next(s for s in prog["steps"] if s["id"] == "ingest")
    assert ingest["detail"].get("n_sources", 0) >= 1
    steps = (result.dossier.accounting or {}).get("steps") or []
    assert any(s.get("id") == "material" for s in steps)
    assert get_active_progress() is None
