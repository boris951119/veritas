"""R24：池内金标进盒——通稿近同文簇去重＋双侧优先。"""

from __future__ import annotations

from app.kg_lab.density_submit import (
    _near_dup,
    density_constrained_submit,
    pack_core_first,
)
from app.kg_lab.intent_routes import core_rank_score
from app.kg_lab.source_role import _norm


def _feats_meta_wire_cluster():
    """三份单侧通稿近同文 + 一份双侧可核验段。"""
    wire = "8月26日10时30分许，因尼泊尔一侧发生泥石流灾害，造成西藏日喀则市吉隆县吉隆口岸重大人员伤亡、失联。"
    variants = [
        wire,
        "2026年" + wire,
        "2026年8月26日10时30分许，因尼泊尔一侧发生泥石流灾害，造成吉隆口岸重大人员伤亡、失联。",
    ]
    both = (
        "北京时间2026年8月26日上午10时52分左右，尼泊尔境内蓝塘里壤峰北坡一条冰川在海拔约5200米处断裂"
        "发生冰岩崩；官方通稿则写8月26日10时30分许。"
    )
    metas = {
        "w1#p1": {"text": variants[0], "doc_id": "w1", "channel": "other",
                  "portable_role": "media_relay", "title": "通稿A"},
        "w2#p1": {"text": variants[1], "doc_id": "w2", "channel": "other",
                  "portable_role": "media_relay", "title": "通稿B"},
        "w3#p1": {"text": variants[2], "doc_id": "w3", "channel": "other",
                  "portable_role": "media_relay", "title": "通稿C"},
        "both#p1": {"text": both, "doc_id": "both", "channel": "other",
                    "portable_role": "media_relay", "title": "对撞段"},
    }
    feats = {
        "w1#p1": {
            "verifiability": 0.67, "authority_unit": 0.75,
            "authority_band": "official_channel", "option_side": "option_a",
            "frame_align": 0.3, "option_align": 0.4, "has_time_nail": 0.0,
        },
        "w2#p1": {
            "verifiability": 0.67, "authority_unit": 0.75,
            "authority_band": "official_channel", "option_side": "option_a",
            "frame_align": 0.3, "option_align": 0.4, "has_time_nail": 0.0,
        },
        "w3#p1": {
            "verifiability": 1.0, "authority_unit": 0.75,
            "authority_band": "official_channel", "option_side": "option_a",
            "frame_align": 0.3, "option_align": 0.4, "has_time_nail": 0.0,
        },
        "both#p1": {
            "verifiability": 1.0, "authority_unit": 0.75,
            "authority_band": "official_channel", "option_side": "both",
            "frame_align": 0.5, "option_align": 0.5, "has_time_nail": 1.0,
        },
    }
    anchors = {
        "side_a": ["8月26", "10时30分", "通稿"],
        "side_b": ["10时52分", "监控"],
        "soft": ["泥石流"],
    }
    pool_pos = {"w1#p1": 1, "w2#p1": 2, "w3#p1": 3, "both#p1": 4}
    return metas, feats, anchors, pool_pos


def test_near_dup_catches_wire_variants():
    a = _norm("8月26日10时30分许，因尼泊尔一侧发生泥石流灾害，造成西藏日喀则市吉隆县吉隆口岸重大人员伤亡、失联。")
    b = _norm("2026年8月26日10时30分许，因尼泊尔一侧发生泥石流灾害，造成吉隆口岸重大人员伤亡、失联。")
    assert _near_dup(a, b)


def test_near_dup_spares_weak_overlap_long_siblings():
    """仅短共引、低 Jaccard 的长段不并簇。"""
    a = _norm(
        "北京时间8月26日上午10时52分左右发生冰岩崩。" + "现场损毁情况如下。" * 8
    )
    b = _norm(
        "新闻发布会称灾害原因另有解释。" + "专家强调预警窗口极短。" * 8
    )
    assert not _near_dup(a, b)


def test_near_dup_merges_press_rewrite():
    """同一查明结论的发布会换皮应并簇。"""
    shared = (
        "西藏吉隆泥石流灾害原因现已查明，中国科学院成都山地所冰冻圈应急减灾团队通过分析遥感监测数据"
        "和现场回传资料，结合实地踏勘走访综合认为：北京时间8月26日上午10时52分左右，尼泊尔境内"
        "蓝塘里壤峰北坡一条冰川在海拔约5200米处断裂发生冰岩崩"
    )
    a = _norm("新华社电 记者从新闻发布会获悉，" + shared + "，直达吉隆口岸。")
    b = _norm("2026年8月30日消息，从新闻发布会上获悉，" + shared + "，附属设施被夷为平地。")
    assert _near_dup(a, b)


def test_pack_keeps_one_wire_and_both_side():
    metas, feats, anchors, pool_pos = _feats_meta_wire_cluster()
    order = ["w1#p1", "w2#p1", "w3#p1", "both#p1"]
    packed, cores, _fill = pack_core_first(
        order, feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
    )
    wire_in = [p for p in cores if p.startswith("w")]
    # 近同文簇至多留 1；短通稿可被分地板整簇裁掉
    assert len(wire_in) <= 1, cores
    assert "both#p1" in cores
    assert packed[0] == "both#p1" or "both#p1" in cores[:2]


def test_density_box_not_all_wire():
    metas, feats, anchors, pool_pos = _feats_meta_wire_cluster()
    order = ["w1#p1", "w2#p1", "w3#p1", "both#p1"]
    out = density_constrained_submit(
        order, feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
        gold_ids={"both#p1"},
    )
    box = out["submission"]
    assert "both#p1" in box
    assert sum(1 for p in box if p.startswith("w")) <= 1
    assert out["gold_density"] + 1e-12 >= 1 / 3


def test_both_side_outranks_short_wire_on_adjudicate():
    metas, feats, anchors, pool_pos = _feats_meta_wire_cluster()
    sc_w = core_rank_score(
        "w1#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
    )
    sc_b = core_rank_score(
        "both#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, anchors=anchors, url_of={},
    )
    assert sc_b > sc_w
