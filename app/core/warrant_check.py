"""理由—主张主题词闸（零 LLM）：主张里的议题主题词须在所引段落出现。

拦的是「账目截止日 → 不存在人员流失」这类：引文真、数字真，但推不出主张。
只亮黄灯，不删结论。
"""

from __future__ import annotations

from app.core.evidence import Dossier

# 议题侧常见主题词（主张命中其一，则所引段落须命中同一词或其同义组）
_THEME_GROUPS: tuple[tuple[str, ...], ...] = (
    ("延期", "延迟", "滞后", "进度"),
    ("回款", "应收账款", "应收"),
    ("坏账", "计提坏账", "坏账风险"),
    ("人员流失", "离职", "流失", "人力"),
    ("停工", "停产"),
    ("资金链", "流动性"),
)


# 否证：主张在否认某主题，所引段落用裁决句而不是复读指控原词。
# 不用「无 / 未 / 正常」——「未提及回款」「无坏账」会把真脱节放过去。
_DENIAL_CUES = ("并未", "不存在", "否认", "并不", "没有发生", "未发生")
_REBUTTAL_CUES = (
    "传闻不实", "不实", "核查后确认", "核查确认",
    "按计划运转", "未发生", "无异常", "予以澄清", "并不存在",
)


def _themes_in(text: str) -> set[str]:
    """返回文本命中的主题组代表词（每组取第一个命中的代表）。"""
    q = text or ""
    hit: set[str] = set()
    for group in _THEME_GROUPS:
        if any(term in q for term in group):
            hit.add(group[0])
    return hit


def audit_warrant_theme(dossier: Dossier) -> list[dict]:
    """主张主题词 ∩ 所引段落主题词 = ∅ → 黄灯。"""
    flags: list[dict] = []
    for con in dossier.conclusions:
        claim_themes = _themes_in(con.statement or "")
        if not claim_themes:
            continue
        evs = dossier.evidences_of(con.id)
        if not evs:
            continue
        # 只看所引段落。说明是模型复述主张，写进「人员流失」就会把闸放行。
        blob_parts: list[str] = []
        for ev in evs:
            hit_seg = False
            for sid in ev.segment_ids:
                seg = dossier.segment(sid)
                if seg is not None and (seg.text or ""):
                    blob_parts.append(seg.text or "")
                    hit_seg = True
            if not hit_seg:
                blob_parts.append(ev.quote or "")
        blob = "\n".join(blob_parts)
        support = _themes_in(blob)
        missing = claim_themes - support
        if (missing and _denies(con.statement or "") and _rebuts(blob)):
            missing = set()
        missing_list = sorted(missing)
        if not missing_list:
            continue
        flags.append({
            "kind": "warrant_theme",
            "severity": "medium",
            "conclusion_id": con.id,
            "value": "、".join(missing_list),
            "detail": (
                f"结论主张含主题词「{'、'.join(missing_list)}」，"
                "但所引段落中无共同主题词——理由与主张可能脱节"
            ),
        })
    return flags


def _denies(statement: str) -> bool:
    return any(cue in statement for cue in _DENIAL_CUES)


def _rebuts(segment_text: str) -> bool:
    return any(cue in segment_text for cue in _REBUTTAL_CUES)
