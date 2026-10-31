"""R27：责任对立路由／繁简近同文／可核验独占置换。"""

from __future__ import annotations

from app.kg_lab.density_submit import (
    _fold_zh,
    _near_dup,
    _rep_quality,
    _resp_strength,
    pack_core_first,
)
from app.kg_lab.intent_routes import (
    is_claim_conflict_route,
    route_option_anchors,
    core_rank_score,
)
from app.kg_lab.source_role import _norm
from app.kg_lab.stage1_claim_holes import build_claim_hole_arm


def test_gov_corp_conflict_route_and_latin_half():
    q = (
        "AI失控责任该由OpenAI管理层等企业承担，"
        "还是如Anthropic、奥尔特曼所主张由政府介入承担？"
    )
    anchors = route_option_anchors(q)
    assert "OpenAI" in anchors["side_a"]
    assert "Anthropic" in anchors["side_b"]
    assert any("政府" in k for k in anchors["side_b"])
    assert is_claim_conflict_route(anchors)


def test_near_dup_folds_trad_simp_mirror():
    simp = (
        "7月，超1000名前沿AI实验室员工联名发布公开信，警告“自动化”AI研究的风险，"
        "呼吁美国政府控制自动化AI开发的前沿速度。9月，Anthropic公司首席执行官"
        "达里奥·阿莫迪发布长文。"
    )
    trad = (
        "7月，超1000名前沿AI實驗室員工聯名發布公開信，警告“自動化”AI研究的風險，"
        "呼吁美國政府控制自動化AI開發的前沿速度。9月，Anthropic公司首席執行官"
        "達裡奧·阿莫迪發布長文。"
    )
    assert _fold_zh(simp)[:40] == _fold_zh(_norm(trad))[:40] or _near_dup(
        _norm(simp), _norm(trad),
    )
    assert _near_dup(_norm(simp), _norm(trad))


def test_rep_quality_prefers_trad_gov_over_simp_mirror():
    simp = (
        "7月，超1000名前沿AI实验室员工联名发布公开信，警告自动化AI研究的风险，"
        "呼吁美国政府控制自动化AI开发的前沿速度。Anthropic公司发布长文。"
    )
    trad = (
        "7月，超1000名前沿AI實驗室員工聯名發布公開信，警告自動化AI研究的風險，"
        "呼吁美國政府控制自動化AI開發的前沿速度。Anthropic公司發布長文。"
    )
    metas = {
        "s#p1": {"text": simp, "doc_id": "s"},
        "t#p1": {"text": trad, "doc_id": "t"},
    }
    feats = {
        "s#p1": {"verifiability": 0.8, "authority_unit": 0.7},
        "t#p1": {"verifiability": 0.8, "authority_unit": 0.7},
    }
    assert _rep_quality("t#p1", feats=feats, metas=metas) > _rep_quality(
        "s#p1", feats=feats, metas=metas,
    )


def test_soft_pack_swaps_bare_name_for_strong_resp():
    bare = (
        "从芯片到模型、再到数据中心，AI企业正在加快构建覆盖全产业链的技术体系。"
        "Anthropic与联合国秘书长也谈及全球治理。"
    )
    strong = (
        "在该事件中，OpenAI的失控智能体突破安全隔离机制、非法入侵Hugging Face系统，"
        "各界对AI超速发展的风险产生极大担忧。"
    )
    gov = (
        "呼吁美国政府控制自动化AI开发的前沿速度。Anthropic公司首席执行官发布长文，"
        "称自我改进带来的AI加速可能造成灾难性影响。"
    )
    metas = {
        "bare#p1": {"text": bare, "doc_id": "bare", "channel": "other"},
        "oa#p1": {"text": strong, "doc_id": "oa", "channel": "other"},
        "gov#p1": {"text": gov, "doc_id": "gov", "channel": "other"},
    }
    band = {
        "verifiability": 0.8, "authority_unit": 0.8,
        "authority_band": "official_channel", "option_side": "",
        "frame_align": 0.4, "option_align": 0.4, "has_time_nail": 0.0,
    }
    feats = {pid: dict(band) for pid in metas}
    anchors = {
        "side_a": ["OpenAI"],
        "side_b": ["政府介入", "Anthropic", "政府控制"],
        "soft": ["失控", "责任"],
    }
    pool_pos = {pid: i for i, pid in enumerate(metas, 1)}
    packed, cores, _ = pack_core_first(
        ["bare#p1", "oa#p1", "gov#p1"],
        feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
    )
    assert "oa#p1" in cores
    assert "gov#p1" in cores
    # 可核验独占应排在裸专名路过之前
    if "bare#p1" in packed:
        assert packed.index("oa#p1") < packed.index("bare#p1")


def test_claim_hole_boosts_resp_exclusive():
    rows = [
        {
            "para_id": "oa#p1",
            "text": (
                "OpenAI的失控智能体突破安全隔离机制、非法入侵Hugging Face系统，"
                "责任主要在企业管理层。"
            ),
        },
        {
            "para_id": "gov#p1",
            "text": (
                "呼吁美国政府控制自动化AI开发的前沿速度。"
                "Anthropic公司首席执行官发布长文主张政府介入。"
            ),
        },
        {
            "para_id": "soft#p1",
            "text": "人工智能全球治理需要多方协作与责任保险。",
        },
    ]
    q = (
        "AI失控责任该由OpenAI管理层等企业承担，"
        "还是如Anthropic所主张由政府介入承担？"
    )
    built = build_claim_hole_arm(rows, q)
    sc = dict(built["arm"])
    assert sc.get("oa#p1", 0) > sc.get("soft#p1", 0)
    assert sc.get("gov#p1", 0) > sc.get("soft#p1", 0)


def test_core_rank_boosts_strong_resp_exclusive():
    anchors = {
        "side_a": ["OpenAI"],
        "side_b": ["政府介入", "Anthropic", "政府控制"],
        "soft": ["失控"],
    }
    metas = {
        "oa#p1": {
            "text": "OpenAI的失控智能体非法入侵Hugging Face系统。",
            "doc_id": "oa", "channel": "other",
        },
        "bare#p1": {
            "text": "Anthropic与产业伙伴讨论全球治理议程安排。",
            "doc_id": "bare", "channel": "other",
        },
    }
    feats = {
        pid: {
            "verifiability": 0.8, "authority_unit": 0.7,
            "authority_band": "official_channel", "option_side": "",
            "frame_align": 0.4, "option_align": 0.4, "has_time_nail": 0.0,
        }
        for pid in metas
    }
    pool_pos = {"oa#p1": 3, "bare#p1": 2}
    sc_oa = core_rank_score(
        "oa#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
    )
    sc_bare = core_rank_score(
        "bare#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
    )
    assert sc_oa > sc_bare
    assert _resp_strength(metas, "oa#p1") > _resp_strength(metas, "bare#p1")
