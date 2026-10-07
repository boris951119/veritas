"""二阶资料卫生闸（零 LLM）：无基数百分比、货币口径、未核验出处。

不替代引文闸：只亮黄牌，不删结论。
"""

from __future__ import annotations

import re

from app.core.evidence import Dossier, SourceType
from app.core.numeric_check import extract_nums

_GROWTH = re.compile(
    r"(增长|下降|上涨|下跌|同比|环比|升幅|降幅|提升|升至|降至|高达|达到|达"
    r"|骤增|暴增|暴跌|回落)[了]?\s*(\d+(?:\.\d+)?)\s*[%％]"
)
_CNY = re.compile(r"人民币|RMB|￥|元")
_USD = re.compile(r"美元|美金|USD|\$")


def audit_bare_percent(dossier: Dossier) -> list[dict]:
    """结论写「增长 50%」但所引证据里没有可作基数的第二个数字。"""
    flags: list[dict] = []
    for con in dossier.conclusions:
        if con.status in ("merged",):
            continue
        if not _GROWTH.search(con.statement or ""):
            continue
        corpus = " ".join(
            e.quote for e in dossier.evidences_of(con.id)
        )
        for ev in dossier.evidences_of(con.id):
            for sid in ev.segment_ids:
                seg = dossier.segment(sid)
                if seg:
                    corpus += " " + seg.text
        nums = [n for n in extract_nums(corpus) if n.unit != "%"]
        if len(nums) < 1:
            flags.append({
                "kind": "percent_no_base", "severity": "medium",
                "conclusion_id": con.id, "value": con.statement[:40],
                "detail": f"{con.id} 给出涨跌百分比，所引证据未见基数",
            })
    return flags


def audit_unit_mismatch(dossier: Dossier) -> list[dict]:
    """同一案卷里同时出现人民币口径与美元口径（单位把戏黄牌）。"""
    blob_by_src: list[tuple[str, str]] = []
    for src in dossier.sources:
        blob_by_src.append((src.id, " ".join(s.text for s in src.segments)))
    has_cny = [i for i, t in blob_by_src if _CNY.search(t)]
    has_usd = [i for i, t in blob_by_src if _USD.search(t)]
    if has_cny and has_usd:
        return [{
            "kind": "unit_mismatch", "severity": "medium",
            "value": f"{len(has_cny)}cny/{len(has_usd)}usd",
            "detail": "资料同时出现人民币与美元口径，数字不可直接加总或对撞",
        }]
    return []


def audit_unverified_sources(dossier: Dossier) -> list[dict]:
    """新闻/网页类信源未给 URL：出处无法联网核验，披露为未核验。"""
    flags: list[dict] = []
    for src in dossier.sources:
        if src.source_type not in (SourceType.WEB, SourceType.NEWS):
            continue
        if (src.url or "").strip():
            continue
        flags.append({
            "kind": "source_unverified", "severity": "medium",
            "value": src.id,
            "detail": f"信源 {src.id}（{src.source_type.value}）未声明 URL，"
                      "无法联网核验出处——按未核验披露，不当作官方来源",
        })
    return flags
