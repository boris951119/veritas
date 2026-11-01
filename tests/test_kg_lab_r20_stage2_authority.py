"""R20：意图／权威二筛／冲突对（无案情死锁、无问句相似度层）。"""

from __future__ import annotations

from app.kg_lab.event_frame import extract_event_frame, option_side
from app.kg_lab.portable_tags import publish_recency_unit
from app.kg_lab.question_intent import classify_intent, adjudication_queries
from app.kg_lab.stage2_authority import (
    DEFAULT_WEIGHTS,
    authority_rerank,
    build_conflict_pairs,
    portable_authority_unit,
)


def test_adjudicate_intent_from_or_question():
    q = "拖了11年才安置，是刘翔不愿走还是体育局未放行，哪一方说法站得住？"
    intent = classify_intent(q)
    assert intent.adjudication is True
    assert intent.kind == "adjudicate"
    views = adjudication_queries(q)
    kinds = {v["view"] for v in views}
    assert "conclusion" in kinds
    assert "evidence" in kinds
    assert not any(v["id"].startswith("cause") for v in views)


def test_stage2_weights_have_no_query_likeness_key():
    assert "query_sim" not in DEFAULT_WEIGHTS
    assert "bm25_q" not in DEFAULT_WEIGHTS
    assert "embed_q" not in DEFAULT_WEIGHTS
    assert "stage1" not in DEFAULT_WEIGHTS  # 骨干走 inbox，权威分不含问句相似


def test_authority_beats_commentary():
    feat_auth = {
        "authority_unit": 1.0,
        "verifiability": 0.9,
        "option_align": 0.5,
        "has_time_nail": 1.0,
        "publish_recency": 0.5,
        "title_option_hit": 0.0,
    }
    feat_cmt = {
        "authority_unit": 0.1,
        "verifiability": 0.0,
        "option_align": 0.5,
        "has_time_nail": 0.0,
        "publish_recency": 0.5,
        "title_option_hit": 0.0,
    }
    s_auth = portable_authority_unit(feat_auth, {"fine_role": "official_primary"})
    s_cmt = portable_authority_unit(feat_cmt, {"fine_role": "commentary"})
    assert s_auth > s_cmt


def test_option_side_does_not_cross_oppose_paraphrase():
    fr = extract_event_frame("是买断费还是自主择业经济补偿金，以哪方口径为准？")
    assert option_side("按规定给予了自主择业经济补偿金。", fr) == "option_b"
    assert option_side("应认定为买断费。", fr) == "option_a"


def test_conflict_pairs_expose_support_and_oppose():
    frame = extract_event_frame("是买断费还是自主择业经济补偿金，以哪方口径为准？")
    assert len(frame.options) >= 2
    feats = {
        "a": {"option_side": "option_a", "authority_unit": 0.9, "verifiability": 0.8},
        "b": {"option_side": "option_b", "authority_unit": 0.4, "verifiability": 0.2},
    }
    metas = {"a": {"fine_role": "official_primary"}, "b": {"fine_role": "commentary"}}
    pairs = build_conflict_pairs(["a", "b"], feats, metas, frame)
    assert pairs["support"]
    assert pairs["oppose"]
    assert pairs["conflicts"]
    assert pairs["conflicts"][0]["reason"] == "authority_over_similarity"
    assert pairs["conflicts"][0]["preferred"] == "a"


def test_publish_recency_newer_higher():
    assert publish_recency_unit("2026-03-15") > publish_recency_unit("2020-01-01")
    assert publish_recency_unit("") == 0.0


def test_authority_rerank_keeps_backbone_and_exposes_pairs():
    frame = extract_event_frame("是买断费还是自主择业经济补偿金？")
    stage1 = [("s1", 1.0), ("s2", 0.5), ("s3", 0.4)]
    pool = [("s1", 1.0), ("p_only", 0.8)]
    feats = {
        "s1": {
            "authority_unit": 0.8, "verifiability": 0.5, "option_align": 0.4,
            "has_time_nail": 1.0, "publish_recency": 0.6, "title_option_hit": 0.0,
            "option_side": "option_a", "authority_band": "official_channel",
        },
        "s2": {
            "authority_unit": 0.2, "verifiability": 0.1, "option_align": 0.1,
            "has_time_nail": 0.0, "publish_recency": 0.2, "title_option_hit": 0.0,
            "option_side": "option_b", "authority_band": "market",
        },
        "s3": {
            "authority_unit": 0.3, "verifiability": 0.2, "option_align": 0.1,
            "has_time_nail": 0.0, "publish_recency": 0.1, "title_option_hit": 0.0,
            "option_side": "neither", "authority_band": "unknown",
        },
        "p_only": {
            "authority_unit": 1.0, "verifiability": 0.9, "option_align": 0.7,
            "has_time_nail": 1.0, "publish_recency": 0.7, "title_option_hit": 0.5,
            "option_side": "option_b", "authority_band": "primary_source",
        },
    }
    metas = {
        "s1": {"fine_role": "official_reprint", "text": "认定为买断费", "title": "通报", "doc_id": "d1"},
        "s2": {"fine_role": "commentary", "text": "自主择业经济补偿金", "title": "评论", "doc_id": "d2"},
        "s3": {"fine_role": "commentary", "text": "其他", "title": "x", "doc_id": "d4"},
        "p_only": {"fine_role": "official_primary", "text": "自主择业经济补偿金", "title": "通报", "doc_id": "d3"},
    }
    texts = {k: metas[k]["text"] for k in metas}
    out = authority_rerank(
        stage1, pool, texts=texts, feats=feats, metas=metas,
        question="是买断费还是自主择业经济补偿金？", frame=frame,
        pool=5, k=3, use_inbox_dedup=False,
    )
    assert out["backbone"] == "inbox_stage1"
    assert out["no_query_likeness"] is True
    assert out["order"][0]["id"] == "s1"  # 骨干首位保留
    assert "conflict_pairs" in out
    assert out["conflict_pairs"]["conflicts"]
