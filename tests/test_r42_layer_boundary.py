"""R42：低耦合拆装——交卷窄面禁系数／pack hints 可接。"""

from __future__ import annotations

import pytest

from app.kg_lab.layer_boundary import (
    FORBIDDEN_PACK_KEYS,
    assert_submit_no_coeff,
    audit_forbidden_keys,
    borrowable_checklist,
    build_submit_surface,
    describe_boundaries,
    pack_hints_from_submit,
    stage1_pool_export,
    stage2_box_export,
    tree17_signal_export,
)


def test_stage1_export_has_no_coeff_keys():
    out = stage1_pool_export([("a#p1", 0.9), ("b#p2", 0.5)], pool_n=20)
    assert out["layer"] == "stage1_pool"
    assert out["pool_ids"] == ["a#p1", "b#p2"]
    assert audit_forbidden_keys(out) == []


def test_stage2_strips_authority_floats_from_pairs():
    auth = {
        "top_ids": ["s1", "o1", "x"],
        "k": 2,
        "conflict_pairs": {
            "options": ["A", "B"],
            "support": [{"id": "s1", "option": "A"}],
            "oppose": [{"id": "o1", "option": "B"}],
            "conflicts": [{
                "support_id": "s1",
                "oppose_id": "o1",
                "support_option": "A",
                "oppose_option": "B",
                "support_authority": 0.88,
                "oppose_authority": 0.12,
                "preferred": "s1",
                "reason": "authority_over_similarity",
            }],
        },
        "density": {"k": 2, "n_core": 2, "met_target": True, "proxy_density": 1.0},
        "intent": {"route": "adjudicate"},
        "swallowed": ["z"],
        "near_dup_dropped": [],
    }
    box = stage2_box_export(auth)
    assert box["box_ids"] == ["s1", "o1"]
    assert box["k"] == 2
    conf = box["conflict_pairs"]["conflicts"][0]
    assert "support_authority" not in conf
    assert "oppose_authority" not in conf
    assert conf["support_id"] == "s1"
    assert audit_forbidden_keys(box) == []


def test_submit_rejects_coeff_injection():
    box = {
        "box_ids": ["a", "b"],
        "k": 2,
        "conflict_pairs": {"options": [], "support": [], "oppose": [], "conflicts": []},
        "density_public": {},
        "route": "fact_check",
    }
    surface = build_submit_surface(box, tree17_plan={
        "close_read": ["a"],
        "pair_required": False,
        "conflict_route": False,
        "items": [{"para_id": "a", "in_close_read": True, "label": "采信", "side": "none", "stance": "support"}],
    })
    assert_submit_no_coeff(surface)
    hints = pack_hints_from_submit(surface)
    assert hints["priority_segment_ids"] == ["a", "b"]
    assert hints["focus_segment_ids"] == ["a"]
    assert hints["max_segments"] == 2
    assert audit_forbidden_keys(hints) == []
    # 故意污染：应被审计抓住
    dirty = {**surface, "coeff": {"authority": 0.4}}
    assert any(h.endswith(".coeff") for h in audit_forbidden_keys(dirty))
    with pytest.raises(AssertionError):
        assert_submit_no_coeff(dirty)


def test_tree17_signal_no_verifiability_blob():
    sig = tree17_signal_export({
        "close_read": ["p1"],
        "pair_required": True,
        "conflict_route": True,
        "items": [{
            "para_id": "p1",
            "in_close_read": True,
            "label": "对立",
            "side": "option_b",
            "stance": "oppose",
            "verifiability": {"score": 0.9, "time_n": 2},
        }],
    })
    assert sig["close_read_ids"] == ["p1"]
    assert sig["pair_required"] is True
    assert "verifiability" not in sig["labels"][0]
    assert audit_forbidden_keys(sig) == []


def test_borrowable_checklist_covers_required_items():
    items = borrowable_checklist()
    blob = " ".join(x["item"] for x in items)
    for needle in ("可变 k", "conflict_pairs", "通稿", "繁简", "树17", "一筛多维系数"):
        assert needle in blob
    for row in items:
        assert row["layer"]
        assert row["mainline_hook"]
        assert row["module"]
    desc = describe_boundaries()
    assert "mainline_pack" in desc["layers"]
    assert set(FORBIDDEN_PACK_KEYS) <= set(desc["layers"]["mainline_pack"]["must_not_accept"])
