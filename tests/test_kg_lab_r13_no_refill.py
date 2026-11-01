"""R13：二筛踢掉的位子不从池后补。"""

from __future__ import annotations

from app.kg_lab.inbox_rerank import inbox_rerank

_Q = "拖了11年才安置，是刘翔不愿走还是体育局未放行，哪一方说法站得住？"
_QUOTE = "但刘翔继续于深夜发文：“不是我不想走，而是你没让我走”。"
_MONEY = "刘翔最终选择自主择业，并按规定给予了自主择业经济补偿金。"


def _feat(role: str, **extra):
    feat = {f"role_{role}": 1.0, "tier_market_media": 1.0}
    feat.update(extra)
    return feat


def test_submission_keeps_rank_from_before_the_cut():
    ranked = [("a#p", 0.30), ("b#p", 0.20), ("c#p", 0.10)]
    texts = {pid: f"正文{pid}，没有主张词。" for pid in ("a#p", "b#p", "c#p")}
    metas = {pid: {"fine_role": "media_relay", "text": texts[pid], "title": ""} for pid in texts}
    feats = {pid: {"role_media_relay": 1.0, "tier_market_media": 1.0} for pid in texts}
    out = inbox_rerank(ranked, texts=texts, feats=feats, metas=metas, pool=3, k=2)
    assert [row["rank"] for row in out["order"]] == [1, 2, 3]
    assert out["submission"] == [
        {"id": "a#p", "rank": 1, "score": out["order"][0]["score"]},
        {"id": "b#p", "rank": 2, "score": out["order"][1]["score"]},
    ]
    assert "penalty" not in out["submission"][0]


def test_kicked_seat_is_not_filled_from_further_down():
    ranked = [("bad#p", 0.30), ("keep#p", 0.20), ("later#p", 0.29)]
    later = "9月1日，刘翔递交了自愿选择自主择业申请表，并按规定给予了自主择业经济补偿金。"
    texts = {"bad#p": _MONEY, "keep#p": _QUOTE, "later#p": later}
    metas = {pid: {"fine_role": "official_reprint", "text": texts[pid], "title": pid} for pid in texts}
    metas["keep#p"]["fine_role"] = "party_relay"
    metas["later#p"]["fine_role"] = "official_primary"
    feats = {
        "bad#p": _feat("official_reprint"),
        "keep#p": _feat("party_relay", r9_relay="relay_party_primary"),
        "later#p": _feat("official_primary"),
    }
    out = inbox_rerank(
        ranked, texts=texts, feats=feats, metas=metas,
        pool=3, k=2, question=_Q, refill=False,
    )
    assert out["top_ids"] == ["keep#p"]
    assert out["submission"][0]["id"] == "keep#p"
    assert out["submission"][0]["rank"] == 2
    assert "later#p" not in out["top_ids"]
