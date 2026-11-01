"""R19：事件框架与查询视图（无硬族）。"""

from __future__ import annotations

from app.kg_lab.event_frame import (
    extract_event_frame,
    extract_options,
    frame_align_score,
    option_paraphrases,
)
from app.kg_lab.query_views import rule_query_views
from app.kg_lab.tag_schema import EVENT_FRAME_KEYS, STAGE1_FEATURES


def test_schema_has_portable_event_frame_keys():
    assert "frame_align" in STAGE1_FEATURES
    assert "authority_unit" in STAGE1_FEATURES
    assert "frame_align" in EVENT_FRAME_KEYS


def test_options_from_or_question_without_hard_family():
    q = "拖了11年才安置，是刘翔不愿走还是体育局未放行，哪一方说法站得住？"
    fr = extract_event_frame(q)
    assert "刘翔" in fr.actors
    assert "体育局" in fr.actors
    assert any("不愿" in o or "未放行" in o or "体育局" in o for o in fr.options)
    assert not hasattr(fr, "active_families")
    # 近义扩展命中金标原话
    paras = option_paraphrases("刘翔不愿走")
    assert any("不想走" in p for p in paras)


def test_zhun_or_keeps_time_options():
    q = (
        "吉隆口岸泥石流灾害的起始时刻，应以官方通稿的8月26日10时30分许为准，"
        "还是以监控记录的10时52分至59分为准？"
    )
    opts = extract_options(q)
    assert len(opts) >= 2
    assert any("10时30" in o or "30分" in o for o in opts)
    assert any("10时52" in o or "52分" in o for o in opts)
    assert not any(o.startswith("0分") for o in opts)


def test_rending_options_money():
    q = "这笔49.4万元应认定为买断费还是自主择业经济补偿金，以哪方口径为准？"
    opts = extract_options(q)
    assert any("买断" in o for o in opts)
    assert any("自主择业" in o or "补偿金" in o for o in opts)


def test_quote_claim_as_option():
    q = "刘翔退役至今是否真有编制与岗位，官方称其在编不在岗能否以人事档案证实？"
    fr = extract_event_frame(q)
    assert any("在编不在岗" in o for o in fr.options) or "在编" in fr.qual_predicates


def test_frame_align_prefers_option_hit():
    fr = extract_event_frame("是买断费还是自主择业经济补偿金，以哪方口径为准？")
    assert len(fr.options) >= 2
    a = fr.options[0]
    s_a = frame_align_score(f"官方认定为{a}。", fr)
    s_none = frame_align_score("今天天气不错。", fr)
    assert s_a > s_none


def test_frame_align_paraphrase_hit():
    fr = extract_event_frame("是刘翔不愿走还是体育局未放行？")
    s = frame_align_score("不是我不想走，而是你没让我走", fr)
    assert s > 0.0


def test_query_views_include_conclusion_cause_evidence():
    q = "双方同意建立中美人工智能对话，交流相关风险和惠益，是否属官方口径？"
    views = rule_query_views(q)
    kinds = {v["view"] for v in views}
    assert "conclusion" in kinds or "raw" in kinds
    assert "cause" in kinds
    assert "evidence" in kinds


def test_query_views_include_option_paraphrase_core():
    q = "是刘翔不愿走还是体育局未放行，哪一方说法站得住？"
    views = rule_query_views(q)
    blob = " ".join(v["query"] for v in views)
    assert "不想走" in blob or "没让我走" in blob
