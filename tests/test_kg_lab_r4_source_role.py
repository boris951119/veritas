"""R4 通稿去重 + 角色 prior + 摘要槽位（离线，不读金标文件）。"""

from __future__ import annotations

from app.kg_lab.source_role import (
    ROLE_WEIGHT,
    infer_source_role,
    rerank_source_role,
)
from app.kg_lab.summary_slots import apply_slots_to_summary, extract_slots, merge_facts


def _row(pid: str, title: str, text: str, cred: float) -> dict:
    doc = pid.split("#")[0]
    return {
        "para_id": pid,
        "doc_id": doc,
        "title": title,
        "text": text,
        "source_credibility": cred,
    }


OPENING = (
    "上海体育局回应刘翔买断 情况通报 "
    "刘翔同志是我国优秀田径运动员，为体育事业作出了突出贡献。"
    "我们予以充分尊重。"
    "9月1日，刘翔递交了自愿选择自主择业申请表，并签署了有关协议；"
)
OPERATIVE = (
    "9月1日，刘翔递交了自愿选择自主择业申请表，并签署了有关协议；"
    "9月7日，人事关系手续基本办理完结，并按规定给予了自主择业经济补偿金。"
)
CONTINUATION = (
    "9月7日，人事关系手续基本办理完结，并按规定给予了自主择业经济补偿金。"
    "对于刘翔同志将2015年4月以来全部工资收入捐赠用于西藏吉隆泥石流救灾的善举，我们深表敬意！"
)
RELAY = (
    "上海体育局今天正式回应了。确认刘翔已自主选择择业安置。"
    "上海市体育局表示，此前曾提供组织安置方向，对此予以充分尊重。"
    "9月1日，刘翔递交了自愿选择自主择业申请表，并签署了有关协议。"
)
TIMELINE = (
    "2026年8月26日他发求助，说组织给两条路，回岗当教练或者自主买断。"
    "9月1日他交自愿自主择业申请表，9月7日人事手续基本办完，自主择业经济补偿49.4万。"
)
STATUTE = (
    "在运动员退役安置的制度框架中，“买断”对应的表述是“自主择业”——"
    "依据2003年发布的《自主择业退役运动员经济补偿办法》，符合条件的运动员自愿放弃组织安置。"
)
PARTY = "刘翔深夜再发文：“并不是我不想走，而是你没让我走，10年了。”"


def test_role_rules_ignore_credibility_float():
    official = infer_source_role("上海市体育局回应刘翔退役安置“买断”问题", OPERATIVE, 0.9)
    low = infer_source_role("情况通报_上观新闻", CONTINUATION, 0.6)
    statute = infer_source_role("小新说丨迟到了11年的安置", STATUTE, 0.6)
    relay = infer_source_role("看看新闻网", RELAY, 0.95)
    timeline = infer_source_role("尘埃落定！看懂刘翔安置事件大结局", TIMELINE, 0.9)
    party = infer_source_role("每经热评｜关于刘翔的争议", PARTY, 0.7)
    assert official["role"] == "official_primary"
    assert low["role"] == "official_primary"
    assert statute["role"] == "institution_def"
    assert relay["role"] == "media_relay"
    assert timeline["role"] == "commentary"
    assert party["role"] == "party_claim"
    assert ROLE_WEIGHT["institution_def"] > ROLE_WEIGHT["media_relay"]
    assert ROLE_WEIGHT["official_primary"] > ROLE_WEIGHT["commentary"]
    # 高 cred 转述不得因此升到制度段之上
    assert statute["weight"] > relay["weight"]


