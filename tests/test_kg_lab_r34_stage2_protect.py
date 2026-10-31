"""R34：二筛可核验槽保位／抗通稿壳（无案专名硬编码）。"""

from __future__ import annotations

from app.kg_lab.density_submit import pack_core_first
from app.kg_lab.intent_routes import (
    core_rank_score,
    is_core_candidate,
    looks_like_wire_shell,
    related_filler,
    slot_align_detail,
    stage2_verifiable_slots,
)


def test_stage2_slots_pull_latin_quote_and_nouns_no_case_lexicon():
    q = (
        '某人说的 discouraged 原意指什么？'
        '流传的「无人肯写推荐信」是否属实？'
    )
    slots = stage2_verifiable_slots(q)
    assert "discouraged" in slots["latin"]
    assert any("推荐信" in x for x in (slots.get("quotes") or []))
    assert any("推荐信" in n or "原意" in n for n in (slots.get("nouns") or []) + [""])
    src = open("app/kg_lab/intent_routes.py", encoding="utf-8").read()
    assert "王虹" not in src and "柬泰" not in src and "AI171" not in src


def test_slot_align_strong_vs_weak_and_wire_shell():
    slots = stage2_verifiable_slots(
        "泰方称柬方率先开火，2025年12月冲突谁先动武？F-16 是否介入？"
    )
    strong, weak = slot_align_detail(
        "On December 8, 2025 Thai F-16 forces launched an attack after clashes.",
        slots,
    )
    assert strong >= 3  # F-16 + year-month + EN conflict
    # 裸年份不算强槽（防裁决题 2026 灌盒）
    year_only = stage2_verifiable_slots("2026年11月热线能否就绪？WIRED怎么说？")
    s_bare, _ = slot_align_detail("多位代表参加了2026年人工智能对话。", year_only)
    assert s_bare == 0
    assert not looks_like_wire_shell(
        "On December 8, 2025 Thai F-16 launched an attack after clashes.",
        slot_hits=strong,
    )
    assert looks_like_wire_shell(
        "以下是多方综合报道时间线速览，持续关注。",
        slot_hits=0,
    )
    # 汇总壳即使撞到关键词仍判壳
    assert looks_like_wire_shell(
        "汇总多方信源，描述访谈中的 discouraged 一词如何引爆。",
        slot_hits=2,
    )


def test_claim_noun_weapon_aid_is_strong():
    slots = stage2_verifiable_slots(
        "西方媒体称中国向柬埔寨提供大量武器援助偏帮一方，是否有证据？"
    )
    assert any("援助" in n for n in (slots.get("claim_nouns") or []))
    strong, _ = slot_align_detail(
        "有记者提问称近期有西方媒体报道中国向柬埔寨提供大量武器援助。",
        slots,
    )
    assert strong >= 1


def test_fact_check_strong_slot_beats_wire_shell_in_pack():
    q = '「无人肯写推荐信」说法是否属实？discouraged 原意？'
    slots = stage2_verifiable_slots(q)
    feats = {
        "gold#p1": {
            "verifiability": 0.4,
            "authority_unit": 0.4,
            "authority_band": "media_report",
            "option_side": "",
            "wire_relay": 0.0,
        },
        "wire#p1": {
            "verifiability": 0.2,
            "authority_unit": 0.7,
            "authority_band": "official_channel",
            "option_side": "",
            "wire_relay": 0.8,
        },
        "shell#p1": {
            "verifiability": 0.1,
            "authority_unit": 0.75,
            "authority_band": "official_channel",
            "option_side": "",
            "wire_relay": 0.9,
        },
    }
    metas = {
        "gold#p1": {
            "text": "访谈原话说 discouraged，并否认无人肯写推荐信。",
            "doc_id": "gold",
            "channel": "interview",
        },
        "wire#p1": {
            "text": "官方媒体转载综述，未涉及关键词。",
            "doc_id": "wire",
            "channel": "wire",
        },
        "shell#p1": {
            "text": "以下是多方综合报道时间线速览，持续关注最新消息汇总。",
            "doc_id": "shell",
            "channel": "wire",
        },
    }
    pool_pos = {"gold#p1": 5, "wire#p1": 2, "shell#p1": 1}
    assert is_core_candidate(
        "gold#p1", feats=feats, metas=metas, route="fact_check",
        pool_pos=pool_pos, slots=slots,
    )
    assert not related_filler(
        "shell#p1", feats=feats, metas=metas, route="fact_check",
        pool_pos=pool_pos, slots=slots,
    )
    g_sc = core_rank_score(
        "gold#p1", feats=feats, metas=metas, route="fact_check",
        pool_pos=pool_pos, slots=slots,
    )
    w_sc = core_rank_score(
        "wire#p1", feats=feats, metas=metas, route="fact_check",
        pool_pos=pool_pos, slots=slots,
    )
    assert g_sc > w_sc
    packed, cores, _fill = pack_core_first(
        ["shell#p1", "wire#p1", "gold#p1"],
        feats=feats, metas=metas, route="fact_check",
        pool_pos=pool_pos, slots=slots,
    )
    assert "gold#p1" in cores
    assert packed[0] == "gold#p1" or "gold#p1" in packed[:2]


def test_adjudicate_latin_alone_does_not_flood_core():
    """裁决题：裸拉丁无侧锚不得整篇灌核心（保中美AI）。"""
    slots = stage2_verifiable_slots(
        "AI失控责任该由OpenAI管理层等企业承担，还是如Anthropic所主张？"
    )
    feats = {
        "flood#p1": {
            "verifiability": 0.2,
            "authority_unit": 0.3,
            "authority_band": "media_report",
            "option_side": "",
        },
    }
    metas = {
        "flood#p1": {
            "text": "OpenAI released a blog about GPT models and APIs.",
            "doc_id": "flood",
            "channel": "blog",
        },
    }
    pool_pos = {"flood#p1": 3}
    assert not is_core_candidate(
        "flood#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, slots=slots, anchors={"side_a": ["企业"], "side_b": ["政府"]},
    )
