"""R9 细桶：三条漏标应和混口径综述分开。"""

from __future__ import annotations

from app.kg_lab.r9_buckets import claim_bits, comment_bucket, relay_bucket, subject_x_channel

_009 = "但刘翔对这个回应并不买账，继续于深夜发文：“不是我不想走，而是你没让我走”。"
_029 = "9月2日：刘翔把工资全数捐赠。9月3日 竞体中心：刘翔目前还在单位，后续统一发公告。"
_033 = "刘翔的职位是上海体育局团委副书记，并不是公务员，也不会坐班。"
_030 = "8月26日他发求助，说自主买断。9月1日交申请，9月7日手续办完，经济补偿49.4万。"
_051 = "上海市体育局回应称，拟主要通过组织安置或自主择业对其予以妥善安置。"


def test_three_misses_leave_the_coarse_commentary_bin():
    assert relay_bucket("", _009, "party_relay") == "relay_party_primary"
    assert comment_bucket("时间线回顾", _029, "commentary") == "institutional_gloss"
    assert comment_bucket("", _033, "commentary") == "institutional_gloss"
    assert comment_bucket("尘埃落定！大结局", _030, "commentary") == "mixed_roundup"
    assert relay_bucket("", _051, "media_relay") == "relay_official_bulletin"


def test_claim_full_and_keyword_are_exclusive():
    q2 = "是刘翔不愿走还是体育局未放行？"
    assert claim_bits(q2, _009) == (1.0, 0.0)
    assert claim_bits(q2, _029) == (0.0, 1.0)
    q3 = "刘翔退役至今是否真有编制与岗位？"
    assert claim_bits(q3, _033) == (0.0, 1.0)
    assert claim_bits(q3, "没有接到过任何编制及岗位。") == (1.0, 0.0)


def test_subject_times_weibo_channel():
    q = "是刘翔不愿走还是体育局未放行？"
    assert subject_x_channel(q, "", _009, "party_relay", "relay_party_primary") == 1.0
    assert subject_x_channel(q, "", _029, "commentary", "") == 0.0
    assert subject_x_channel(q, "", "我们予以充分尊重。", "official_primary", "") == 1.0