def test_dedupe_keeps_official_slices_and_swaps_relay():
    rows = [
        _row("doc_002#p3", "上海市体育局回应刘翔退役安置“买断”问题", OPERATIVE, 0.9),
        _row("doc_024#p1", "上海体育局回应刘翔买断-新华网", OPENING, 0.9),
        _row("doc_035#p7", "情况通报_上观新闻", CONTINUATION, 0.6),
        _row("doc_024#p2", "上海体育局回应刘翔买断-新华网", CONTINUATION, 0.9),
        _row(
            "doc_048#p2",
            "上海市体育局发布情况通报：将持续优化退役运动员安置政策_人民日报",
            CONTINUATION,
            0.9,
        ),
        _row("doc_038#p1", "看看新闻网", RELAY, 0.6),
        _row("doc_030#p5", "尘埃落定！看懂刘翔安置事件大结局", TIMELINE, 0.7),
        _row("doc_025#p6", "小新说丨迟到了11年的安置", STATUTE, 0.6),
    ]
    fused = [
        ("doc_030#p5", 0.081),
        ("doc_038#p1", 0.076),
        ("doc_002#p3", 0.070),
        ("doc_025#p6", 0.069),
        ("doc_024#p2", 0.067),
        ("doc_035#p7", 0.060),
        ("doc_024#p1", 0.040),
    ]
    rr = rerank_source_role(rows, fused, dedupe=True, role_prior=True)
    ids = [pid for pid, _ in rr["ranked"]]
    # 转述名次让给带「情况通报」正文的官方开头，而不是高 cred 的另一切片
    assert "doc_038#p1" not in ids
    assert "doc_024#p1" in ids
    # 两条官方切片都在（申请+补偿 与 补偿+捐赠 不是同一段）
    assert "doc_002#p3" in ids
    assert "doc_035#p7" in ids
    # 同一续段：低 cred《情况通报》压过高 cred 新华网／人民日报改写题
    assert "doc_024#p2" not in ids
    assert "doc_048#p2" not in ids
    # 时间线综述没有近义句可并，仍在名单里，但乘了评论权重后不应压过官方切片
    assert ids.index("doc_002#p3") < ids.index("doc_030#p5")
    assert ids.index("doc_025#p6") < ids.index("doc_030#p5")


def test_role_prior_does_not_sort_by_credibility():
    rows = [
        _row("doc_025#p6", "小新说", STATUTE, 0.6),
        _row("doc_043#p2", "联合早报", RELAY, 0.95),
    ]
    # 转述原始分更高、可信度也更高
    fused = [("doc_043#p2", 0.080), ("doc_025#p6", 0.078)]
    rr = rerank_source_role(rows, fused, dedupe=False, role_prior=True)
    ids = [pid for pid, _ in rr["ranked"]]
    assert ids[0] == "doc_025#p6"


def test_slots_only_when_text_has_evidence():
    official = extract_slots("上海市体育局回应", OPERATIVE)
    assert official["source_role"] == "官方"
    assert "买断" not in official["opposition_terms"]
    assert "经济补偿金" in official["opposition_terms"]
    assert official["amount_status"] == "established"
    assert "49.4" not in official["amount_note"]
    assert any("申请" in d for d in official["procedure_dates"])

    unconfirmed = extract_slots(
        "快快评",
        "刘翔的49.4万买断费的具体核算依据、明细标准尚未公开。",
    )
    assert unconfirmed["amount_status"] == "officially_unconfirmed"
    assert "买断费" in unconfirmed["opposition_terms"] or "买断" in unconfirmed["opposition_terms"]

    bare = extract_slots("体育新闻", "当日赛程正常进行，观众入场。")
    assert bare["opposition_terms"] == []
    assert bare["amount_status"] == "none"
    assert bare["procedure_dates"] == []


def test_unconfirmed_requires_amount_language_not_quiet_procedure():
    quiet = extract_slots(
        "时间线",
        "在未公开的情况下完成割离。9月1日办理自主择业手续，获得49.4万元买断费。",
    )
    assert quiet["amount_status"] == "disclosed"
    hidden = extract_slots(
        "快快评",
        "刘翔的49.4万买断费的具体核算依据、明细标准尚未公开。",
    )
    assert hidden["amount_status"] == "officially_unconfirmed"


def test_failed_llm_keeps_existing_facts():
    text = "制度框架里买断对应自主择业。"
    old = [
        "运动员退役安置制度中买断对应自主择业。",
        "依据2003年办法可自愿放弃安置。",
        "制度设计前提是充分知情。",
    ]
    assert merge_facts([], old, text) == old[:3]


def test_merge_facts_caps_and_keeps_grounded_opposition():
    text = "刘翔深夜发文：不是我不想走，而是你没让我走。十年物是人非。"
    old = [
        "不是我不想走，而是你没让我走",
        "十年物是人非",
        "多余背景一句不在原文里的奥运金牌",
    ]
    llm = ["模型编造了他获得一百万元", "不是我不想走，而是你没让我走"]
    facts = merge_facts(llm, old, text)
    assert len(facts) <= 3
    assert any("没让我走" in f for f in facts)
    assert all("一百万元" not in f for f in facts)
    enriched = apply_slots_to_summary(
        {"facts": old, "entities": ["刘翔"], "keywords": []},
        title="每经热评",
        text=text,
        llm_facts=llm,
    )
    assert len(enriched["facts"]) <= 3
    assert "角色:当事人" in enriched["summary_text"] or "口径:" in enriched["summary_text"]
