"""R26：口径声部优先／短通稿罚分／簇代表偏短／同侧第 2 精确槽。"""

from __future__ import annotations

from app.kg_lab.density_submit import (
    _near_dup,
    _rep_quality,
    density_constrained_submit,
    pack_core_first,
)
from app.kg_lab.intent_routes import core_rank_score
from app.kg_lab.source_role import _norm
from app.kg_lab.stage1_claim_holes import build_claim_hole_arm


def test_wire_pen_spares_long_exclusive():
    """长 wire_relay 独占不应再吃满额通稿罚分。"""
    short = "8月26日10时30分许，因尼泊尔一侧发生泥石流灾害，造成口岸失联。"
    long = (
        "北京时间2026年8月26日上午10时52分左右，尼泊尔境内一条冰川在海拔约5200米处"
        "断裂发生冰岩崩，高位快速坠落冲刷山体形成巨型泥石流，仅数分钟直达口岸。"
        + "现场损毁细节。" * 6
    )
    anchors = {
        "side_a": ["5200米", "冰岩崩"],
        "side_b": ["冰湖溃决", "溃决"],
        "soft": [],
    }
    metas = {
        "short#p1": {"text": short, "doc_id": "short", "channel": "other"},
        "long#p1": {"text": long, "doc_id": "long", "channel": "other"},
    }
    feats = {
        "short#p1": {
            "verifiability": 0.67, "authority_unit": 0.75,
            "authority_band": "wire_relay", "option_side": "option_a",
            "frame_align": 0.3, "option_align": 0.4, "has_time_nail": 1.0,
        },
        "long#p1": {
            "verifiability": 1.0, "authority_unit": 0.75,
            "authority_band": "wire_relay", "option_side": "option_a",
            "frame_align": 0.5, "option_align": 0.5, "has_time_nail": 1.0,
        },
    }
    pool_pos = {"short#p1": 2, "long#p1": 3}
    sc_s = core_rank_score(
        "short#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
    )
    sc_l = core_rank_score(
        "long#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
    )
    assert sc_l > sc_s


def test_rep_quality_prefers_short_precise_over_long_wire():
    short = (
        "北京时间8月26日上午10时52分左右，冰川在海拔约5200米处断裂发生冰岩崩，"
        "冲刷形成泥石流直达口岸。"
    )
    long = short + ("附属设施与救援进展细节。" * 20)
    metas = {
        "s#p1": {"text": short, "doc_id": "s"},
        "l#p1": {"text": long, "doc_id": "l"},
    }
    feats = {
        "s#p1": {"verifiability": 0.8, "authority_unit": 0.7},
        "l#p1": {"verifiability": 0.9, "authority_unit": 0.8},
    }
    assert _rep_quality("s#p1", feats=feats, metas=metas) > _rep_quality(
        "l#p1", feats=feats, metas=metas,
    )


def test_caliber_voice_pack_beats_cause_finding_both():
    """两侧声部独占齐后，成因综述弱双侧排在发布会弱双侧之后。"""
    voice_a = (
        "外交部发言人林剑主持例行记者会。记者问：因尼泊尔一侧发生泥石流灾害，造成口岸伤亡失联。"
    )
    voice_b = (
        "联合国秘书长古特雷斯声明：对尼泊尔洪灾深感悲痛，向受灾民众表示声援。"
    )
    cause_both = (
        "专家综合分析认为，灾害源头在尼泊尔一侧泥石流，亦有洪灾说法。"
    )
    soft_both = (
        "泥石流灾害新闻发布会介绍：灾害暴发突然、洪峰流量大，监测发现冰岩崩冲击口岸。"
    )
    metas = {
        "va#p1": {"text": voice_a, "doc_id": "va", "channel": "wire"},
        "vb#p1": {"text": voice_b, "doc_id": "vb", "channel": "other"},
        "cb#p1": {"text": cause_both, "doc_id": "cb", "channel": "other"},
        "sb#p1": {"text": soft_both, "doc_id": "sb", "channel": "other"},
    }
    band = {
        "verifiability": 0.8, "authority_unit": 0.8,
        "authority_band": "official_channel", "option_side": "",
        "frame_align": 0.4, "option_align": 0.4, "has_time_nail": 0.0,
    }
    feats = {pid: dict(band) for pid in metas}
    anchors = {
        "side_a": ["泥石流"],
        "side_b": ["洪灾", "山崩", "冰岩崩"],
        "soft": [],
    }
    pool_pos = {pid: i for i, pid in enumerate(metas, 1)}
    packed, cores, _ = pack_core_first(
        ["va#p1", "vb#p1", "cb#p1", "sb#p1"],
        feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
    )
    assert "va#p1" in cores
    assert "vb#p1" in cores
    # 声部独占应排在成因综述弱双侧之前
    assert packed.index("va#p1") < packed.index("cb#p1")
    assert packed.index("vb#p1") < packed.index("cb#p1")


