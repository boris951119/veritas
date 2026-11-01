"""R43：造谣核对第二澄清——具体否认进盒，谣言复述壳让位（无案专名）。"""

from __future__ import annotations

from app.kg_lab.density_submit import density_constrained_submit
from app.kg_lab.intent_routes import (
    is_clarify_rumor_shell,
    is_clarify_substance,
    is_core_candidate,
    slot_align_detail,
    stage2_verifiable_slots,
)


def _slots():
    return stage2_verifiable_slots(
        '流传的「北大无人肯写推荐信」「因绩点不足未保研」「缺席毕业合照」等是否属实？'
    )


def test_quote_slot_counts_three_char_claim():
    slots = _slots()
    strong, _ = slot_align_detail(
        "赴法留学得到了数学科学学院教师的推荐信，并告知已录取。",
        slots,
    )
    assert strong >= 1


def test_substance_vs_rumor_shell_portable():
    slots = _slots()
    substance = (
        "知情者说，实际上获得了至少三名教师的推荐信，并非无人肯写推荐信。"
        "原院长回应称具备保研资格。"
    )
    rumor = (
        "有消息称无人肯写推荐信，缺席毕业合照，因绩点不足未保研。"
        "如今的回应澄清了事实，当事人并非一个郁郁不得志的人。"
    )
    assert is_clarify_substance(substance)
    assert not is_clarify_rumor_shell(substance, slots)
    assert not is_clarify_substance(rumor)
    assert is_clarify_rumor_shell(rumor, slots)
    src = open("app/kg_lab/intent_routes.py", encoding="utf-8").read()
    assert "王虹" not in src


def test_clarify_substance_beats_rumor_in_density_box():
    slots = _slots()
    feats = {
        "first#p1": {"verifiability": 0.2, "authority_unit": 0.3, "authority_band": "market",
                     "option_side": "", "option_align": 0.5},
        "second#p1": {"verifiability": 0.67, "authority_unit": 0.45, "authority_band": "wire_relay",
                      "option_side": "", "option_align": 0.5},
        "rumor#p1": {"verifiability": 0.0, "authority_unit": 0.25, "authority_band": "market",
                     "option_side": "", "option_align": 0.5},
        "rumor#p2": {"verifiability": 0.0, "authority_unit": 0.25, "authority_band": "market",
                     "option_side": "", "option_align": 0.5},
    }
    metas = {
        "first#p1": {
            "text": "知情者说实际上获得了三名教师推荐信，并非无人肯写推荐信。原院长回应保研问题。",
            "doc_id": "first",
        },
        "second#p1": {
            "text": "关于推荐信与出国深造，当事人得到了本院教师甲、乙、丙等的推荐信。",
            "doc_id": "second",
        },
        "rumor#p1": {
            "text": "有消息称无人肯写推荐信，缺席毕业合照，因绩点不足未保研，真假难辨。",
            "doc_id": "rumor",
        },
        "rumor#p2": {
            "text": "绩点末位勉强毕业、数学系不给写推荐信、缺席毕业合照等等。"
                    "的回应澄清了事实，当事人并非一个郁郁不得志的人。",
            "doc_id": "rumor2",
        },
    }
    pool_pos = {"first#p1": 4, "second#p1": 48, "rumor#p1": 8, "rumor#p2": 6}
    for pid in feats:
        assert is_core_candidate(
            pid, feats=feats, metas=metas, route="adjudicate",
            pool_pos=pool_pos, slots=slots,
        ) == (pid.startswith("first") or pid.startswith("second"))
    order = ["rumor#p2", "first#p1", "rumor#p1", "second#p1"]
    out = density_constrained_submit(
        order, feats=feats, metas=metas, route="adjudicate",
        k_min=3, k_max=7, pool_pos=pool_pos, slots=slots,
        gold_ids={"first#p1", "second#p1"},
    )
    box = out["submission"]
    assert "first#p1" in box
    assert "second#p1" in box
    assert "rumor#p1" not in box or box.index("first#p1") < box.index("rumor#p1")
    assert out["n_gold"] >= 2
    assert out["gold_density"] + 1e-12 >= 2 / 3
