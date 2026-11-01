"""R14 切片维：编制身份同义词、履历噪声。不看金标。"""

from __future__ import annotations

from app.kg_lab.slice_dims import identity_synonym, resume_noise

_P6 = (
    "刘翔的职位是上海体育局团委副书记，不过上海体育局也曾解释，刘翔并不是公务员，"
    "也没有行政级别的说法，他会参与一些工作，但是不会坐班。\n"
    "现年43岁的刘翔在2004年奥运会缔造历史后，2008年在北京奥运会上伤退，"
    "2012年伦敦奥运会，在预赛中跨越第一个栏时就被绊倒，最后单脚跳到终点。"
)
_Q3 = "刘翔退役至今是否真有编制与岗位，官方称其在编不在岗能否以人事档案证实？"
_Q1 = "这笔49.4万元应认定为买断费还是自主择业经济补偿金？"


def test_identity_synonym_needs_the_post_question():
    assert identity_synonym(_Q3, _P6) == 1.0
    assert identity_synonym(_Q1, _P6) == 0.0


def test_resume_noise_is_the_olympic_tail_not_the_job_line():
    job = "刘翔的职位是上海体育局团委副书记，不过他不是公务员，也不会坐班。"
    assert resume_noise(_P6) == 1.0
    assert resume_noise(job) == 0.0
