"""R11：标题／原标题里的主张词，正文剥掉回声后几乎为空，要减分。不读金标。"""

from __future__ import annotations

from app.kg_lab.inbox_rerank import inbox_rerank, is_title_bait

_Q = "拖了11年才安置，是刘翔不愿走还是体育局未放行，哪一方说法站得住？"
_041_TITLE = "刘翔深夜再发文：继续搞笑吧，我一直没有离开，并不是我不想走，而是你没让我走，10年了，突然现在要安置我"
_041_BODY = (
    "本人忏悔：愿卖房赔钱\n"
    "原标题：《刘翔深夜再发文：继续搞笑吧，我一直没有离开，并不是我不想走，而是你没让我走》\n"
    "阅读原文"
)
_009_TITLE = "刘翔与上海市体育局纠纷 公众有权知道发生了什么"
_009_BODY = "但刘翔对这个回应并不买账，继续于深夜发文：“不是我不想走，而是你没让我走”“十年物是人非”。"


def test_shell_whose_claim_is_only_in_title_is_bait():
    assert is_title_bait(_041_TITLE, _041_BODY, _Q)
    assert not is_title_bait(_009_TITLE, _009_BODY, _Q)


def test_quote_in_body_is_not_bait_even_if_title_repeats_it():
    title = "不是我不想走，而是你没让我走"
    body = "刘翔深夜发文：不是我不想走，而是你没让我走。十年物是人非，当断不断必有后患。"
    assert not is_title_bait(title, body, _Q)


def test_shell_loses_the_slot_to_the_real_quote():
    ranked = [("doc_041#p6", 0.21), ("doc_009#p5", 0.20)]
    texts = {"doc_041#p6": _041_BODY, "doc_009#p5": _009_BODY}
    metas = {
        "doc_041#p6": {"title": _041_TITLE, "text": _041_BODY, "fine_role": "party_relay"},
        "doc_009#p5": {"title": _009_TITLE, "text": _009_BODY, "fine_role": "party_relay"},
    }
    feats = {
        "doc_041#p6": {"role_party_relay": 1.0, "tier_market_media": 1.0},
        "doc_009#p5": {"role_party_relay": 1.0, "tier_market_media": 1.0},
    }
    out = inbox_rerank(ranked, texts=texts, feats=feats, metas=metas, pool=2, k=1, question=_Q)
    assert out["top_ids"] == ["doc_009#p5"]
    assert "doc_041#p6" in out["title_bait"]
    assert "doc_009#p5" not in out["title_bait"]
