"""C-156：置信面（3.2）导出披露——两类键＋常量表进交卷面；分数面与关旗形态一字不动。

判据落点（与 scripts/probe_c156_confidence_face.py 的三腿同向，这里只吃合成案卷）：
- 关旗（VERITAS_CONF_FACE_DETAIL=0）＝交卷 confidence.json 行键集回到改前那一套、字段说明里没有新块；
- 开旗＝只多 `component_basis`／`recompute` 两类键，score／band／band_rel／terms 逐行不动；
- `recompute` 用「本行印出的四位数」独立复算（本文件按字面常量手算，不调被测实现）；
- `aggregate_constants()` 与 confidence.py 里的 `_AGG`／模块常量必须同一份数（防两套数漂移）；
- 字段说明里那三行现量计数与交卷面实数一致（本文件用朴素比较数档，不复用实现）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.core import confidence as conf_mod
from app.core.evidence import Conclusion, EvidenceNode
from app.export.official import (
    _FIELD_NOTES,
    conf_face_detail_enabled,
    export_official,
)
from app.ingest.official_case import load_official_case
from tests.test_official_roundtrip import _para, _write_docs

_ENV = "VERITAS_CONF_FACE_DETAIL"

# 改前（tip 3227200）交卷 confidence.json 的行键集：关旗必须逐字回到这套
PRE_CHANGE_ROW_KEYS = {
    "question_id", "conclusion_id", "信源可信度", "证据数量与一致性",
    "推理链完整性", "formula", "terms", "substitution", "score",
    "dossier_confidence", "band", "band_rule", "band_rel", "band_rel_rule",
}
NEW_ROW_KEYS = {"component_basis", "recompute"}


def _clear_flag(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)


def _dossier(tmp_path: Path, *, n_ev: int = 2, authors: tuple[str, ...] = ("m",)):
    """合成一题：一条 majority 结论挂 n_ev 条逐字可定位的证据，编队三人。"""
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    pieces = [
        "固态电解质界面在首次循环里生成，来自碳酸乙烯酯的还原分解。",
        "该体系在 60 ℃ 存储 30 天后容量保持率为 91.2%。",
        "第三方报道复述了同一组数据，未给出新的实验条件。",
    ][:n_ev]
    content = "".join(pieces)
    cuts = []
    cursor = 0
    for i, piece in enumerate(pieces):
        cuts.append(_para(f"p{i}", cursor, cursor + len(piece)))
        cursor += len(piece)
    case = _write_docs(tmp_path, [{
        "doc_id": "doc_1",
        "title": "t",
        "publish_time": "2024-01-02",
        "content": content,
        "source_credibility": 0.6,
        "content_url": "",
        "paragraphs": cuts,
    }])
    dossier = load_official_case(case)
    con = Conclusion.create("SEI 由碳酸乙烯酯还原分解生成", author=authors[0], id="CON-A")
    con.status = "majority"
    for name in authors[1:]:
        con.authors.append(name)
    dossier.conclusions.append(con)
    for i, piece in enumerate(pieces):
        dossier.add_evidence(
            EvidenceNode.create("CON-A", piece, [f"p{i}"], id=f"EV-{i}")
        )
    dossier.panel = ["alpha", "beta", "gamma"]
    conf_mod.recompute_all(dossier, n_panel=len(dossier.panel))
    return dossier


def _export(tmp_path: Path, monkeypatch, *, flag: str | None) -> tuple[list[dict], str]:
    """走真入口 export_official 落一份交卷面，返回 (confidence 行, 字段说明全文)。"""
    _clear_flag(monkeypatch)
    if flag is not None:
        monkeypatch.setenv(_ENV, flag)
    dossier = _dossier(tmp_path / "case")
    out = tmp_path / "out"
    question = {"question_id": "q_001", "question": "SEI 是怎么生成的？"}
    paths = export_official([(question, dossier)], out)
    rows = json.loads(paths["confidence"].read_text(encoding="utf-8"))
    notes = paths["notes"].read_text(encoding="utf-8")
    return rows, notes


# ── 旗：出厂默认开＋env 关 ────────────────────────────────────────────────

def test_c156_flag_factory_default_on(monkeypatch):
    _clear_flag(monkeypatch)
    assert conf_face_detail_enabled() is True
    assert Settings.from_env().conf_face_detail is True


def test_c156_flag_env_zero_turns_off(monkeypatch):
    _clear_flag(monkeypatch)
    monkeypatch.setenv(_ENV, "0")
    assert conf_face_detail_enabled() is False
    assert Settings.from_env().conf_face_detail is False


def test_c156_flag_config_json_key_turns_off(tmp_path, monkeypatch):
    """config.json 那半走真读入口：键写 false ⇒ 关（不是只有 env 能关）。"""
    _clear_flag(monkeypatch)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"conf_face_detail": False}), encoding="utf-8")
    assert Settings.from_json(cfg).conf_face_detail is False
    cfg.write_text(json.dumps({"conf_face_detail": "0"}), encoding="utf-8")
    assert Settings.from_json(cfg).conf_face_detail is False
    cfg.write_text(json.dumps({}), encoding="utf-8")
    assert Settings.from_json(cfg).conf_face_detail is True


# ── 关旗＝逐字节回到改前形态 ──────────────────────────────────────────────

def test_c156_off_flag_row_keys_are_pre_change_set(tmp_path, monkeypatch):
    rows, _ = _export(tmp_path, monkeypatch, flag="0")
    assert rows, "关旗臂也得有行（空面不算回退）"
    for row in rows:
        assert set(row) == PRE_CHANGE_ROW_KEYS


def test_c156_off_flag_notes_have_no_new_block(tmp_path, monkeypatch):
    _, notes = _export(tmp_path, monkeypatch, flag="0")
    assert "置信合式常量表" not in notes
    assert "置信面本次现量" not in notes
    assert notes.startswith(_FIELD_NOTES.rstrip("\n"))


# ── 开旗＝只多两类键，分数面逐行不动 ─────────────────────────────────────

def test_c156_on_flag_adds_only_two_keys_and_score_face_identical(tmp_path, monkeypatch):
    off_rows, _ = _export(tmp_path / "off", monkeypatch, flag="0")
    on_rows, _ = _export(tmp_path / "on", monkeypatch, flag="1")
    assert len(off_rows) == len(on_rows) > 0
    for off, on in zip(off_rows, on_rows):
        assert set(on) - set(off) == NEW_ROW_KEYS
        for key in ("score", "band", "band_rel", "terms", "substitution", "formula"):
            assert on[key] == off[key], f"{key} 被改了＝换分"
        assert on["recompute"]["reproducible"] is True
        assert set(on["recompute"]) >= {
            "printed_weighted_sum", "gates_fired", "expected_score",
            "reported_score", "delta", "tolerance", "reproducible", "rule",
        }
        assert set(on["component_basis"]) >= {"n_evidence", "n_authors", "n_panel", "levels"}


def test_c156_default_on_when_env_unset(tmp_path, monkeypatch):
    rows, notes = _export(tmp_path, monkeypatch, flag=None)
    assert rows
    assert all(NEW_ROW_KEYS <= set(r) for r in rows)
    assert "置信合式常量表" in notes and "置信面本次现量" in notes


# ── component_basis：分量真数落在行上（3.2「依据」那半） ───────────────────

def test_c156_component_basis_is_real_counts(tmp_path, monkeypatch):
    rows, _ = _export(tmp_path, monkeypatch, flag="1")
    basis = rows[0]["component_basis"]
    assert basis["n_evidence"] == 2
    assert basis["n_panel"] == 3 and basis["n_panel_source"] == "dossier.panel"
    assert basis["n_authors"] == 1
    assert basis["levels"] == sorted(basis["levels"]) and basis["levels"]
    assert isinstance(basis["min_evidence_score"], (int, float))
    assert isinstance(basis["chain_rings_applicable"], list)
    assert basis["chain_rings_applicable"]
    assert set(basis["chain_rings_broken"]) <= set(basis["chain_rings_applicable"])
    assert basis["chain_unknown"] is False


def test_c156_component_basis_survives_json_roundtrip(tmp_path, monkeypatch):
    """交卷件是 JSON：两类键必须真写进文件而不是只在内存里。"""
    out_dir = tmp_path / "bundle"
    _clear_flag(monkeypatch)
    dossier = _dossier(tmp_path / "case")
    paths = export_official(
        [({"question_id": "q_001", "question": "SEI 是怎么生成的？"}, dossier)], out_dir
    )
    text = paths["confidence"].read_text(encoding="utf-8")
    assert '"component_basis"' in text and '"recompute"' in text
    rows = json.loads(text)
    assert all(NEW_ROW_KEYS <= set(r) for r in rows)


# ── recompute：评委按印出的数能复算出同一个分 ────────────────────────────

def test_c156_recompute_matches_hand_arithmetic_with_literal_weights(tmp_path, monkeypatch):
    rows, _ = _export(tmp_path, monkeypatch, flag="1")
    for row in rows:
        terms, rec = row["terms"], row["recompute"]
        # 字面常量手算（不读 aggregate_constants／不调 _printed_recompute）＝独立腿
        raw = (
            0.10 + 0.25 * terms["strength"] + 0.20 * terms["coverage"]
            + 0.15 * terms["agreement_factor"] + 0.30 * terms["chain_for_aggregate"]
        )
        raw = min(1.0, max(0.0, raw))
        assert rec["printed_weighted_sum"] == round(raw, 4)
        assert rec["expected_score"] == round(raw, 4), "本样卷无门触发⇒封顶前应等于封顶后"
        assert rec["gates_fired"] == ["none"]
        assert rec["reported_score"] == row["score"]
        assert rec["delta"] <= rec["tolerance"] and rec["reproducible"] is True


def test_c156_recompute_reports_failure_when_score_off(tmp_path):
    """反向腿：印出的数与本行 score 打架时，必须标 reproducible=False 而不是静默放行。"""
    from app.export.official import _printed_recompute

    terms = {
        "strength": 0.5, "coverage": 0.5, "agreement_factor": 0.5,
        "chain_for_aggregate": 0.5, "gates": None,
    }
    # 手算：0.10 + 0.5*(0.25+0.20+0.15+0.30) = 0.55
    ok = _printed_recompute(terms, 0.55)
    assert ok["printed_weighted_sum"] == 0.55
    assert ok["reproducible"] is True and ok["delta"] == 0.0
    bad = _printed_recompute(terms, 0.9)
    assert bad["reproducible"] is False
    assert bad["delta"] == 0.35 and bad["expected_score"] == 0.55


def test_c156_recompute_applies_hard_gate_caps(tmp_path):
    """门触发时按披露的封顶值复算，且把触发的门名列出来。"""
    from app.export.official import _printed_recompute

    terms = {
        "strength": 0.9, "coverage": 0.9, "agreement_factor": 0.9,
        "chain_for_aggregate": 0.9,
        "gates": {"G1_citation": {"fired": True}, "G3_premise_broken": {"fired": False}},
    }
    # 手算：0.10 + 0.9*(0.25+0.20+0.15+0.30) = 0.91 ⇒ G1 封顶 0.40
    rec = _printed_recompute(terms, 0.4)
    assert rec["gates_fired"] == ["G1_citation"]
    assert rec["printed_weighted_sum"] == 0.91
    assert rec["expected_score"] == 0.40 and rec["reproducible"] is True
    g2 = _printed_recompute({**terms, "gates": {"G2_no_evidence": {"fired": True}}}, 0.0)
    assert g2["expected_score"] == 0.0 and g2["gates_fired"] == ["G2_no_evidence"]


# ── 常量表：披露与生产同一份数 ───────────────────────────────────────────

def test_c156_aggregate_constants_equals_live_weights():
    consts = conf_mod.aggregate_constants()
    agg = conf_mod._AGG
    assert consts["weights"] == {
        "b": agg["b"], "s": agg["s"], "c": agg["c"], "a": agg["a"], "h": agg["h"],
    }
    assert consts["hard_gates"]["G1_citation"]["cap"] == agg["g1_cap"]
    assert consts["hard_gates"]["G1_citation"]["hit_rate_min"] == agg["g1_hit_rate_min"]
    assert consts["hard_gates"]["G3_premise_broken"]["cap"] == agg["g3_cap"]
    cc = consts["component_constants"]
    assert cc["coverage_floor"] == conf_mod._COVERAGE_FLOOR
    assert cc["coverage_saturation"] == conf_mod._COVERAGE_SATURATION
    assert cc["agreement_floor"] == conf_mod._AGREEMENT_FLOOR
    assert cc["chain_unknown"] == conf_mod._CHAIN_UNKNOWN
    assert cc["causation_bonus"] == conf_mod._CAUSATION_BONUS
    assert consts["band_thresholds"] == {
        "high": conf_mod._BAND_HIGH, "mid": conf_mod._BAND_MID,
    }
    assert consts["temperature_default"] == conf_mod._DEFAULT_TEMPERATURE
    # 快照是只读副本：改它不许回头污染生产常量
    consts["weights"]["s"] = 0.99
    assert conf_mod._AGG["s"] != 0.99


def test_c156_constants_block_numbers_come_from_live_table(tmp_path, monkeypatch):
    _, notes = _export(tmp_path, monkeypatch, flag="1")
    w = conf_mod.aggregate_constants()["weights"]
    line = next(l for l in notes.splitlines() if l.startswith("raw = clip01("))
    for val in (w["b"], w["s"], w["c"], w["a"], w["h"]):
        assert str(val) in line


# ── 现量三行：文案与交卷实数不得脱钩 ─────────────────────────────────────

def test_c156_face_lines_counts_match_the_rows(tmp_path, monkeypatch):
    rows, notes = _export(tmp_path, monkeypatch, flag="1")
    scores = [r["score"] for r in rows]
    assert scores, "现量行得有数（空面不算数）"
    high = sum(1 for s in scores if s >= 0.8)
    mid = sum(1 for s in scores if 0.5 <= s < 0.8)
    low = sum(1 for s in scores if s < 0.5)
    assert f"绝对档 高 {high}／中 {mid}／低 {low}" in notes
    assert f"置信面本次现量（confidence.json {len(rows)} 行）" in notes
    assert "三道硬门本次触发行数＝G1 引文命中 0／G2 无证据 0／G3 前提破坏 0" in notes
    assert f"署名≥2 的结论 {sum(1 for r in rows if r['component_basis']['n_authors'] >= 2)} 条" in notes
    assert "按印出数复算失败（±1e-4 外）的行 0 条" in notes


def test_c156_on_notes_is_off_notes_plus_two_blocks(tmp_path, monkeypatch):
    """开旗相对关旗＝插入常量表＋尾附三行现量；除此之外说明体一字不动。"""
    _, off = _export(tmp_path / "off", monkeypatch, flag="0")
    _, on = _export(tmp_path / "on", monkeypatch, flag="1")
    marker = "\n## 本次导出\n"
    head_off, tail_off = off.split(marker, 1)
    head_on, tail_on = on.split(marker, 1)
    assert head_on.startswith(head_off), "常量表插在说明体之后，前段须逐字同关旗"
    inserted = head_on[len(head_off):]
    assert inserted.startswith("\n## 置信合式常量表")
    assert "raw = clip01(" in inserted and "硬门：" in inserted
    off_tail_lines = tail_off.rstrip("\n").splitlines()
    on_tail_lines = tail_on.rstrip("\n").splitlines()
    assert on_tail_lines[:len(off_tail_lines)] == off_tail_lines
    assert len(on_tail_lines) - len(off_tail_lines) == 3
