"""R19：可迁移元数据标签（权威／时效／适用范围／框架对齐）。

不写案情专名；与 R17 schema 并列，供一筛加分与披露。
"""

from __future__ import annotations

import re
from typing import Any

from app.kg_lab.channel_tier import channel_tier
from app.kg_lab.event_frame import EventFrame, frame_align_score, option_side

_DATE = re.compile(r"\d{1,2}月\d{1,2}日|\d{4}\s*年|\d{1,2}\s*时\d{1,2}\s*分")
_AMOUNT = re.compile(r"\d+(?:\.\d+)?\s*万|\d{2,}\s*元|\$[\d,]+")
_PRIMARY_CUE = (
    "通报", "新闻发布会", "我们予以", "按规定", "调查报告", "正式回应",
    "全文如下", "记者从", "发布会", "官方视频", "一手",
)
_WIRE_CUE = ("新华社", "据报道", "援引", "央视", "电（", "记者")

AUTHORITY_BANDS: tuple[str, ...] = (
    "primary_source",
    "official_channel",
    "wire_relay",
    "market",
    "unknown",
)


def authority_band(
    *,
    title: str,
    text: str,
    fine_role: str,
    tier: str,
) -> str:
    blob = (title or "") + "\n" + (text or "")
    role = fine_role or ""
    if role in {"official_primary", "party_primary", "institution_def"}:
        return "primary_source"
    if tier in {"central_official", "local_official"}:
        return "official_channel"
    if any(c in blob for c in _PRIMARY_CUE) and role in {"media_relay", "official_reprint"}:
        return "official_channel"
    if role in {"media_relay", "official_reprint"} or any(c in blob for c in _WIRE_CUE):
        return "wire_relay"
    if tier in {"market_media", "foreign_media", "self_media"}:
        return "market"
    return "unknown"


def portable_features(
    *,
    question: str,
    title: str,
    text: str,
    fine_role: str,
    url: str,
    frame: EventFrame,
) -> dict[str, Any]:
    tier = channel_tier(url or "", title or "")
    auth = authority_band(title=title, text=text, fine_role=fine_role, tier=tier)
    time_nail = bool(_DATE.search(text or "") or _DATE.search(title or ""))
    amount = bool(_AMOUNT.search(text or ""))
    align = frame_align_score(text, frame, title=title)
    side = option_side(text, frame)
    scope_hit = any(s in ((title or "") + (text or "")) for s in frame.scope_cues) if frame.scope_cues else False
    # 0～1 权威分，供一筛轻加（高相似时靠权威，对齐通义分享）
    auth_unit = {
        "primary_source": 1.0,
        "official_channel": 0.75,
        "wire_relay": 0.45,
        "market": 0.25,
        "unknown": 0.1,
    }.get(auth, 0.1)
    return {
        "authority_band": auth,
        "authority_unit": auth_unit,
        "channel_tier": tier,
        "has_time_nail": 1.0 if time_nail else 0.0,
        "has_amount": 1.0 if amount else 0.0,
        "frame_align": align,
        "option_side": side,
        "scope_hit": 1.0 if scope_hit else 0.0,
        "applicability": "in_scope" if scope_hit else ("unknown" if not frame.scope_cues else "no_cue"),
    }


def apply_portable_features(
    feats: dict[str, dict[str, float]],
    metas: dict[str, dict[str, Any]],
    url_of: dict[str, str],
    question: str,
    frame: EventFrame,
) -> None:
    """就地写入一筛可读特征。"""
    for pid, meta in metas.items():
        feat = feats.setdefault(pid, {})
        url = url_of.get(str(meta.get("doc_id") or ""), "")
        tags = portable_features(
            question=question,
            title=str(meta.get("title") or ""),
            text=str(meta.get("text") or ""),
            fine_role=str(meta.get("fine_role") or ""),
            url=url,
            frame=frame,
        )
        feat["frame_align"] = float(tags["frame_align"])
        feat["authority_unit"] = float(tags["authority_unit"])
        feat["has_time_nail"] = float(tags["has_time_nail"])
        feat["has_amount_nail"] = float(tags["has_amount"])
        feat["scope_hit"] = float(tags["scope_hit"])
        # 披露用字符串
        feat["authority_band"] = tags["authority_band"]  # type: ignore[assignment]
        feat["option_side"] = tags["option_side"]  # type: ignore[assignment]
        feat["applicability"] = tags["applicability"]  # type: ignore[assignment]
