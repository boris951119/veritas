"""理由—主张脱节闸（零 LLM）：两条规则取并集，任一成立即亮黄灯。

① 主张命中的议题主题词须在同一段落出现；② 主张与所引段落取词不得零交集。
拦的是「账目截止日 → 不存在人员流失」这类：引文真、数字真，但推不出主张。
只亮黄灯，不删结论；措辞一致而语义不支撑的假支撑两条都查不出（见 docs/proposal.md 局限性）。

C-72：另加行为型并列要点覆盖守护（kind=parallel_coverage）——结论含并列要点而
引文只盖住一部分 ⇒ 黄灯＋写清缺哪一半。只亮灯、不评分、不删结论；受
VERITAS_CLAIM_SLOTS 开关门控（关＝本条不跑，与改前逐字相同）。
"""

from __future__ import annotations

import re

from app.core.evidence import Dossier

# 议题侧常见主题词。主张闸的「主题词脱节」半边读这张表；
# premise_check、coverage_gap、chain_integrity、gate_applicability 也用它。
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


_CJK = re.compile(r"[\u4e00-\u9fff]+")
_LATIN = re.compile(r"[A-Za-z]{3,}")
_DIGITS = re.compile(r"\d+")


def _tokens(text: str) -> set[str]:
    """中文二元组、不少于 3 个字母的拉丁词、数字串。没有可调阈值。"""
    q = text or ""
    out: set[str] = set()
    for run in _CJK.findall(q):
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    for word in _LATIN.findall(q):
        out.add(word.lower())
    out.update(_DIGITS.findall(q))
    return out


def _evidence_blob(dossier: Dossier, con) -> str:
    """只看所引段落。说明是模型复述主张，写进主张里的词就会把闸放行。"""
    blob_parts: list[str] = []
    for ev in dossier.evidences_of(con.id):
        hit_seg = False
        for sid in ev.segment_ids:
            seg = dossier.segment(sid)
            if seg is not None and (seg.text or ""):
                blob_parts.append(seg.text or "")
                hit_seg = True
        if not hit_seg:
            blob_parts.append(ev.quote or "")
    return "\n".join(blob_parts)


def audit_warrant_theme(dossier: Dossier) -> list[dict]:
    """主题词脱节或措辞零交集，任一成立即黄灯。否定式放行在两条之前。"""
    flags: list[dict] = []
    for con in dossier.conclusions:
        evs = dossier.evidences_of(con.id)
        if not evs:
            continue
        blob = _evidence_blob(dossier, con)
        statement = con.statement or ""
        if _denies(statement) and _rebuts(blob):
            continue
        values: list[str] = []
        details: list[str] = []
        claim_themes = _themes_in(statement)
        if claim_themes:
            missing = sorted(claim_themes - _themes_in(blob))
            if missing:
                joined = "、".join(missing)
                values.extend(missing)
                details.append(
                    f"主题词脱节：结论主张含主题词「{joined}」，"
                    "所引段落未出现同一主题词"
                )
        claim_tokens = _tokens(statement)
        if claim_tokens and not (claim_tokens & _tokens(blob)):
            values.append("零交集")
            details.append("措辞零交集：结论主张与所引段落取词没有交集")
        if not details:
            continue
        flags.append({
            "kind": "warrant_theme",
            "severity": "medium",
            "conclusion_id": con.id,
            "value": "、".join(values),
            "detail": "；".join(details),
        })
    return flags


# 并列切分：顿号／以及／同时／一方面…另一方面／不仅…还
_PARALLEL_SPLIT = re.compile(
    r"(?:一方面|另一方面|不仅|而且|并且|同时|以及|还有|、|；|;)"
)
_PARALLEL_CUES = (
    "一方面", "另一方面", "不仅", "同时", "以及", "并且", "还有", "、",
)


def _parallel_parts(statement: str) -> list[str]:
    """主张里的并列要点；少於 2 段则不启本条。"""
    s = (statement or "").strip()
    if not s or not any(c in s for c in _PARALLEL_CUES):
        return []
    parts = [p.strip() for p in _PARALLEL_SPLIT.split(s) if p and p.strip()]
    # 过短碎片丢掉（标点噪音）
    parts = [p for p in parts if len(re.sub(r"\s+", "", p)) >= 4]
    return parts if len(parts) >= 2 else []


def audit_parallel_coverage(dossier: Dossier) -> list[dict]:
    """并列要点只被引文盖住一部分 → 黄灯。关 CLAIM_SLOTS 时空列表。"""
    try:
        from app.core.claim_slots import claim_slots_enabled
    except ImportError:
        return []
    if not claim_slots_enabled():
        return []
    flags: list[dict] = []
    for con in dossier.conclusions:
        if not dossier.evidences_of(con.id):
            continue
        parts = _parallel_parts(con.statement or "")
        if len(parts) < 2:
            continue
        blob = _evidence_blob(dossier, con)
        blob_tok = _tokens(blob)
        missing: list[str] = []
        covered_n = 0
        for part in parts:
            pt = _tokens(part)
            if pt and (pt & blob_tok):
                covered_n += 1
            else:
                missing.append(part[:30])
        # 部分覆盖才亮（全缺／全盖都不走这条——全缺留给零交集）
        if missing and covered_n > 0:
            joined = "、".join(missing)
            flags.append({
                "kind": "parallel_coverage",
                "severity": "medium",
                "conclusion_id": con.id,
                "value": joined,
                "detail": (
                    f"并列要点覆盖不全：引文已覆盖 {covered_n}/{len(parts)}，"
                    f"缺「{joined}」；只亮灯，不改分、不删结论"
                ),
            })
    return flags


def _denies(statement: str) -> bool:
    return any(cue in statement for cue in _DENIAL_CUES)


def _rebuts(segment_text: str) -> bool:
    return any(cue in segment_text for cue in _REBUTTAL_CUES)