def test_claim_hole_boosts_caliber_voice_over_chaming_both():
    rows = [
        {
            "para_id": "voice#p1",
            "text": "外交部发言人就泥石流灾害答记者问，介绍中方救灾情况。",
        },
        {
            "para_id": "chaming#p1",
            "text": (
                "西藏吉隆泥石流灾害原因现已查明，团队综合认为冰川断裂发生冰岩崩，"
                "亦涉及洪灾山崩表述。"
            ),
        },
    ]
    q = "中方称泥石流、联合国与尼泊尔称洪灾或山崩，评估时应采用哪一口径？"
    built = build_claim_hole_arm(rows, q)
    sc = dict(built["arm"])
    assert sc.get("voice#p1", 0) > sc.get("chaming#p1", 0)


def test_second_precise_slot_keeps_short_clock_claim():
    """同侧第 2 槽留给短精确＋钟点段，长通稿／查明换皮不占。"""
    head = (
        "2026年8月30日消息，从新闻发布会上获悉，灾害原因现已查明，"
        "北京时间8月26日上午10时52分左右，冰川在海拔约5200米处断裂发生冰岩崩。"
    )
    short = (
        "北京时间2026年8月26日上午10时52分左右，尼泊尔境内冰川在海拔约5200米处"
        "断裂发生冰岩崩，冲刷形成泥石流直达口岸。"
    )
    long = short + ("现场损毁与救援细节补充。" * 25)
    metas = {
        "h#p1": {"text": head, "doc_id": "h", "channel": "other"},
        "s#p1": {"text": short, "doc_id": "s", "channel": "other"},
        "l#p1": {"text": long, "doc_id": "l", "channel": "other"},
        "b#p1": {
            "text": "科研人员发现冰岩崩后形成新冰湖，强调加强冰湖溃决监测。",
            "doc_id": "b", "channel": "other",
        },
    }
    feats = {
        pid: {
            "verifiability": 0.9, "authority_unit": 0.8,
            "authority_band": "official_channel" if pid != "l#p1" else "wire_relay",
            "option_side": "option_a", "frame_align": 0.5, "option_align": 0.5,
            "has_time_nail": 1.0,
        }
        for pid in metas
    }
    feats["b#p1"]["option_side"] = "both"
    anchors = {
        "side_a": ["5200米", "冰岩崩", "冰川断裂"],
        "side_b": ["冰湖溃决", "溃决"],
        "soft": [],
    }
    pool_pos = {pid: i for i, pid in enumerate(metas, 1)}
    packed, cores, _ = pack_core_first(
        ["h#p1", "l#p1", "s#p1", "b#p1"],
        feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
    )
    assert "h#p1" in cores
    assert "s#p1" in cores
    # 长通稿不应挤掉短精确第 2 槽
    if "l#p1" in cores:
        assert cores.index("s#p1") < cores.index("l#p1")


def test_near_dup_still_merges_press_rewrite():
    shared = (
        "西藏吉隆泥石流灾害原因现已查明，中国科学院成都山地所冰冻圈应急减灾团队通过分析遥感监测数据"
        "和现场回传资料，结合实地踏勘走访综合认为：北京时间8月26日上午10时52分左右，尼泊尔境内"
        "蓝塘里壤峰北坡一条冰川在海拔约5200米处断裂发生冰岩崩"
    )
    a = _norm("新华社电 记者从新闻发布会获悉，" + shared + "，直达吉隆口岸。")
    b = _norm("2026年8月30日消息，从新闻发布会上获悉，" + shared + "，附属设施被夷为平地。")
    assert _near_dup(a, b)
