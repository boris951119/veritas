"""C-145a：VERITAS_CONFLICT_TRACE 出厂默认开——冒烟与行为守护。

默认开（未设 env）＝demo／冒烟必写出 conflict_trace.json（零对撞＝空态文件
＋真实题数原因句）；显式 env=0＝与改前关旗行为一致（键不写、文件不出现）。
判定／打分／选段／装箱零改动。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.export.official import export_official
from app.pipeline import RunSpec, run_case
from tests.test_c143_trace_report_face import (
    _case_dir, _deps, _dossier_with_numbers,
)


def _read_trace(official: Path) -> dict:
    tf = official / "conflict_trace.json"
    assert tf.exists(), "默认开必须写出 conflict_trace.json（含空态）"
    return json.loads(tf.read_text(encoding="utf-8"))


def test_a_default_on_demo_smoke_writes_file(monkeypatch, tmp_path):
    """默认开冒烟：demo 案零 LLM 全路径 → 回放面在场（含空态句）。"""
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    out = tmp_path / "out"
    r = run_case(
        RunSpec(case_dir=Path("cases") / "demo-solid-state",
                out_dir=out, probe=False),
        _deps())
    official = out / "official"
    export_official(
        [({"question_id": "q_demo", "question": r.dossier.question},
          r.dossier)],
        official)
    payload = _read_trace(official)
    assert payload.get("detail"), "回放面必须带 detail（空态也带原因句）"
    summary = payload.get("summary") or {}
    if not payload.get("records"):
        assert payload.get("empty_state") is True
        assert "1 题" in payload.get("detail", ""), "空态句须带真实题数"


def test_b_default_on_records_face(monkeypatch, tmp_path):
    """默认开行为腿：未设 env＋对撞夹具 → 键活过白名单＋处置行在场。"""
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    d = _dossier_with_numbers(["40%", "60%"])
    out = tmp_path / "out"
    r = run_case(
        RunSpec(case_dir=_case_dir(tmp_path), out_dir=out, dossier=d,
                probe=False),
        _deps())
    acc_trace = (r.dossier.accounting or {}).get("conflict_trace")
    assert isinstance(acc_trace, dict), "默认开必须写 accounting 键"
    assert acc_trace["summary"]["n"] >= 1, "夹具自证：台账对撞必须 ≥1 条"
    official = out / "official"
    paths = export_official(
        [({"question_id": "q1", "question": d.question}, r.dossier)],
        official)
    payload = _read_trace(official)
    row = payload["records"][0]
    assert row["conflict_class"] in {
        "same_window", "cross_day", "unknown_time", "unclassified"}
    assert row["disposition"] in {"keep", "dissent", "undecided"}


def test_c_env_zero_off_no_file(monkeypatch, tmp_path):
    """显式关＝与改前关旗行为一致：键不写、文件不出现（对撞夹具）。"""
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "0")
    d = _dossier_with_numbers(["40%", "60%"])
    out = tmp_path / "out"
    r = run_case(
        RunSpec(case_dir=_case_dir(tmp_path), out_dir=out, dossier=d,
                probe=False),
        _deps())
    assert "conflict_trace" not in (r.dossier.accounting or {})
    official = out / "official"
    paths = export_official(
        [({"question_id": "q1", "question": d.question}, r.dossier)],
        official)
    assert "conflict_trace" not in paths, "显式关不许出现回放面文件"
