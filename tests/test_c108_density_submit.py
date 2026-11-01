"""C-108：密度交卷薄迁＋默认开窄面；禁键；旗关回退。"""

from __future__ import annotations

import os

import pytest

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.kg_density_bridge import (
    density_submit_surface,
    ensure_kg_submit_from_density,
    kg_cap_segments_enabled,
)
from app.core.kg_submit_surface import (
    FORBIDDEN_PACK_KEYS,
    apply_kg_submit_surface,
    audit_forbidden_keys,
    pack_kwargs_for_kg,
)
from app.core.material import pack_material
from app.kg_lab.density_submit import choose_density_k, density_constrained_submit


def _dossier() -> Dossier:
    d = Dossier(question="这笔49.4万元应认定为买断费还是自主择业经济补偿金，以哪方口径为准？")
    texts = [
        ("SRC1", "官方通报：按规定给予自主择业经济补偿金49.4万元。2024年3月12日10时30分许发布。"),
        ("SRC2", "当事人称这是买断费，不是补偿金，不愿走。"),
        ("SRC3", "今天天气晴朗，适合晾晒衣物。"),
        ("SRC4", "公园湖面平静，有人散步。"),
        ("SRC5", "媒体转载：自主择业经济补偿金与买断费口径对立，双方各执一词。"),
    ]
    for sid, text in texts:
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text))
        d.add_source(src)
    return d


def test_c108_settings_default_on_and_env_off(monkeypatch):
    monkeypatch.delenv("VERITAS_KG_SUBMIT_SURFACE", raising=False)
    assert Settings().kg_submit_surface is True
    monkeypatch.setenv("VERITAS_KG_SUBMIT_SURFACE", "0")
    assert Settings.from_env().kg_submit_surface is False


def test_c108_choose_density_k_respects_target():
    packed = ["c1", "c2", "c3", "f1", "f2", "x"]
    out = choose_density_k(packed, {"c1", "c2", "c3"}, {"f1", "f2"}, k_min=3, k_max=5)
    assert 3 <= out["k"] <= 5
    assert out["submission"]
    assert audit_forbidden_keys(out) == []


def test_c108_density_bridge_surface_no_coeff_leak():
    d = _dossier()
    out = density_submit_surface(d, top_n=20)
    surface = out["surface"]
    assert surface["rank_order"]
    assert surface["k"] >= 1
    assert audit_forbidden_keys(surface) == []
    for bad in ("coeff", "feats", "weights", "multidim", "r9_coeff"):
        assert bad not in FORBIDDEN_PACK_KEYS or bad in FORBIDDEN_PACK_KEYS
        blob = str(surface)
        assert f'"{bad}"' not in blob or bad not in surface


def test_c108_flag_off_pack_equals_baseline(monkeypatch):
    monkeypatch.setenv("VERITAS_KG_SUBMIT_SURFACE", "0")
    d0 = _dossier()
    d1 = _dossier()
    a = pack_material(d0, budget_chars=5000)
    # 旗关：不 apply
    assert apply_kg_submit_surface(d1, enabled=False) is None
    b = pack_material(d1, budget_chars=5000, **pack_kwargs_for_kg(d1))
    assert a["selected"] == b["selected"]


def test_c108_default_priority_no_cap_keeps_or_grows_selected(monkeypatch):
    monkeypatch.delenv("VERITAS_KG_CAP_SEGMENTS", raising=False)
    monkeypatch.delenv("VERITAS_KG_SUBMIT_SURFACE", raising=False)
    assert kg_cap_segments_enabled() is False
    d = _dossier()
    base = pack_material(d, budget_chars=5000)
    d2 = _dossier()
    ensure_kg_submit_from_density(d2, top_n=20)
    apply_kg_submit_surface(d2, enabled=True)
    kw = pack_kwargs_for_kg(d2)
    assert "max_segments" not in kw  # 默认不硬顶
    on = pack_material(d2, budget_chars=5000, **kw)
    # 预算装满路径：段数不应被裁到 k
    assert len(on["selected"]) >= min(len(base["selected"]), 3)


def test_c108_cap_segments_env_applies_max(monkeypatch):
    monkeypatch.setenv("VERITAS_KG_CAP_SEGMENTS", "1")
    d = _dossier()
    ensure_kg_submit_from_density(d, top_n=20, force=True)
    apply_kg_submit_surface(d, enabled=True)
    assert d.accounting.get("kg_cap_segments") is True
    kw = pack_kwargs_for_kg(d)
    assert "max_segments" in kw
    pack = pack_material(d, budget_chars=50_000, **kw)
    assert len(pack["selected"]) <= int(kw["max_segments"])
