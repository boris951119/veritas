"""C-159：置信面「档位依据＋高档收据」守护格（只加披露；分数面与红线数值一字不动）。

判据落点（与 scripts/probe_c159_conf_receipt.py 的 G1..G7 同向，这里只吃合成行与
合成案卷，不依赖任何未入库产物）：
- 出厂默认开；``VERITAS_CONF_RECEIPT=0`` 与 config.json ``conf_receipt=false`` 都能关；
- 关＝行键集与字段说明回到 C-156 面；开＝只多 ``档位依据``／``高档收据`` 两键，
  其余键与数值逐字段等（＝不抬档、不改分）；
- 理由句里的数字，本文件**按字面常量手算**核溯源（不调被测实现，防自证）；
- 阈值不硬编：改 ``_BAND_HIGH``  ⇒ 句子里的阈值跟着变；
- 来源不在场（无 component_basis）⇒ 只写「未披露」，不许冒出等级字母；
- 禁面数值钉死：``_AGG`` 五权重、``_BAND_HIGH``／``_BAND_MID``、``LEVEL_WEIGHT``
  四档权＝本票一字未动。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.core import confidence as conf_mod
from app.core.confidence import aggregate_constants
from app.core.confidence_receipt import (
    HIGH_KEY,
    RECEIPT_KEY,
    attach_receipts,
    reason_sentence,
)
from app.core.evidence import LEVEL_WEIGHT, EvidenceLevel
from app.export.official import conf_receipt_enabled, export_official

_ENV = "VERITAS_CONF_RECEIPT"
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


@pytest.fixture(autouse=True)
def _flag_isolated(monkeypatch):
    """每条用例自己定旗：先摘 env，再由用例显式设，不吃环境残留。"""
    monkeypatch.delenv(_ENV, raising=False)


# ── 合成行：与生产 confidence.json 同形（键名照抄，数值手给）──────────────────

def _row(*, score: float = 0.96, band: str = "高", band_rel: str = "高",
         strength: float = 0.85, coverage: float = 0.5,
         agreement_factor: float = 0.6666, chain: float = 1.0,
         gates: dict | None = None, with_basis: bool = True) -> dict:
    g = gates or {"G1_citation": {"fired": False, "hit_rate": 1.0,
                                  "threshold": 0.6, "cap": 0.4},
                  "G2_no_evidence": {"fired": False, "n_evidence": 1},
                  "G3_premise_broken": {"fired": False, "ids": [], "cap": 0.45}}
    row = {
        "question_id": "q_001",
        "conclusion_id": "CON-SYNTH",
        "信源可信度": strength,
        "证据数量与一致性": {"coverage": coverage, "agreement": 0.3333,
                             "agreement_factor": agreement_factor},
        "推理链完整性": chain,
        "formula": "clip01(b + s*strength + c*coverage + a*agreement_factor "
                   "+ h*chain_score) + hard gates",
        "terms": {"strength": strength, "coverage": coverage, "agreement": 0.3333,
                  "agreement_factor": agreement_factor, "chain": chain,
                  "chain_factor": 1.0, "chain_for_aggregate": chain,
                  "aggregate_raw": score, "gates": g},
        "substitution": (f"clip01(0.10 + 0.25*{strength} + 0.20*{coverage} + "
                         f"0.15*{agreement_factor} + 0.30*{chain}) + gates[none] "
                         f"= {score}"),
        "score": score,
        "dossier_confidence": score,
        "band": band,
        "band_rule": conf_mod.BAND_RULE,
        "band_rel": band_rel,
        "band_rel_rule": "quantiles n=100 method=inclusive；pooled 样本数=1",
    }
    if with_basis:
        row["component_basis"] = {
            "n_evidence": 2, "n_authors": 1, "n_panel": 3,
            "n_panel_source": "dossier.panel", "levels": ["A", "B"],
            "min_evidence_score": 0.64,
            "chain_rings_applicable": ["quote_hits", "number_traceable"],
            "chain_rings_broken": [], "chain_unknown": False,
        }
        row["recompute"] = {"printed_weighted_sum": score, "gates_fired": ["none"],
                            "expected_score": score, "reported_score": score,
                            "delta": 0.0, "tolerance": 0.0001,
                            "reproducible": True, "rule": "…"}
    return row


def _hand_allowed(row: dict) -> set[float]:
    """允许集＝本文件手写的行内数值＋常量表数值＋手算乘积／差值（不调被测实现）。"""
    consts = aggregate_constants()
    w = consts["weights"]
    thr = consts["band_thresholds"]
    allowed = {
        float(row["score"]), 0.3333, 0.6, 0.45, 1.0, 0.0,
        float(thr["high"]), float(thr["mid"]),
        float(w["b"]), float(w["s"]), float(w["c"]), float(w["a"]), float(w["h"]),
    }
    t = row["terms"]
    vals = [float(t[k]) for k in ("strength", "coverage", "agreement",
                                  "agreement_factor", "chain",
                                  "chain_for_aggregate")]
    for x in (row.get("component_basis") or {}).values():
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            allowed.add(float(x))
    allowed |= {float(v) for v in vals}  # 分量原值也可以出现在句子里（w×v 的 v）
    cb = row.get("component_basis") or {}
    allowed.add(float(len(cb.get("chain_rings_applicable") or [])))
    allowed.add(float(len(cb.get("chain_rings_broken") or [])))
    for wv in (float(w["b"]), float(w["s"]), float(w["c"]), float(w["a"]),
               float(w["h"])):
        for v in vals:
            allowed.add(round(wv * v, 4))
            allowed.add(round(wv * (1.0 - v), 4))
    sc = float(row["score"])
    allowed |= {round(float(thr["high"]) - sc, 4), round(sc - float(thr["high"]), 4),
                round(float(thr["mid"]) - sc, 4), round(sc - float(thr["mid"]), 4)}
    return allowed


# ── 旗：出厂默认开＋env/config 两半都能关 ────────────────────────────────────

def test_c159_flag_factory_default_on():
    assert conf_receipt_enabled() is True
    assert Settings.from_env().conf_receipt is True


def test_c159_flag_env_zero_and_config_json_off(monkeypatch, tmp_path):
    monkeypatch.setenv(_ENV, "0")
    assert conf_receipt_enabled() is False
    assert Settings.from_env().conf_receipt is False
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"conf_receipt": False}), encoding="utf-8")
    assert Settings.from_json(cfg).conf_receipt is False
    cfg.write_text(json.dumps({"conf_receipt": "0"}), encoding="utf-8")
    assert Settings.from_json(cfg).conf_receipt is False
    cfg.write_text(json.dumps({}), encoding="utf-8")
    assert Settings.from_json(cfg).conf_receipt is True


# ── 不抬档：开旗只多两键，其余逐字段等 ───────────────────────────────────────

def test_c159_attach_adds_only_two_keys():
    rows = [_row(band="高"), _row(band="中", score=0.6, band_rel="中"),
            _row(band="低", score=0.4, band_rel="低")]
    snapshot = [json.dumps({k: v for k, v in r.items()}, ensure_ascii=False,
                           sort_keys=True) for r in rows]
    summary = attach_receipts(rows)
    assert summary == {"n_rows": 3, "n_sentence": 3, "n_high_receipt": 1,
                       "n_empty_sentence": 0}
    for row, before in zip(rows, snapshot):
        rest = {k: v for k, v in row.items()
                if k not in (RECEIPT_KEY, HIGH_KEY)}
        assert json.dumps(rest, ensure_ascii=False, sort_keys=True) == before, (
            "除两键外，任何既有键的数值都不许被本票改动（不抬档的硬形式）")
        assert row["band"] in ("高", "中", "低")
        assert isinstance(row[RECEIPT_KEY], str) and row[RECEIPT_KEY].strip()


def test_c159_high_receipt_only_on_high_rows():
    rows = [_row(band="高"), _row(band="中", score=0.6), _row(band="低", score=0.4)]
    attach_receipts(rows)
    assert isinstance(rows[0][HIGH_KEY], dict)
    assert HIGH_KEY not in rows[1]
    assert HIGH_KEY not in rows[2]
    hi = rows[0][HIGH_KEY]
    assert float(hi["本行分数"]) == float(rows[0]["score"])
    assert hi["五项贡献"]["推理链完整性"] == 0.3  # 0.30×1.0，现算不改分
    assert hi["证据等级构成"]["A"]["等级权"] == float(LEVEL_WEIGHT[EvidenceLevel.A])


# ── 溯源：理由句里的数字必须手算得到 ─────────────────────────────────────────

@pytest.mark.parametrize("band,score,rel", [("高", 0.96, "高"), ("中", 0.6, "中"),
                                            ("低", 0.4, "低")])
def test_c159_sentence_numbers_are_traceable(band, score, rel):
    row = _row(band=band, score=score, band_rel=rel)
    sent, _ = reason_sentence(row)
    allowed = _hand_allowed(row)
    bad = [m.group() for m in _NUM_RE.finditer(sent) if float(m.group()) not in allowed]
    assert not bad, f"理由句冒出不在允许集里的数字：{bad}｜句子＝{sent}"


def test_c159_sentence_does_not_invent_when_basis_missing():
    row = _row(band="高", with_basis=False)
    sent, high = reason_sentence(row)
    assert "未披露" in sent
    for lv in ("A", "B", "C", "D"):
        assert f"证据等级 {lv}" not in sent
    assert high["证据等级构成"] == "未披露（置信面细节旗关）"
    assert high["支撑证据条数"] == "未披露（置信面细节旗关）"


def test_c159_gate_fired_clause_names_gate_and_cap():
    row = _row(band="低", score=0.4, band_rel="低", gates={
        "G1_citation": {"fired": True, "hit_rate": 0.4, "threshold": 0.6, "cap": 0.4},
        "G2_no_evidence": {"fired": False, "n_evidence": 3},
        "G3_premise_broken": {"fired": False, "ids": [], "cap": 0.45},
    })
    sent, _ = reason_sentence(row)
    assert "触发硬门＝G1 引文命中（封顶 0.4）" in sent
    assert "三道硬门均未触发" not in sent


def test_c159_thresholds_come_from_constants_not_hardcode(monkeypatch):
    """把高阈值挪到 0.95：句子必须跟着改口（钉住「阈值非手抄」这条腿）。"""
    monkeypatch.setattr(conf_mod, "_BAND_HIGH", 0.95)
    row = _row(band="高", score=0.96)
    sent, high = reason_sentence(row)
    assert "高阈值 0.95" in sent
    assert "高阈值 0.8" not in sent
    assert float(high["阈值原样值"]["高"]) == 0.95


def test_c159_banded_sentence_states_threshold_relation():
    mid, _ = reason_sentence(_row(band="中", score=0.788))
    assert "＜高阈值 0.8" in mid and "差 0.012" in mid and "≥中阈值 0.5" in mid
    low, _ = reason_sentence(_row(band="低", score=0.4988))
    assert "＜中阈值 0.5" in low
    hi, _ = reason_sentence(_row(band="高", score=0.8125))
    assert "≥高阈值 0.8" in hi and "高出 0.0125" in hi


# ── 交卷面真接线：关旗回 C-156 面／开旗只多两键 ──────────────────────────────

def _export(tmp_path: Path, monkeypatch, *, flag: str | None):
    from tests.test_c156_confidence_face import _dossier

    monkeypatch.delenv(_ENV, raising=False)
    monkeypatch.delenv("VERITAS_CONF_FACE_DETAIL", raising=False)
    if flag is not None:
        monkeypatch.setenv(_ENV, flag)
    dossier = _dossier(tmp_path / "case")
    out = tmp_path / "out" / (flag or "default")
    question = {"question_id": "q_001", "question": "SEI 是怎么生成的？"}
    paths = export_official([(question, dossier)], out)
    rows = json.loads(paths["confidence"].read_text(encoding="utf-8"))
    notes = paths["notes"].read_text(encoding="utf-8")
    return rows, notes


def test_c159_export_off_keeps_c156_face(tmp_path, monkeypatch):
    rows, notes = _export(tmp_path, monkeypatch, flag="0")
    assert rows, "关旗臂也得有行（空面不算回退）"
    for row in rows:
        assert RECEIPT_KEY not in row and HIGH_KEY not in row
    assert "档位依据与高档收据" not in notes
    assert "置信收据本次现量" not in notes


def test_c159_export_on_adds_two_keys_and_leaves_score_face(tmp_path, monkeypatch):
    off_rows, _ = _export(tmp_path, monkeypatch, flag="0")
    on_rows, notes = _export(tmp_path, monkeypatch, flag="1")
    assert len(off_rows) == len(on_rows) > 0
    for off, on in zip(off_rows, on_rows):
        added = set(on) - set(off)
        assert added <= {RECEIPT_KEY, HIGH_KEY}
        base_off = {k: v for k, v in off.items()}
        base_on = {k: v for k, v in on.items() if k not in (RECEIPT_KEY, HIGH_KEY)}
        assert base_on == base_off, "分数面（score／band／terms 等）必须逐字段等"
        assert on[RECEIPT_KEY].strip()
    assert "档位依据与高档收据" in notes
    assert "置信收据本次现量" in notes


def test_c159_notes_lines_match_row_counts(tmp_path, monkeypatch):
    rows, notes = _export(tmp_path, monkeypatch, flag="1")
    n = len(rows)
    hi = sum(1 for r in rows if r.get("band") == "高")
    receipts = sum(1 for r in rows if isinstance(r.get(HIGH_KEY), dict))
    m = re.search(r"confidence\.json (\d+) 行）：档位依据在场 (\d+) 行", notes)
    assert m and int(m.group(1)) == n and int(m.group(2)) == n
    assert f"高档收据在场 {receipts} 行＝band「高」行数 {hi} 行" in notes


def test_c159_sentence_length_bounded():
    """交卷面还要给人读：单行理由句限长（超限＝披露开始淹没提交件）。"""
    rows = [_row(band="高"), _row(band="中", score=0.6), _row(band="低", score=0.4)]
    attach_receipts(rows)
    for row in rows:
        assert len(row[RECEIPT_KEY]) <= 320, row[RECEIPT_KEY]


def test_c159_forbidden_numbers_unchanged():
    """禁面数值钉死：本票不动合式权重、档阈值、等级权。"""
    assert {k: conf_mod._AGG[k] for k in ("b", "s", "c", "a", "h")} == {
        "b": 0.10, "s": 0.25, "c": 0.20, "a": 0.15, "h": 0.30}
    assert (conf_mod._BAND_HIGH, conf_mod._BAND_MID) == (0.8, 0.5)
    assert {str(l.value): float(v) for l, v in LEVEL_WEIGHT.items()} == {
        "A": 1.0, "B": 0.8, "C": 0.55, "D": 0.3}
