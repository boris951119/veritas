"""R5 细角色：原文/转载、本人渠道/转述、混口径。不读金标文件。"""

from __future__ import annotations

from app.kg_lab.source_role import R4_FINE_EQUIV, infer_fine_role, rerank_source_role


def test_bureau_page_versus_reprint():
    body = (
        "9月1日，刘翔递交了自愿选择自主择业申请表，并签署了有关协议；"
        "9月7日，人事关系手续基本办理完结，并按规定给予了自主择业经济补偿金。"
    )
    primary = infer_fine_role("上海市体育局回应刘翔退役安置“买断”问题", body, 0.9)
    xinhua = infer_fine_role("上海体育局回应刘翔买断-新华网", body, 0.9)
    shangguan = infer_fine_role("情况通报_上观新闻", body, 0.6)
    headline = infer_fine_role("上海体育局发布对刘翔安置通报，刘翔：再无关联", body, 0.85)
    assert primary["role"] == "official_primary"
    assert primary["channel"] == "bureau"
    assert xinhua["role"] == "official_reprint"
    assert shangguan["role"] == "official_reprint"
    assert headline["role"] == "official_reprint"
    # 转载在等价表里先与原文同乘子，扫参再把它压低
    assert R4_FINE_EQUIV["official_reprint"] == R4_FINE_EQUIV["official_primary"]


def test_weibo_self_beats_low_platform_score():
    text = "全文如下：这么多天过去，还是由我来说吧。第一，早在9月1日我已经买断，获得49.4万元买断费。"
    low = infer_fine_role("刘翔再发文", text, 0.35)
    wire = infer_fine_role(
        "刘翔称已于9月1日“买断”-新华网",
        "刘翔称已于9月1日“买断” 新华社上海9月10日电（记者胡洁菲）"
        "刘翔在个人微博上发文称，自己已于9月1日买断，获得49.4万元买断费。",
        0.9,
    )
    assert low["role"] == "party_primary"
    assert low["credibility"] == 0.35
    assert wire["role"] == "opposition_framing"
    assert R4_FINE_EQUIV["party_primary"] >= R4_FINE_EQUIV["party_relay"]


def test_mixed_timeline_not_plain_commentary():
    text = (
        "8月26日他发求助，说组织给两条路，自主买断；"
        "9月1日他交申请表，9月7日手续办完，自主择业经济补偿49.4万。"
    )
    info = infer_fine_role("尘埃落定！看懂刘翔安置事件大结局_网易", text, 0.7)
    assert info["role"] == "mixed_summary"
    assert info["coarse"] == "commentary"


def test_equiv_weights_match_r4_order():
    rows = [
        {
            "para_id": "doc_002#p3",
            "doc_id": "doc_002",
            "title": "上海市体育局回应刘翔退役安置“买断”问题",
            "text": "9月1日，刘翔递交了自愿选择自主择业申请表；9月7日，按规定给予了自主择业经济补偿金。",
            "source_credibility": 0.9,
        },
        {
            "para_id": "doc_012#p2",
            "doc_id": "doc_012",
            "title": "上海体育局发布对刘翔安置通报，刘翔：再无关联",
            "text": "我们予以充分尊重。9月1日，刘翔递交了自愿选择自主择业申请表；按规定给予了自主择业经济补偿金。",
            "source_credibility": 0.85,
        },
        {
            "para_id": "doc_030#p5",
            "doc_id": "doc_030",
            "title": "尘埃落定！看懂刘翔安置事件大结局",
            "text": "8月26日他发求助，说自主买断。9月7日手续办完，自主择业经济补偿49.4万。",
            "source_credibility": 0.7,
        },
    ]
    fused = [("doc_012#p2", 0.08), ("doc_030#p5", 0.079), ("doc_002#p3", 0.07)]
    base = [p for p, _ in rerank_source_role(rows, fused, dedupe=False)["ranked"]]
    equiv = [p for p, _ in rerank_source_role(rows, fused, dedupe=False, weights=R4_FINE_EQUIV)["ranked"]]
    assert base == equiv
    pressed = rerank_source_role(
        rows, fused, dedupe=False,
        weights={**R4_FINE_EQUIV, "official_reprint": 0.94, "mixed_summary": 0.76},
    )
    order = [p for p, _ in pressed["ranked"]]
    assert order[0] == "doc_002#p3"
    assert order.index("doc_030#p5") > order.index("doc_002#p3")
    assert order.index("doc_012#p2") > 0
