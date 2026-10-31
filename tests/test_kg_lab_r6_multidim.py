"""R6 多维求和：问句没点名的主体不加分；口径两侧都算对齐。"""

from __future__ import annotations

from app.kg_lab.multidim_weight import (
    claim_align,
    combine_score,
    paragraph_features,
    subject_match,
)


def test_subject_requires_actor_in_question():
    text = "刘翔在微博写道：我已经买断。"
    assert subject_match("这笔钱算买断费还是补偿金？", "", text, "party_primary") == 0.0
    hit = subject_match("是刘翔不愿走还是体育局未放行？", "", text, "party_primary")
    mention_only = subject_match("是刘翔不愿走还是体育局未放行？", "", "刘翔曾担任教练。", "commentary")
    assert hit > mention_only
    assert hit > 0


def test_claim_aligns_either_side():
    q = "这笔49.4万元应认定为买断费还是自主择业经济补偿金？"
    assert claim_align(q, "按规定给予了自主择业经济补偿金。") == 1.0
    assert claim_align(q, "他发文称获得49.4万元买断费。") == 1.0
    assert claim_align(q, "当日天气晴好，观众入场。") == 0.0
    # 问句没提走留，段里只有原话、没有买断／补偿，这组不加分
    assert claim_align(q, "不是我不想走，而是你没让我走。") == 0.0


def test_amount_and_time_follow_the_question():
    money_q = "这笔49.4万元应认定为买断费还是经济补偿金？"
    walk_q = "拖了11年才安置，是刘翔不愿走还是体育局未放行？"
    body = "9月1日他交申请，获得49.4万元买断费，9月7日手续办完。"
    money = paragraph_features(money_q, title="", text=body, fine_role="commentary")
    walk = paragraph_features(walk_q, title="", text=body, fine_role="party_relay")
    assert money["amount_status"] == 1.0
    assert money["time_anchor"] == 0.0
    assert walk["amount_status"] == 0.0
    assert walk["time_anchor"] == 1.0
    assert walk["claim_align"] == 0.0


def test_score_is_a_sum_not_a_product():
    feats = {
        "subject_match": 1.0,
        "source_role": 1.0,
        "claim_align": 0.0,
        "amount_status": 0.0,
        "time_anchor": 0.0,
    }
    both = combine_score(0.05, feats, {"subject_match": 0.02, "source_role": 0.01})
    only_role = combine_score(0.05, feats, {"subject_match": 0.0, "source_role": 0.01})
    assert abs(both - (only_role + 0.02)) < 1e-9
    # 高角色分不能把主体匹配乘没
    assert both > only_role
