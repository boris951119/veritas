"""R10 盒内重排不读金标：拼段让位给官方原文，同文留更高渠道。"""

from __future__ import annotations

from app.kg_lab.inbox_rerank import inbox_rerank

_002 = "9月1日，刘翔递交了自愿选择自主择业申请表，并签署了有关协议；9月7日，人事关系手续基本办理完结，并按规定给予了自主择业经济补偿金。"
_012 = (
    "前期，经与刘翔本人深入沟通，提供了包括田径中心负责人、技术总监、体育类高校等组织安置方向，"
    "刘翔最终选择自主择业，我们予以充分尊重。" + _002
)
_024 = (
    "情况通报 刘翔同志是我国优秀田径运动员，为体育事业作出了突出贡献。"
    "前期，经与刘翔本人深入沟通，提供了包括田径中心负责人、技术总监、体育类高校等组织安置方向，"
    "刘翔最终选择自主择业，我们予以充分尊重。9月1日，刘翔递交了自愿选择自主择业申请表，并签署了有关协议；"
)


def _feat(role: str, tier: str, **extra):
    feat = {f"role_{role}": 1.0, f"tier_{tier}": 1.0}
    feat.update(extra)
    return feat


def test_concat_bulletin_is_dropped_for_official_original():
    ranked = [
        ("doc_012#p2", 0.20),
        ("doc_024#p1", 0.19),
        ("doc_002#p3", 0.18),
        ("doc_030#p5", 0.17),
    ]
    texts = {"doc_012#p2": _012, "doc_024#p1": _024, "doc_002#p3": _002, "doc_030#p5": "时间线综述，不是通报原文。"}
    feats = {
        "doc_012#p2": _feat("official_reprint", "market_media"),
        "doc_024#p1": _feat("official_reprint", "central_official"),
        "doc_002#p3": _feat("official_primary", "central_official"),
        "doc_030#p5": _feat("mixed_summary", "market_media", r9_comment="mixed_roundup"),
    }
    metas = {pid: {"fine_role": pid and ""} for pid in texts}
    metas["doc_002#p3"]["fine_role"] = "official_primary"
    metas["doc_012#p2"]["fine_role"] = "official_reprint"
    metas["doc_024#p1"]["fine_role"] = "official_reprint"
    metas["doc_030#p5"]["fine_role"] = "mixed_summary"
    out = inbox_rerank(ranked, texts=texts, feats=feats, metas=metas, pool=4, k=3)
    assert "doc_012#p2" in out["swallowed"]
    assert "doc_012#p2" not in out["top_ids"]
    assert out["top_ids"][0] == "doc_024#p1" or "doc_002#p3" in out["top_ids"]
    assert "doc_002#p3" in out["top_ids"]


def test_verbatim_keeps_higher_tier_not_a_labeled_id():
    same = "9月7日，人事关系手续基本办理完结，并按规定给予了自主择业经济补偿金。对于捐赠善举，我们深表敬意！"
    ranked = [("low#p", 0.3), ("high#p", 0.2)]
    texts = {"low#p": same, "high#p": same}
    feats = {
        "low#p": _feat("official_reprint", "market_media"),
        "high#p": _feat("official_reprint", "central_official"),
    }
    metas = {
        "low#p": {"fine_role": "official_reprint"},
        "high#p": {"fine_role": "official_reprint"},
    }
    out = inbox_rerank(ranked, texts=texts, feats=feats, metas=metas, pool=2, k=1)
    assert out["top_ids"] == ["high#p"]
    assert "low#p" in out["near_dup_dropped"]


def test_penalized_higher_tier_does_not_eject_clean_relay():
    text = "8月26日下午，上海市竞技体育训练管理中心与刘翔进行了沟通，拟依据相关规定，主要通过组织安置或自主择业对其予以妥善安置。"
    ranked = [("central#p", 0.25), ("market#p", 0.18)]
    texts = {"central#p": text, "market#p": text}
    feats = {
        "central#p": _feat("mixed_summary", "central_official"),
        "market#p": _feat("media_relay", "market_media"),
    }
    metas = {
        "central#p": {"fine_role": "mixed_summary"},
        "market#p": {"fine_role": "media_relay"},
    }
    out = inbox_rerank(ranked, texts=texts, feats=feats, metas=metas, pool=2, k=1)
    assert out["top_ids"] == ["market#p"]
    assert "central#p" in out["near_dup_dropped"]


def test_single_excerpt_keeps_longer_bulletin():
    short = "8月26日下午，上海市竞技体育训练管理中心与刘翔进行了沟通，拟依据相关规定，主要通过组织安置或自主择业对其予以妥善安置。"
    long = "针对刘翔在个人微博发文情况，上海市体育局回应称，刘翔是上海的优秀运动员，为上海体育作出了突出贡献。" + short
    other = "编制与岗位要看人事档案，官方称在编不在岗，这段不引用八月二十六日的沟通。"
    ranked = [("long#p", 0.22), ("short#p", 0.10), ("other#p", 0.21)]
    texts = {"long#p": long, "short#p": short, "other#p": other}
    feats = {
        "long#p": _feat("media_relay", "market_media"),
        "short#p": _feat("media_relay", "market_media"),
        "other#p": _feat("commentary", "market_media"),
    }
    metas = {pid: {"fine_role": "media_relay"} for pid in texts}
    metas["other#p"]["fine_role"] = "commentary"
    out = inbox_rerank(ranked, texts=texts, feats=feats, metas=metas, pool=3, k=2)
    assert "long#p" not in out["swallowed"]
    assert "long#p" in out["top_ids"]
    assert "short#p" in out["near_dup_dropped"]


def test_gloss_is_not_penalized_as_commentary():
    ranked = [("gloss#p", 0.20), ("plain#p", 0.16)]
    texts = {"gloss#p": "团委副书记，还在单位，不是公务员，不会坐班。", "plain#p": "另一段市场稿，没有降权。"}
    feats = {
        "gloss#p": _feat("commentary", "market_media", r9_comment="institutional_gloss"),
        "plain#p": _feat("media_relay", "market_media"),
    }
    metas = {
        "gloss#p": {"fine_role": "commentary"},
        "plain#p": {"fine_role": "media_relay"},
    }
    out = inbox_rerank(ranked, texts=texts, feats=feats, metas=metas, pool=2, k=1)
    assert out["top_ids"] == ["gloss#p"]
    assert out["penalties"] == {}
