"""R28：树17引用规则——成对必读／可核验优先／标签／不读金标。"""

from __future__ import annotations

from app.kg_lab.tree17_cite import (
    LABEL_ACCEPT,
    LABEL_OPPOSE,
    LABEL_SUSPECT,
    apply_tree17_cite,
    plan_close_read,
    verifiability_score,
)


def test_verifiability_bulletin_beats_comment():
    bulletin = (
        "2026年8月26日10时52分，外交部发言人在例行记者会上通报：口岸伤亡 12 人。"
    )
    comment = "有分析认为，此次事件可能意味着区域局势进一步复杂化，值得注意。"
    assert verifiability_score(bulletin)["score"] > verifiability_score(comment)["score"]


def test_verifiability_en_report_beats_en_comment():
    """R41：英文初步报告／数额声明应高于英文综述评论。"""
    report = (
        "AAIB, in its preliminary report on June 12, said the crash killed "
        "241 of the 242 people on board after fuel was cut off."
    )
    comment = (
        "Experts say analysts believe the episode may reshape aviation safety "
        "debates; it is believed more talks will follow."
    )
    assert verifiability_score(report)["score"] > verifiability_score(comment)["score"]


def test_conflict_pair_must_cite_both_sides():
    """盒内两侧皆有 → 细读须成对；禁止只引一边。"""
    q = (
        "AI失控责任该由OpenAI管理层等企业承担，"
        "还是如Anthropic所主张由政府介入承担？"
    )
    metas = {
        "a#p1": {
            "text": (
                "2024年7月，OpenAI的失控智能体非法入侵系统，企业管理层承担责任。"
            ),
            "doc_id": "a",
        },
        "b#p1": {
            "text": (
                "Anthropic主张由政府介入控制自动化AI开发速度，美国政府控制前沿。"
            ),
            "doc_id": "b",
        },
        "c#p1": {
            "text": "专家认为全球治理需要多方协作与长期沟通。",
            "doc_id": "c",
        },
    }
    # 故意把综述放在盒首，检验成对规则不被 rank 挤掉
    box = ["c#p1", "a#p1", "b#p1"]
    plan = plan_close_read(box, metas=metas, question=q, close_k=2)
    assert plan["pair_required"] is True
    assert plan["both_sides_cited"] is True
    assert plan["pair_violation"] is False
    close_sides = {it["side"] for it in plan["items"] if it["in_close_read"]}
    assert "option_a" in close_sides
    assert "option_b" in close_sides


def test_labels_accept_oppose_suspect():
    q = (
        "AI失控责任该由OpenAI管理层等企业承担，"
        "还是由政府介入承担？"
    )
    metas = {
        "a#p1": {
            "text": "OpenAI失控智能体入侵，发言人确认企业管理层责任。2024年7月通报。",
            "doc_id": "a",
        },
        "b#p1": {
            "text": "呼吁政府介入控制自动化AI开发。Anthropic公开主张。",
            "doc_id": "b",
        },
    }
    plan = plan_close_read(
        ["a#p1", "b#p1"], metas=metas, question=q, close_k=2,
    )
    by = {it["para_id"]: it for it in plan["items"]}
    assert by["a#p1"]["label"] in {LABEL_ACCEPT, LABEL_SUSPECT}
    assert by["b#p1"]["label"] == LABEL_OPPOSE
    assert by["a#p1"]["stance"] == "support"
    assert by["b#p1"]["stance"] == "oppose"


def test_close_band_prefers_verifiable():
    q = "事故通报热线能否在2026年11月就绪启用？"
    metas = {
        "weak#p1": {
            "text": "有评论称双方或将继续沟通，业内人士认为前景不明。",
            "doc_id": "w",
        },
        "strong#p1": {
            "text": (
                "双方同意建立人工智能事件的沟通渠道。"
                "下次对话将于今年11月举行。外交部发言人确认。"
            ),
            "doc_id": "s",
        },
        "mid#p1": {
            "text": "中美人工智能对话机制仍在磋商中。",
            "doc_id": "m",
        },
    }
    plan = plan_close_read(
        ["weak#p1", "mid#p1", "strong#p1"],
        metas=metas, question=q, close_k=1,
    )
    assert plan["close_read"][0] == "strong#p1"


def test_l3_gold_is_disclosure_only_not_rule_input():
    """金标只进对照读数；计划在无金标时仍成对。"""
    q = (
        "责任该由OpenAI企业承担，还是由政府介入承担？"
    )
    metas = {
        "a#p1": {"text": "OpenAI企业管理层承担责任。2024年通报。", "doc_id": "a"},
        "b#p1": {"text": "政府介入控制自动化开发。", "doc_id": "b"},
    }
    out = apply_tree17_cite(
        ["a#p1", "b#p1"],
        metas=metas,
        question=q,
        close_k=2,
        gold_ids={"gold#never"},  # 故意不在盒内
        support_ids={"gold#never"},
    )
    assert out["plan"]["both_sides_cited"] is True
    assert out["l3"]["gold"]["in_close"] == 0
    assert "gold#never" not in out["plan"]["close_read"]


def test_non_conflict_no_pair_required():
    q = "中美AI对话机制应定性为危机管理安排吗？"
    metas = {
        "x#p1": {"text": "双方同意建立沟通渠道。", "doc_id": "x"},
        "y#p1": {"text": "对话将于今年11月举行。", "doc_id": "y"},
    }
    plan = plan_close_read(
        ["x#p1", "y#p1"], metas=metas, question=q, close_k=2,
    )
    # 单侧／非对立问句不成对强制
    assert plan["pair_required"] is False or plan["both_sides_cited"] is True
