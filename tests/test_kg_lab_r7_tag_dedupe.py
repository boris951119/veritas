"""R7：口径框架不稀释原词；去重可保住指定 id。"""

from __future__ import annotations

from app.kg_lab.multidim_weight import claim_align
from app.kg_lab.source_role import _norm, cluster_representatives

_A = (
    "针对刘翔在个人微博发文情况，上海市体育局回应称，刘翔是上海的优秀运动员。"
    "8月26日下午，上海市竞技体育训练管理中心与刘翔进行了沟通，"
    "拟依据相关规定，主要通过组织安置或自主择业对其予以妥善安置。"
)
_B = (
    "对此，上海体育局向澎湃新闻回应称：刘翔是上海的优秀运动员。"
    "8月26日下午，上海市竞技体育训练管理中心与刘翔进行了沟通，"
    "拟依据相关规定，主要通过组织安置或自主择业对其予以妥善安置。"
)


def _meta(pid: str, text: str, cred: float) -> dict:
    return {
        "para_id": pid,
        "title": pid,
        "text": text,
        "norm": _norm(text),
        "role": "media_relay",
        "credibility": cred,
    }


def test_frames_extend_group_without_diluting_original_term():
    q = "是刘翔不愿走还是体育局未放行？"
    quote = "不是我不想走，而是你没让我走。"
    bulletin = "9月1日，刘翔递交了自愿选择自主择业申请表。"
    assert claim_align(q, quote, frames=False) == 1.0
    assert claim_align(q, quote, frames=True) == 1.0
    assert claim_align(q, bulletin, frames=False) == 0.0
    assert claim_align(q, bulletin, frames=True) == 1.0
    assert claim_align("是否真有编制与岗位？", "他并不是公务员，也不会坐班。", frames=True) == 1.0


def test_prefer_ids_keeps_lower_cred_duplicate():
    metas = {
        "doc_005#p3": _meta("doc_005#p3", _B, 0.85),
        "doc_051#p3": _meta("doc_051#p3", _A, 0.70),
    }
    # 默认可信度更高的 doc_005 当代表
    plain = cluster_representatives(metas)
    assert plain["doc_051#p3"] == "doc_005#p3"
    # 指定保留严格 id 时，分数不动，只换发出去的 id
    kept = cluster_representatives(
        metas, prefer_ids={"doc_051#p3"}, scores={"doc_005#p3": 0.05, "doc_051#p3": 0.04},
    )
    assert kept["doc_005#p3"] == "doc_051#p3"
    assert kept["doc_051#p3"] == "doc_051#p3"
