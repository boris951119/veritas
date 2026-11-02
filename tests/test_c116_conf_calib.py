"""C-116：置信档校准闸；默认关；禁系数／禁金标进提示。"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.conf_calib import (
    apply_conf_calib,
    conf_calib_enabled,
    demote_reasons_from_parts,
    gated_band,
    high_band_precision,
    label_hit,
)
from app.core.confidence import band_of
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, RelationKind,
    Segment, Source, SourceType,
)
from app.core.kg_submit_surface import FORBIDDEN_PACK_KEYS, audit_forbidden_keys
from app.export.official import _confidence_rows


def test_c116_flag_default_off(monkeypatch):
    monkeypatch.delenv("VERITAS_CONF_CALIB", raising=False)
    assert Settings().conf_calib is False
    assert conf_calib_enabled() is False
    monkeypatch.setenv("VERITAS_CONF_CALIB", "1")
    assert Settings.from_env().conf_calib is True
    assert conf_calib_enabled() is True


def test_c116_flag_off_band_unchanged(monkeypatch):
    monkeypatch.setenv("VERITAS_CONF_CALIB", "0")
    g = gated_band(0.85, parts={"n_evidence": 1, "chain": 0.5, "agreement": 0.5})
    assert g["predicted_band"] == "高"
    assert g["band"] == "高"
    assert g["demoted"] is False


def test_c116_demote_high_on_gates(monkeypatch):
    monkeypatch.setenv("VERITAS_CONF_CALIB", "1")
    # 证据不足
    g = gated_band(
        0.85,
        parts={"n_evidence": 1, "chain": 1.0, "agreement": 1.0},
        enabled=True,
    )
    assert g["predicted_band"] == "高"
    assert g["band"] == "中"
    assert "min_evidence" in g["demote_reasons"]
    # 链不全
    g2 = gated_band(
        0.85,
        parts={"n_evidence": 3, "chain": 0.8, "agreement": 1.0},
        enabled=True,
    )
    assert g2["demoted"] and "chain_incomplete" in g2["demote_reasons"]
    # 编队未一致
    g3 = gated_band(
        0.85,
        parts={"n_evidence": 3, "chain": 1.0, "agreement": 0.5},
        enabled=True,
    )
    assert "panel_disagreement" in g3["demote_reasons"]
    # 全过
    g4 = gated_band(
        0.85,
        parts={"n_evidence": 3, "chain": 1.0, "agreement": 1.0,
               "gates": {"G1_citation": {"fired": False, "hit_rate": 1.0}}},
        enabled=True,
    )
    assert g4["demoted"] is False and g4["band"] == "高"


def test_c116_does_not_change_score(monkeypatch):
    monkeypatch.setenv("VERITAS_CONF_CALIB", "1")
    g = gated_band(0.8812, parts={"n_evidence": 1}, enabled=True)
    assert g["score"] == 0.8812
    assert band_of(g["score"]) == "高"


def test_c116_apply_writes_accounting_no_coeff(monkeypatch):
    monkeypatch.setenv("VERITAS_CONF_CALIB", "1")
    d = Dossier(question="测")
    src = Source.create("S", SourceType.REPORT, id="S")
    src.segments.append(Segment(id="S#p1", source_id="S", text="足够长的证据段落正文一二三"))
    d.add_source(src)
    c = Conclusion.create("结论甲", author="mainstream")
    c.status = "majority"
    c.confidence = 0.85
    c.confidence_parts = {
        "n_evidence": 1, "chain": 1.0, "agreement": 1.0, "strength": 0.7,
    }
    d.conclusions.append(c)
    payload = apply_conf_calib(d, enabled=True)
    assert payload is not None
    assert payload["n_demoted"] == 1
    assert audit_forbidden_keys(payload) == []
    for bad in FORBIDDEN_PACK_KEYS:
        assert bad not in payload
    assert "金标" not in str(payload)
    assert d.accounting["conf_calib"]["rows"][0]["demoted"] is True
    assert c.confidence == 0.85  # 分数不动
    assert c.confidence_parts["band_gated"] == "中"


def test_c116_export_band_gated(monkeypatch):
    monkeypatch.setenv("VERITAS_CONF_CALIB", "1")
    d = Dossier(question="测")
    c = Conclusion.create("结论", author="a")
    c.status = "majority"
    c.confidence = 0.85
    c.confidence_parts = {
        "strength": 0.9, "coverage": 0.9, "agreement": 0.5,
        "agreement_factor": 0.85, "chain": 0.5, "n_evidence": 1,
        "aggregate_raw": 0.85, "gates": {},
        "chain_for_aggregate": 0.5,
    }
    d.conclusions.append(c)
    rows = _confidence_rows("q_001", d)
    assert rows[0]["predicted_band"] == "高"
    assert rows[0]["band"] == "中"
    assert rows[0]["score"] == rows[0]["score"]  # 有分
    assert "demote_reasons" in rows[0]


def test_c116_label_hit_and_precision():
    assert label_hit("对") is True
    assert label_hit("部分") is False
    assert label_hit("错") is False
    rows = [
        {"band": "高", "label": "对"},
        {"band": "高", "label": "错"},
        {"band": "中", "label": "对"},
    ]
    p = high_band_precision(rows)
    assert p["n_high"] == 2 and p["n_hit"] == 1
    assert abs(p["precision"] - 0.5) < 1e-9


def test_c116_demote_reasons_from_parts_no_fourth_invented():
    rs = demote_reasons_from_parts({
        "n_evidence": 0, "chain": 0.0, "agreement": 0.0,
    })
    assert set(rs) <= {
        "min_evidence", "anchor_incomplete", "chain_incomplete",
        "panel_disagreement", "conflict_undecided",
    }
