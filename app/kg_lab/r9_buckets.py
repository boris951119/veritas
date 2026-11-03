"""R9：把卡住金标的粗桶拆开。规则打标，主张词来自 lexicon，不读金标 id。

评论 → party_comment / institutional_gloss / mixed_roundup / pure_opinion
转述 → relay_official_bulletin / relay_party_primary / relay_secondary
口径 → claim_full（问句原词或直接引语）/ claim_keyword（只命中框架词），二者互斥
主体×渠道 → 问句主体本人渠道（微博／深夜发文）
"""

from __future__ import annotations

import re
from typing import Any

from app.kg_lab.case_lexicon import (
    CaseLexicon,
    FAMILY_CATALOG,
    GENERIC_BULLETIN,
    GENERIC_GLOSS,
    GENERIC_PARTY_VOICE,
    lexicon_for_question,
)

_DATE = re.compile(r"\d{1,2}月\d{1,2}日")

COMMENT_BUCKETS: tuple[str, ...] = (
    "party_comment",
    "institutional_gloss",
    "mixed_roundup",
    "pure_opinion",
)
RELAY_BUCKETS: tuple[str, ...] = (
    "relay_official_bulletin",
    "relay_party_primary",
    "relay_secondary",
)

_ROUNDUP_TITLE = ("时间线", "尘埃落定", "大结局", "回顾")
_OPINION = ("热评", "快评", "观点", "网友", "舆论", "估算")


def comment_bucket(
    title: str,
    text: str,
    fine_role: str,
    lex: CaseLexicon | None = None,
) -> str:
    if fine_role != "commentary":
        return ""
    blob = (title or "") + "\n" + (text or "")
    gloss = tuple((lex.gloss if lex else GENERIC_GLOSS))
    party = tuple((lex.party_voice if lex else GENERIC_PARTY_VOICE))
    if any(s in blob for s in gloss):
        return "institutional_gloss"
    dates = set(_DATE.findall(text or ""))
    if any(s in blob for s in _ROUNDUP_TITLE) or len(dates) >= 2:
        return "mixed_roundup"
    if any(s in blob for s in party):
        return "party_comment"
    if any(s in blob for s in _OPINION):
        return "pure_opinion"
    return "pure_opinion"


def relay_bucket(
    title: str,
    text: str,
    fine_role: str,
    lex: CaseLexicon | None = None,
) -> str:
    """只拆 media_relay / party_relay。official_reprint 仍走原来的角色维。"""
    if fine_role not in {"media_relay", "party_relay"}:
        return ""
    blob = (title or "") + "\n" + (text or "")
    party = tuple((lex.party_voice if lex else GENERIC_PARTY_VOICE))
    bulletin = tuple((lex.bulletin if lex else GENERIC_BULLETIN))
    if any(s in blob for s in party) or (
        fine_role == "party_relay" and ("微博" in blob or "发文" in blob)
    ):
        return "relay_party_primary"
    if any(s in (text or "") for s in bulletin):
        return "relay_official_bulletin"
    return "relay_secondary"


def _full_surfaces(lex: CaseLexicon) -> tuple[str, ...]:
    out: list[str] = []
    for fam in lex.active_families or list(FAMILY_CATALOG):
        for t in lex.family_surfaces.get(fam) or FAMILY_CATALOG.get(fam, {}).get("surfaces") or ():
            if t not in out:
                out.append(t)
    return tuple(out)


def _keyword_surfaces(lex: CaseLexicon) -> tuple[str, ...]:
    out: list[str] = []
    for fam in lex.active_families or list(FAMILY_CATALOG):
        for t in lex.family_frames.get(fam) or FAMILY_CATALOG.get(fam, {}).get("frames") or ():
            if t not in out:
                out.append(t)
    return tuple(out)


def claim_bits(question: str, text: str, lex: CaseLexicon | None = None) -> tuple[float, float]:
    """返回 (claim_full, claim_keyword)，互斥。问句没触发的词不计。"""
    if lex is None:
        lex = lexicon_for_question(question)
    q = question or ""
    body = text or ""
    full_pool = _full_surfaces(lex)
    q_full = [t for t in full_pool if t in q]
    # 问句只写了族触发面、没写 surfaces 里的词时，用已激活族的 surfaces 作 full 候选
    if not q_full and lex.active_families:
        q_full = list(full_pool)
    syns = _expand_synonyms(q_full, lex) if q_full else ()
    if q_full and syns and any(t in body for t in syns):
        return 1.0, 0.0
    if _question_opens_keyword(q, lex) and any(t in body for t in _keyword_surfaces(lex)):
        return 0.0, 1.0
    return 0.0, 0.0


def _expand_synonyms(q_terms: list[str], lex: CaseLexicon) -> tuple[str, ...]:
    """问句点了哪一侧，段内的直接说法都算 full。"""
    extra = set(q_terms)
    for fam, spec in FAMILY_CATALOG.items():
        if any(t in q_terms for t in spec["triggers"]) or any(t in q_terms for t in spec["surfaces"]):
            extra.update(lex.family_surfaces.get(fam) or spec["surfaces"])
    return tuple(extra)


