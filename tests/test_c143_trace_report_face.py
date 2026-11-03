"""C-143：树22 冲突留痕可用化——借 C-123 两处窄修（只动出口面）。

窄修①＝app/pipeline.py 两处 kept 白名单登记 conflict_trace（键活到产物；
旗关时该键根本不写入 accounting，登记零差异）。
窄修②＝app/export/official.py 旗开必写回放面（空态也写＋真实题数原因句：
「本次未检出」不等于「资料无冲突」，零对撞静默＝两态在产物面上同形）。
判定／打分／选段／装箱零改动；VERITAS_CONFLICT_TRACE 出厂默认仍关。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.agents.base import Analyst
from app.config import Settings
from app.core.conflict_trace import (
    apply_conflict_trace,
    conflict_trace_enabled,
)
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.export.official import export_official
from app.pipeline import RunDeps, RunSpec, run_case
from tests.test_agents_pipeline import FakeClient

_EMPTY_JSON = '{"conclusions": []}'


# ------------------------------------------------ 夹具


def _dossier_with_numbers(values: list[str]) -> Dossier:
    """每源正文互异；同主体同指标不同值 → 事实台账对撞（真走 _scan）。"""
    d = Dossier(question="客户B的回款情况如何？")
    for i, v in enumerate(values):
        src = Source.create(f"料{i}", SourceType.REPORT, id=f"SRC{i}")
        src.segments.append(Segment(
            id=f"SRC{i}#s1", source_id=f"SRC{i}",
            text=f"客户B回款率{v}。材料补充说明，用于占位。",
            index=0))
        d.add_source(src)
    return d


def _case_dir(tmp_path: Path, name: str = "c143") -> Path:
    case = tmp_path / name
    case.mkdir(parents=True)
    (case / "manifest.yaml").write_text(
        "question: 客户B的回款情况如何？\ntitle: C-143\n", encoding="utf-8")
    return case


def _q() -> dict:
    return {"question_id": "q1", "question": "客户B的回款情况如何？"}


def _deps() -> RunDeps:
    return RunDeps(client=FakeClient(_EMPTY_JSON), analysts=[
        Analyst("mainstream", "测", FakeClient(_EMPTY_JSON), "m")])


# ------------------------------------------------ 守护格


def test_a_factory_default_off(monkeypatch):
    """出厂默认仍关（未经 Boyu 拍板不改默认开）。"""
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    assert Settings().conflict_trace is False
    assert Settings.from_env().conflict_trace is False
    assert conflict_trace_enabled() is False


def test_b_both_whitelists_carry_trace_key():
    """两处 kept 白名单都登记（K1／K2 两把刀的常驻牙）。"""
    src = Path("app/pipeline.py").read_text(encoding="utf-8")
    anchor = "kept = {k: v for k, v in (dossier.accounting or {}).items()"
    spots: list[int] = []
    i = src.find(anchor)
    while i >= 0:
        spots.append(i)
        i = src.find(anchor, i + 1)
    assert len(spots) == 2, f"kept 白名单锚点数变了：{len(spots)}"
    for n, i in enumerate(spots, 1):
        tail = src[i:i + 1600]
        assert '"conflict_trace"' in tail, f"第 {n} 处 kept 白名单未登记" \
            " conflict_trace（注释不算，须是带引号的键字面量）"


def test_c_full_path_flag_on_records_survive_to_report_face(
        monkeypatch, tmp_path):
    """窄修①行为腿：旗开＋真对撞 → 键活过白名单、回放面写出处置行。"""
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "1")
    d = _dossier_with_numbers(["40%", "60%"])
    out = tmp_path / "out"
    r = run_case(
        RunSpec(case_dir=_case_dir(tmp_path), out_dir=out, dossier=d,
                probe=False),
        _deps())
    acc_trace = (r.dossier.accounting or {}).get("conflict_trace")
    assert isinstance(acc_trace, dict), "conflict_trace 键没活过 kept 白名单"
    assert acc_trace["summary"]["n"] >= 1, "夹具自证：台账对撞必须 ≥1 条"
    paths = export_official([(_q(), r.dossier)], out / "official")
    tf = paths["conflict_trace"]
    payload = json.loads(tf.read_text(encoding="utf-8"))
    assert payload["summary"]["n"] >= 1
    row = payload["records"][0]
    assert row["conflict_class"] in {
        "same_window", "cross_day", "unknown_time", "unclassified"}
    assert row["disposition"] in {"keep", "dissent", "undecided"}


def test_d_empty_state_written_with_real_count(monkeypatch, tmp_path):
    """窄修②：零对撞也写空态文件＋真实题数原因句（K4／K5 的牙）。"""
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "1")
    d = _dossier_with_numbers(["40%"])  # 单源单值＝零对撞
    out = tmp_path / "out"
    r = run_case(
        RunSpec(case_dir=_case_dir(tmp_path), out_dir=out, dossier=d,
                probe=False),
        _deps())
    assert "conflict_trace" not in (r.dossier.accounting or {}) or (
        r.dossier.accounting["conflict_trace"]["summary"]["n"] == 0
    ), "夹具自证：单源夹具不该长出对撞留痕"
    paths = export_official([(_q(), r.dossier)], out / "official")
    payload = json.loads(paths["conflict_trace"].read_text(encoding="utf-8"))
    assert payload["records"] == []
    assert payload["empty_state"] is True
    assert payload["summary"]["n"] == 0
    assert "1 题" in payload["detail"], "空态原因句须带真实题数（runs 长度）"
    assert "不等于资料无冲突" in payload["detail"]


def test_e_flag_off_no_key_no_file(monkeypatch, tmp_path):
    """关旗＝与改前行为一致：键不写、文件不出现（含台账对撞夹具）。"""
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "0")
    d = _dossier_with_numbers(["40%", "60%"])
    out = tmp_path / "out"
    r = run_case(
        RunSpec(case_dir=_case_dir(tmp_path), out_dir=out, dossier=d,
                probe=False),
        _deps())
    assert "conflict_trace" not in (r.dossier.accounting or {})
    assert apply_conflict_trace(d, collisions=[], enabled=False) is None
    paths = export_official([(_q(), r.dossier)], out / "official")
    assert "conflict_trace" not in paths, "关旗不许出现回放面文件"
