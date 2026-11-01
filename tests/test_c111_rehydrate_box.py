"""C-111：短盒回灌；禁系数进 pack；旗回退 C-109。"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.kg_density_bridge import density_submit_surface
from app.core.kg_rehydrate import (
    apply_rehydrate_to_density,
    kg_rehydrate_enabled,
    lookup_seed_box,
    query_sha16,
    rehydrate_pad_box,
)
from app.core.kg_submit_surface import (
    apply_kg_submit_surface,
    audit_forbidden_keys,
    pack_kwargs_for_kg,
)


def _dossier(q: str = "测试议题甲乙对立口径？") -> Dossier:
    d = Dossier(question=q)
    for sid, text in [
        ("A", "官方：甲口径成立。2024年1月1日10时00分。"),
        ("B", "当事方称乙口径，否认甲。"),
        ("C", "无关：今日天气。"),
        ("D", "媒体汇总甲乙对立。"),
        ("E", "专家认为应以官方为准。"),
        ("F", "通稿复述官方甲口径。"),
        ("G", "评论区情绪宣泄。"),
        ("H", "时间线补充说明。"),
    ]:
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text))
        d.add_source(src)
    return d


def test_c111_rehydrate_default_on_env_off(monkeypatch):
    monkeypatch.delenv("VERITAS_KG_REHYDRATE_BOX", raising=False)
    assert Settings().kg_rehydrate_box is True
    assert kg_rehydrate_enabled() is True
    monkeypatch.setenv("VERITAS_KG_REHYDRATE_BOX", "0")
    assert Settings.from_env().kg_rehydrate_box is False
    assert kg_rehydrate_enabled() is False


def test_c111_pad_forces_k_near_7():
    dens = {
        "k": 3,
        "submission": ["A#s1", "B#s1", "D#s1"],
        "core_ids": ["A#s1", "B#s1"],
        "packed": ["A#s1", "B#s1", "D#s1", "E#s1", "F#s1", "H#s1", "C#s1"],
    }
    pool = ["A#s1", "B#s1", "D#s1", "E#s1", "F#s1", "H#s1", "C#s1", "G#s1"]
    box = rehydrate_pad_box(pool, dens, target_k=7)
    assert len(box) == 7
    assert box[:3] == ["A#s1", "B#s1", "D#s1"]
    out = apply_rehydrate_to_density(dens, pool)
    assert out["rehydrated"] is True
    assert out["k"] == 7
    assert out["rehydrate_kind"] == "pad_to_k"


def test_c111_pack_kwargs_no_coeff_with_rehydrate(monkeypatch):
    monkeypatch.delenv("VERITAS_KG_CAP_SEGMENTS", raising=False)
    monkeypatch.delenv("VERITAS_KG_REHYDRATE_BOX", raising=False)
    d = _dossier()
    bridge = density_submit_surface(d, top_n=20, use_stage1=True)
    d.accounting["kg_submit"] = bridge["surface"]
    d.accounting["kg_cap_segments"] = False
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    assert audit_forbidden_keys(kw) == []
    for bad in ("coeff", "weights", "feats", "r9", "r21", "DEFAULT_WEIGHTS"):
        assert bad not in kw
        assert bad.lower() not in {k.lower() for k in kw}


def test_c111_flag_off_no_seed_lookup(monkeypatch):
    monkeypatch.setenv("VERITAS_KG_REHYDRATE_BOX", "0")
    # 即便问句能命中种子，关旗也不回灌
    assert lookup_seed_box("anything") is None


def test_c111_upstream_short_still_preferred(monkeypatch):
    monkeypatch.delenv("VERITAS_KG_REHYDRATE_BOX", raising=False)
    d = _dossier()
    short = ["A#s1", "B#s1", "D#s1"]
    out = density_submit_surface(d, order=short, use_stage1=True)
    assert list(out["density"]["submission"]) == short
    # 有上游盒时不走种子
    assert not (out.get("rehydrate") or {}).get("seed_hit")


def test_c111_seed_hit_by_query_sha(monkeypatch):
    monkeypatch.delenv("VERITAS_KG_REHYDRATE_BOX", raising=False)
    from app.core.kg_rehydrate import _load_seeds
    _load_seeds.cache_clear()
    seeds = _load_seeds()
    assert seeds, "仓内应有 C-111 冻结短盒种子"
    row = seeds[0]
    q = None
    # 从种子文件取原文问句
    import json
    from pathlib import Path
    raw = json.loads(
        (Path(__file__).resolve().parents[1]
         / "app/core/kg_rehydrate_seeds.json").read_text(encoding="utf-8")
    )
    q = raw[0]["query"]
    assert query_sha16(q) == raw[0]["query_sha1_16"]
    box = lookup_seed_box(q)
    assert box == list(raw[0]["box"])