def _question_opens_keyword(q: str, lex: CaseLexicon | None = None) -> bool:
    if lex and lex.active_families:
        return True
    for spec in FAMILY_CATALOG.values():
        if any(t in q for t in spec["triggers"]):
            return True
    return False


def subject_x_channel(
    question: str,
    title: str,
    text: str,
    fine_role: str,
    relay: str,
    lex: CaseLexicon | None = None,
) -> float:
    """问句关键主体本人 × 他发声的渠道。转述他的微博原话也算。"""
    if lex is None:
        lex = lexicon_for_question(question)
    q = question or ""
    blob = (title or "") + "\n" + (text or "")
    own = any(s in blob for s in ("微博", "发微博", "深夜发文", "再发文", "全文如下"))
    orgs = {a for a in lex.actors if a.endswith(("局", "部", "中心", "委")) or a in {"官方", "体育局"}}
    party = [a for a in lex.actors if a in q and a not in orgs]
    if party and own and (fine_role == "party_primary" or relay == "relay_party_primary"):
        return 1.0
    if any(a in q for a in orgs) and fine_role == "official_primary":
        return 1.0
    return 0.0


R9_ADDED: tuple[str, ...] = (
    "claim_full",
    "claim_keyword",
    "subject_x_channel",
    "cmt_party_comment",
    "cmt_institutional_gloss",
    "cmt_mixed_roundup",
    "cmt_pure_opinion",
    "relay_official_bulletin",
    "relay_party_primary",
    "relay_secondary",
)

REPLACED: tuple[str, ...] = (
    "claim_align",
    "role_commentary",
    "role_party_relay",
    "role_media_relay",
)


def apply_r9(
    feats: dict[str, dict[str, float]],
    metas: dict[str, dict[str, Any]],
    question: str,
    lex: CaseLexicon | None = None,
) -> None:
    """就地改特征。评论／转述改走细桶；claim_align 改成 full/keyword。"""
    if lex is None:
        lex = lexicon_for_question(question)
    for pid, meta in metas.items():
        feat = feats.setdefault(pid, {})
        title = str(meta.get("title") or "")
        text = str(meta.get("text") or "")
        role = str(meta.get("fine_role") or "")
        cmt = comment_bucket(title, text, role, lex)
        relay = relay_bucket(title, text, role, lex)
        full, keyword = claim_bits(question, text, lex)
        feat["claim_full"] = full
        feat["claim_keyword"] = keyword
        feat["claim_align"] = 0.0
        feat["subject_x_channel"] = subject_x_channel(question, title, text, role, relay, lex)
        for name in (
            "cmt_party_comment", "cmt_institutional_gloss",
            "cmt_mixed_roundup", "cmt_pure_opinion",
            "relay_official_bulletin", "relay_party_primary", "relay_secondary",
        ):
            feat[name] = 0.0
        if cmt:
            feat[f"cmt_{cmt}"] = 1.0
            feat["role_commentary"] = 0.0
        if relay:
            feat[relay] = 1.0
            feat["role_party_relay"] = 0.0
            feat["role_media_relay"] = 0.0
        feat["r9_comment"] = cmt
        feat["r9_relay"] = relay


def r9_names(base: tuple[str, ...]) -> tuple[str, ...]:
    kept = tuple(n for n in base if n not in REPLACED)
    return kept + R9_ADDED


def r9_init(r8_coeff: dict[str, float]) -> dict[str, float]:
    """从 R8 系数平移：细桶先继承被拆掉的那一档，再交给搜索拉开。"""
    w = {n: float(r8_coeff.get(n) or 0.0) for n in r8_coeff}
    for name in R9_ADDED:
        w[name] = 0.0
    w["claim_full"] = float(r8_coeff.get("claim_align") or 0.0)
    w["claim_keyword"] = float(r8_coeff.get("claim_align") or 0.0)
    cmt = float(r8_coeff.get("role_commentary") or 0.0)
    for b in COMMENT_BUCKETS:
        w[f"cmt_{b}"] = cmt
    w["relay_official_bulletin"] = float(r8_coeff.get("role_media_relay") or 0.0)
    w["relay_party_primary"] = float(r8_coeff.get("role_party_relay") or 0.0)
    w["relay_secondary"] = float(r8_coeff.get("role_media_relay") or 0.0)
    for name in REPLACED:
        w[name] = 0.0
    return w


# 兼容旧 inbox_rerank import：从 lexicon／目录拼默认全表
def _compat_full_keyword() -> tuple[tuple[str, ...], tuple[str, ...]]:
    full: list[str] = []
    key: list[str] = []
    for spec in FAMILY_CATALOG.values():
        full.extend(spec["surfaces"])
        key.extend(spec["frames"])
    # 去重保序
    def u(xs: list[str]) -> tuple[str, ...]:
        s: list[str] = []
        for x in xs:
            if x not in s:
                s.append(x)
        return tuple(s)
    return u(full), u(key)


_FULL, _KEYWORD = _compat_full_keyword()


def _synonyms_for(q_terms: list[str]) -> tuple[str, ...]:
    """旧接口：只传问句命中的表面词。"""
    return _expand_synonyms(q_terms, lexicon_for_question(" ".join(q_terms)))
