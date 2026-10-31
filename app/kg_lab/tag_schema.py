"""R17：切片标签 schema —— 规定「打哪些类别」，不写案情专名。

具体主体／主张表面词由 ``case_lexicon`` 从问句或案情配置注入。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 类别枚举（切片打标必须覆盖；可增删，改动写进 R17 报告）
# ---------------------------------------------------------------------------

SPEAKER_ROLES: tuple[str, ...] = (
    "official_primary",
    "official_reprint",
    "institution_def",
    "party_primary",
    "party_relay",
    "opposition_framing",
    "mixed_summary",
    "media_relay",
    "commentary",
)

SOURCE_FINE_COMMENT: tuple[str, ...] = (
    "party_comment",
    "institutional_gloss",
    "mixed_roundup",
    "pure_opinion",
)

SOURCE_FINE_RELAY: tuple[str, ...] = (
    "relay_official_bulletin",
    "relay_party_primary",
    "relay_secondary",
)

CHANNEL_TIERS: tuple[str, ...] = (
    "central_official",
    "local_official",
    "market_media",
    "foreign_media",
    "self_media",
    "other",
)

CLAIM_GRAIN: tuple[str, ...] = ("claim_full", "claim_keyword")

AMOUNT_ATTR: tuple[str, ...] = ("amount_status",)
TIME_ATTR: tuple[str, ...] = ("time_anchor",)

SUBJECT_ATTR: tuple[str, ...] = ("subject_match", "subject_x_channel")

BAIT_SIGNALS: tuple[str, ...] = (
    "title_bait",
    "section_bait",
    "offtopic_cross_claim",
    "fake_gloss",
)

DEDUP_SIGNALS: tuple[str, ...] = ("stitch", "near_dup", "same_quote_cluster")

SLICE_EXTRA: tuple[str, ...] = (
    "identity_synonym",
    "resume_noise",
    "identity_resume",
)

# R17 遗留抽象主张族（R19 一筛主路径不再依赖；保留供对照／二筛兼容）
CLAIM_FAMILIES: tuple[str, ...] = ("leave", "money", "post")

# R19 可迁移元数据
AUTHORITY_BANDS: tuple[str, ...] = (
    "primary_source",
    "official_channel",
    "wire_relay",
    "market",
    "unknown",
)
EVENT_FRAME_KEYS: tuple[str, ...] = (
    "frame_align",
    "option_side",
    "has_time_nail",
    "has_amount_nail",
    "scope_hit",
    "applicability",
    "authority_unit",
)
QUERY_VIEWS: tuple[str, ...] = ("raw", "conclusion", "cause", "evidence")

TAG_CATEGORIES: dict[str, tuple[str, ...]] = {
    "speaker_role": SPEAKER_ROLES,
    "source_fine_comment": SOURCE_FINE_COMMENT,
    "source_fine_relay": SOURCE_FINE_RELAY,
    "channel_tier": CHANNEL_TIERS,
    "claim_grain": CLAIM_GRAIN,
    "amount_attr": AMOUNT_ATTR,
    "time_attr": TIME_ATTR,
    "subject_attr": SUBJECT_ATTR,
    "bait_signals": BAIT_SIGNALS,
    "dedup_signals": DEDUP_SIGNALS,
    "slice_extra": SLICE_EXTRA,
    "claim_family": CLAIM_FAMILIES,
    "authority_band": AUTHORITY_BANDS,
    "event_frame": EVENT_FRAME_KEYS,
    "query_view": QUERY_VIEWS,
}

# ---------------------------------------------------------------------------
# 用途划分：一筛＝相关度／角色／渠道排序；二筛＝去重与挡路惩罚
# ---------------------------------------------------------------------------

STAGE1_FEATURES: tuple[str, ...] = (
    "subject_match",
    "subject_x_channel",
    "claim_full",
    "claim_keyword",
    "amount_status",
    "time_anchor",
    "credibility",
    "channel_self",
    "identity_synonym",
    "resume_noise",
    "identity_resume",
    # R19 可迁移
    "frame_align",
    "authority_unit",
    "has_time_nail",
    "has_amount_nail",
    "scope_hit",
    # 独热由打标写入；系数表按名取
    *(f"role_{r}" for r in SPEAKER_ROLES),
    *(f"tier_{t}" for t in CHANNEL_TIERS),
    *(f"cmt_{c}" for c in SOURCE_FINE_COMMENT),
    *SOURCE_FINE_RELAY,
)

STAGE2_FEATURES: tuple[str, ...] = (
    "title_bait",
    "section_bait",
    "offtopic_cross_claim",
    "fake_gloss",
    "mixed_roundup",
    "mixed_summary",
    "pure_opinion",
    "commentary",
    "stitch",
    "near_dup",
    "same_quote_cluster",
    # 二筛读一筛已打的细桶名，但不把它们当排序维重拟合
    "r9_comment",
    "r9_relay",
    "fine_role",
    "channel_tier",
)

# 打标规则摘要（无专名）。实现落在 source_role / r9_buckets / inbox_rerank。
TAGGING_RULES: dict[str, str] = {
    "speaker_role": (
        "通报操作句／制度句／当事人第一人称或本人渠道／转述框／评论线索；"
        "当事人称谓由问句主体注入后拼「X表示／X称」。"
    ),
    "source_fine": "commentary 再拆制度说明／时间线综述／当事人评论／纯观点；relay 再拆通报／当事人原话／次级。",
    "channel_tier": "按 URL／标题媒体档，与可信度浮点脱钩。",
    "claim_grain": "R17：主张族 full/keyword。R19 主路径改用问句对立选项＋事件框架键 frame_align。",
    "amount_attr": "问句含金额线索且摘要槽有 amount_status；R19 另有 has_amount_nail。",
    "time_attr": "问句含时点线索且摘要槽有 procedure_dates；R19 另有 has_time_nail。",
    "bait_signals": "标题党／小节蹭分／跨主张偏题转载／伪制度说明——只进二筛加减，不进一筛系数。",
    "dedup": "拼段丢掉、近同文与同引语簇只留更高渠道／官方原文代表。",
    "authority_band": "可迁移权威档：一手／官方渠道／通讯社转述／市场／未知。",
    "event_frame": "时点×主体×对立选项／定性；无 leave/money/post 硬族。",
    "query_view": "检索改写视图：原句／结论／原因／证据。",
}


def schema_table() -> list[dict[str, Any]]:
    rows = []
    stage1 = set(STAGE1_FEATURES)
    stage2 = set(STAGE2_FEATURES)
    for cat, values in TAG_CATEGORIES.items():
        for v in values:
            stage = []
            if v in stage1 or any(v in s or s.endswith(v) or s.startswith(f"cmt_{v}") or s.startswith(f"role_{v}") or s.startswith(f"tier_{v}") for s in stage1):
                stage.append("stage1")
            if v in stage2:
                stage.append("stage2")
            if not stage:
                # 类别名本身：按归属表
                if cat in {"bait_signals", "dedup_signals"}:
                    stage = ["stage2"]
                elif cat == "claim_family":
                    stage = ["stage1", "stage2"]
                else:
                    stage = ["stage1"]
            rows.append({
                "category": cat,
                "tag": v,
                "stage": stage,
                "rule": TAGGING_RULES.get(cat) or TAGGING_RULES.get("source_fine", ""),
            })
    return rows
