"""C-107：交卷窄面——禁键泄漏／旗关零差／旗开 fixture 接通。"""

from __future__ import annotations

import inspect

import pytest

from app.agents.prompts import render_segments_block
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.kg_submit_surface import (
    FORBIDDEN_PACK_KEYS,
    FORBIDDEN_PACK_PARAM_NAMES,
    apply_kg_submit_surface,
    assert_clean_pack_kwargs,
    assert_submit_no_coeff,
    audit_forbidden_keys,
    build_submit_surface,
    describe_boundaries,
    kg_focus_segment_ids,
    kg_priority_override,
    pack_hints_from_submit,
    pack_kwargs_for_kg,
    stage2_box_export,
)
from app.core.material import pack_material
from app.pipeline import _render_kg_conflict_pairs_section


def _fixture_surface() -> dict:
    box = stage2_box_export({
        "top_ids": ["SRC1#s1", "SRC2#s1", "SRC3#s1", "SRC4#s1"],
        "k": 2,
        "conflict_pairs": {
            "options": ["涨", "跌"],
            "support": [{"id": "SRC1#s1", "option": "涨"}],
            "oppose": [{"id": "SRC2#s1", "option": "跌"}],
            "conflicts": [{
                "support_id": "SRC1#s1",
                "oppose_id": "SRC2#s1",
                "support_option": "涨",
                "oppose_option": "跌",
                "support_authority": 0.9,  # 须剥掉
                "oppose_authority": 0.1,
                "preferred": "SRC1#s1",
                "reason": "authority_over_similarity",
            }],
        },
        "density": {"k": 2, "n_core": 2, "met_target": True},
        "intent": {"route": "adjudicate"},
    })
    return build_submit_surface(box, tree17_plan={
        "close_read": ["SRC1#s1"],
        "pair_required": True,
        "conflict_route": True,
        "items": [{
            "para_id": "SRC1#s1",
            "in_close_read": True,
            "label": "采信",
            "side": "none",
            "stance": "support",
            "verifiability": {"score": 0.9},
        }],
    })


def _dossier_four() -> Dossier:
    d = Dossier(question="客户B回款率是多少？")
    texts = [
        ("SRC1", "客户B回款512万元，回款率四成，同比上升。"),
        ("SRC2", "客户B回款率下滑至两成，风险上升。"),
        ("SRC3", "今天天气晴朗，适合晾晒衣物。"),
        ("SRC4", "公园里有人散步，湖面平静。"),
    ]
    for sid, text in texts:
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text))
        d.add_source(src)
    return d


def test_c107_forbidden_keys_cover_coeff_feats_weights():
    for needle in ("coeff", "feats", "weights", "multidim", "r9_coeff",
                   "DEFAULT_WEIGHTS", "r21_coeff"):
        assert needle in FORBIDDEN_PACK_KEYS or needle in FORBIDDEN_PACK_PARAM_NAMES


def test_c107_submit_surface_strips_authority_and_rejects_coeff():
    surface = _fixture_surface()
    assert_submit_no_coeff(surface)
    conf = surface["conflict_pairs"]["conflicts"][0]
    assert "support_authority" not in conf
    assert conf["support_id"] == "SRC1#s1"
    assert audit_forbidden_keys(surface) == []
    dirty = {**surface, "coeff": {"a": 1}}
    assert any(h.endswith(".coeff") for h in audit_forbidden_keys(dirty))
    with pytest.raises(AssertionError):
        assert_submit_no_coeff(dirty)


def test_c107_pack_hints_no_forbidden_and_keep_pairs_dict():
    surface = _fixture_surface()
    hints = pack_hints_from_submit(surface)
    assert hints["priority_segment_ids"] == ["SRC1#s1", "SRC2#s1"]
    assert hints["focus_segment_ids"] == ["SRC1#s1"]
    assert hints["max_segments"] == 2
    assert isinstance(hints["conflict_pairs"], dict)
    assert audit_forbidden_keys(hints) == []
    with pytest.raises(ValueError):
        assert_clean_pack_kwargs({"max_segments": 2, "coeff": 1})
    with pytest.raises(ValueError):
        assert_clean_pack_kwargs({"weights": {}})
    assert_clean_pack_kwargs({"max_segments": 2})


def test_c107_pack_material_signature_unchanged():
    sig = inspect.signature(pack_material)
    params = set(sig.parameters)
    assert "max_segments" in params
    for bad in FORBIDDEN_PACK_KEYS:
        assert bad not in params


def test_c107_flag_off_no_apply_zero_behavior(monkeypatch):
    monkeypatch.delenv("VERITAS_KG_SUBMIT_SURFACE", raising=False)
    d = _dossier_four()
    d.accounting["kg_submit"] = _fixture_surface()
    assert apply_kg_submit_surface(d, enabled=False) is None
    assert not d.accounting.get("kg_submit_active")
    assert kg_priority_override(d) is None
    assert kg_focus_segment_ids(d) is None
    assert pack_kwargs_for_kg(d) == {}
    base = pack_material(d, budget_chars=10_000)
    # 无 override 时 priority 与现产同路
    from app.core.answer_slots import priority_segment_ids
    assert priority_segment_ids(d) == []
    again = pack_material(d, budget_chars=10_000)
    assert again["selected"] == base["selected"]


def test_c107_flag_on_fixture_priority_max_segments_focus_pairs():
    d = _dossier_four()
    surface = _fixture_surface()
    hints = apply_kg_submit_surface(d, surface, enabled=True)
    assert hints is not None
    assert d.accounting["kg_submit_active"] is True
    assert kg_priority_override(d) == ["SRC1#s1", "SRC2#s1"]
    assert kg_focus_segment_ids(d) == ["SRC1#s1"]

    kw = pack_kwargs_for_kg(d)
    assert kw == {"max_segments": 2}
    assert_clean_pack_kwargs(kw)

    pack = pack_material(d, budget_chars=10_000, **kw)
    assert len(pack["selected"]) <= 2
    assert "SRC1#s1" in pack["selected"]
    # rank 优先：支持／对立两段应先进箱
    assert pack["selected"] <= {"SRC1#s1", "SRC2#s1", "SRC3#s1", "SRC4#s1"}
    assert "SRC1#s1" in pack["selected"] and "SRC2#s1" in pack["selected"]

    # focus → 分析师提示词侧
    block = render_segments_block(d, focus_segment_ids=kg_focus_segment_ids(d))
    assert "SRC1#s1" in block
    assert "二次定向研判" in block or "细读" in block or "关键段落" in block

    # pairs → 报告冲突节
    lines: list[str] = []
    _render_kg_conflict_pairs_section(lines, d)
    blob = "\n".join(lines)
    assert "交付窄面冲突成对" in blob
    assert "SRC1#s1" in blob and "SRC2#s1" in blob


def test_c107_no_surface_flag_on_still_zero_diff():
    d = _dossier_four()
    assert apply_kg_submit_surface(d, enabled=True) is None
    assert not d.accounting.get("kg_submit_active")
    a = pack_material(d, budget_chars=500)
    b = pack_material(d, budget_chars=500, **pack_kwargs_for_kg(d))
    assert a["selected"] == b["selected"]


def test_c107_boundaries_disclose_flag_and_borrow():
    desc = describe_boundaries()
    assert desc["flag"] == "VERITAS_KG_SUBMIT_SURFACE"
    assert desc["flag_default"] is False
    blob = " ".join(x["item"] for x in desc["borrowable"])
    assert "conflict_pairs" in blob
    assert "树17" in blob
    assert "一筛多维系数" in blob
