"""R12：对题主张抬权，偏题转载、小节标题和伪制度说明降权。不读金标。"""

from __future__ import annotations

from app.kg_lab.inbox_rerank import (
    inbox_rerank,
    is_fake_gloss,
    is_offtopic_money,
    is_section_bait,
)

_Q = "拖了11年才安置，是刘翔不愿走还是体育局未放行，哪一方说法站得住？"
_009 = "但刘翔对这个回应并不买账，继续于深夜发文：“不是我不想走，而是你没让我走”“十年物是人非”。"
_029P4 = (
    "上海市体育局发布声明表示：提供组织安置或自主择业两种方案，将依法依规做好保障。\n"
    "相关内容>>>\n"
    "8月27日 刘翔回应体育局：继续搞笑吧，不是我不想走而是你没让我走"
)
_029P5 = "当晚，刘翔在社媒上写道：并不是我不想走，而是你没让我走，10年了，突然现在要安置我。"
_LONG = (
    "刘翔上热搜了。8月26日他在微博发问买断或当教练。"
    "当晚体育局说依规安置。然而刘翔随即深夜再发文：继续搞笑吧，我一直没有离开，"
    "并不是我不想走，而是你没让我走，10年了。评论认为该把争议摆上台面，而不是只转一句。"
    "后面还有一大段在讨论纳税人、空饷和公众知情，不是同一段引语。"
)


def _feat(role: str, **extra):
    feat = {f"role_{role}": 1.0, "tier_market_media": 1.0}
    feat.update(extra)
    return feat


def test_section_heading_does_not_count_as_the_claim():
    assert is_section_bait(_029P4, _Q)
    assert not is_section_bait(_009, _Q)


def test_money_reprint_drops_but_official_primary_stays():
    reprint = "9月1日，刘翔最终选择自主择业，9月7日给予了自主择业经济补偿金。"
    assert is_offtopic_money(reprint, _feat("official_reprint"), {"fine_role": "official_reprint", "text": reprint}, _Q)
    primary = "9月1日，刘翔递交了自愿选择自主择业申请表，并按规定给予了自主择业经济补偿金。"
    meta = {"fine_role": "official_primary", "text": primary}
    assert not is_offtopic_money(primary, _feat("official_primary"), meta, _Q)


def test_fake_gloss_is_commentary_without_an_official_voice():
    fake = {"r9_comment": "institutional_gloss"}
    fake_meta = {"fine_role": "commentary", "text": "十一年里商业代言按规则分成，人事安置却一拖再拖。姚明则不把坐班当退路。"}
    real_meta = {"fine_role": "commentary", "text": "该中心一工作人员表示，刘翔目前还在该单位，后续统一发公告。"}
    assert is_fake_gloss(fake, fake_meta)
    assert not is_fake_gloss(fake, real_meta)


def test_heading_and_money_reprint_lose_to_the_real_quote():
    ranked = [("pad#p", 0.26), ("reprint#p", 0.25), ("quote#p", 0.20)]
    texts = {"pad#p": _029P4, "reprint#p": "刘翔最终选择自主择业，我们予以充分尊重。", "quote#p": _009}
    metas = {
        "pad#p": {"fine_role": "party_relay", "text": _029P4, "title": "时间线"},
        "reprint#p": {"fine_role": "official_reprint", "text": texts["reprint#p"], "title": "新华网"},
        "quote#p": {"fine_role": "party_relay", "text": _009, "title": "纠纷"},
    }
    feats = {
        "pad#p": _feat("party_relay", r9_relay="relay_party_primary"),
        "reprint#p": _feat("official_reprint"),
        "quote#p": _feat("party_relay", r9_relay="relay_party_primary"),
    }
    out = inbox_rerank(ranked, texts=texts, feats=feats, metas=metas, pool=3, k=1, question=_Q)
    assert out["top_ids"] == ["quote#p"]


def test_near_quote_keeps_relay_not_the_longer_article():
    ranked = [("opp#p", 0.24), ("relay#p", 0.20), ("long#p", 0.23)]
    texts = {"opp#p": _029P5, "relay#p": _009, "long#p": _LONG}
    metas = {
        "opp#p": {"fine_role": "opposition_framing", "text": _029P5, "title": "时间线"},
        "relay#p": {"fine_role": "party_relay", "text": _009, "title": "纠纷"},
        "long#p": {"fine_role": "opposition_framing", "text": _LONG, "title": "热评"},
    }
    feats = {
        "opp#p": _feat("opposition_framing"),
        "relay#p": _feat("party_relay", r9_relay="relay_party_primary"),
        "long#p": _feat("opposition_framing"),
    }
    out = inbox_rerank(ranked, texts=texts, feats=feats, metas=metas, pool=3, k=2, question=_Q)
    assert "relay#p" in out["top_ids"]
    assert "opp#p" in out["near_dup_dropped"]
    assert "long#p" not in out["near_dup_dropped"]
    assert out["rep_of"].get("opp#p") == "relay#p"
