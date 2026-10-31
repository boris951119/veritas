"""R19／R20：可迁移元数据标签（权威／时效／适用范围／框架对齐）。

不写案情专名；与 R17 schema 并列，供一筛加分与披露。
R20 补 publish_recency／title_option_hit；二筛只用可核验维，不叠「更像问句」。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.kg_lab.channel_tier import channel_tier
from app.kg_lab.event_frame import EventFrame, frame_align_score, option_side, option_paraphrases

_DATE = re.compile(r"\d{1,2}月\d{1,2}日|\d{4}\s*年|\d{1,2}\s*时\d{1,2}\s*分")
_AMOUNT = re.compile(r"\d+(?:\.\d+)?\s*万|\d{2,}\s*元|\$[\d,]+")
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_PRIMARY_CUE = (
    "通报", "新闻发布会", "我们予以", "按规定", "调查报告", "正式回应",
    "全文如下", "记者从", "发布会", "官方视频", "一手",
)
_WIRE_CUE = ("新华社", "据报道", "援引", "央视", "电（", "记者")
_VERIFY_CUE = (
    "通报", "全文", "原话", "监控", "档案", "数据显示", "调查报告",
    "按规定", "记者从", "发布会",
)

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


def parse_publish_date(raw: str) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    m = _ISO.search(s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None
    if len(digits) >= 6:
        try:
            return date(int(digits[:4]), int(digits[4:6]), 1)
        except ValueError:
            return None
    return None


def publish_recency_unit(publish_time: str, *, as_of: date | None = None) -> float:
    """发布时间越近越高（0～1）；缺省 0。窗口约 3 年。"""
    d = parse_publish_date(publish_time)
    if not d:
        return 0.0
    ref = as_of or date.today()
    days = (ref - d).days
    if days < 0:
        days = 0
    # 0 天＝1.0；~1095 天（3 年）＝0
    return round(max(0.0, 1.0 - days / 1095.0), 4)


def option_title_hit(title: str, frame: EventFrame) -> float:
    if not title or not frame.options:
        return 0.0
    hits = 0
    for opt in frame.options[:3]:
        keys = option_paraphrases(opt)[:3] or [opt]
        if any(k and k in title for k in keys):
            hits += 1
    return hits / max(1, min(3, len(frame.options)))


def verifiability_unit(title: str, text: str) -> float:
    blob = (title or "") + "\n" + (text or "")
    if not blob.strip():
        return 0.0
    n = sum(1 for c in _VERIFY_CUE if c in blob)
    return round(min(1.0, n / 3.0), 4)


def portable_features(
    *,
    question: str,
    title: str,
    text: str,
    fine_role: str,
    url: str,
    frame: EventFrame,
    publish_time: str = "",
) -> dict[str, Any]:
    tier = channel_tier(url or "", title or "")
    auth = authority_band(title=title, text=text, fine_role=fine_role, tier=tier)
    time_nail = bool(_DATE.search(text or "") or _DATE.search(title or ""))
    amount = bool(_AMOUNT.search(text or ""))
    align = frame_align_score(text, frame, title=title)
    side = option_side(text, frame)
    # 二筛用：只计选项／主体／时点，不含问句杂词（避免「更像问句」）
    option_align = frame_align_score(
        text,
        EventFrame(
            actors=frame.actors,
            options=frame.options,
            time_cues=frame.time_cues,
            qual_predicates=[],
            evidence_cues=frame.evidence_cues,
            scope_cues=[],
            question_terms=[],
        ),
        title=title,
    )
    scope_hit = any(s in ((title or "") + (text or "")) for s in frame.scope_cues) if frame.scope_cues else False
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
        "option_align": option_align,
        "option_side": side,
        "scope_hit": 1.0 if scope_hit else 0.0,
        "applicability": "in_scope" if scope_hit else ("unknown" if not frame.scope_cues else "no_cue"),
        "publish_time": publish_time or "",
        "publish_recency": publish_recency_unit(publish_time),
        "title_option_hit": option_title_hit(title, frame),
        "verifiability": verifiability_unit(title, text),
    }


def apply_portable_features(
    feats: dict[str, dict[str, float]],
    metas: dict[str, dict[str, Any]],
    url_of: dict[str, str],
    question: str,
    frame: EventFrame,
    publish_of: dict[str, str] | None = None,
) -> None:
    """就地写入一筛／二筛可读特征。"""
    publish_of = publish_of or {}
    for pid, meta in metas.items():
        feat = feats.setdefault(pid, {})
        url = url_of.get(str(meta.get("doc_id") or ""), "")
        pub = publish_of.get(str(meta.get("doc_id") or ""), "") or str(
            meta.get("publish_time") or ""
        )
        tags = portable_features(
            question=question,
            title=str(meta.get("title") or ""),
            text=str(meta.get("text") or ""),
            fine_role=str(meta.get("fine_role") or ""),
            url=url,
            frame=frame,
            publish_time=pub,
        )
        feat["frame_align"] = float(tags["frame_align"])
        feat["option_align"] = float(tags["option_align"])
        feat["authority_unit"] = float(tags["authority_unit"])
        feat["has_time_nail"] = float(tags["has_time_nail"])
        feat["has_amount_nail"] = float(tags["has_amount"])
        feat["scope_hit"] = float(tags["scope_hit"])
        feat["publish_recency"] = float(tags["publish_recency"])
        feat["title_option_hit"] = float(tags["title_option_hit"])
        feat["verifiability"] = float(tags["verifiability"])
        feat["authority_band"] = tags["authority_band"]  # type: ignore[assignment]
        feat["option_side"] = tags["option_side"]  # type: ignore[assignment]
        feat["applicability"] = tags["applicability"]  # type: ignore[assignment]
        feat["publish_time"] = tags["publish_time"]  # type: ignore[assignment]
        if pub and not meta.get("publish_time"):
            meta["publish_time"] = pub
