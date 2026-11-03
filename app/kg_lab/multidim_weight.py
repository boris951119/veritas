"""R6：RRF 之后的多维标签加权求和。

score = rrf + Σ coeff_d × feature_d

维度各自 0～1，系数相加，不是「主体×角色」一个乘子。
通稿去重仍用 R4 粗角色簇；细角色只进入 source_role 这一维。
问句侧主体／主张来自 ``case_lexicon``，不在本文件写案情专名。
"""

from __future__ import annotations

from typing import Any

from app.kg_lab.case_lexicon import CaseLexicon, lexicon_for_question
from app.kg_lab.source_role import (
    _meta_from_row,
    cluster_representatives,
)
from app.kg_lab.summary_slots import extract_slots

DIMS: tuple[str, ...] = (
    "subject_match",
    "source_role",
    "claim_align",
    "amount_status",
    "time_anchor",
)

# R5 偏好压成 0～1，供 source_role 维。系数另扫。
ROLE_UNIT: dict[str, float] = {
    "official_primary": 1.00,
    "party_primary": 0.90,
    "institution_def": 0.80,
    "official_reprint": 0.75,
    "party_relay": 0.55,
    "media_relay": 0.40,
    "opposition_framing": 0.20,
    "commentary": 0.10,
    "mixed_summary": 0.00,
}


def query_actors(question: str, lex: CaseLexicon | None = None) -> list[str]:
    if lex is None:
        lex = lexicon_for_question(question)
    q = question or ""
    # 只保留问句里出现的主体（与旧行为一致）
    return [a for a in lex.actors if a in q]


def _speaker_score(actors: list[str], fine_role: str, lex: CaseLexicon) -> float:
    """说话人是否就是问句里的主体。提及本身不算这一档。"""
    role = fine_role or ""
    score = 0.0
    # 当事人：问句第一个非机构主体 ≈ 本人渠道
    orgs = {"官方", "体育局", "教育部", "外交部", "国防部"}
    party_actors = [a for a in actors if a not in orgs and not a.endswith(("局", "部", "中心", "委"))]
    inst_actors = [a for a in actors if a in orgs or a.endswith(("局", "部", "中心", "委")) or a == "官方"]
    if party_actors and role == "party_primary":
        score = 1.0
    elif party_actors and role == "party_relay":
        score = 0.5
    if inst_actors and role in {"official_primary", "institution_def"}:
        score = max(score, 1.0)
    elif inst_actors and role == "official_reprint":
        score = max(score, 0.5)
    return score


def subject_match(
    question: str,
    title: str,
    text: str,
    fine_role: str,
    *,
    aliases: bool = False,
    lex: CaseLexicon | None = None,
) -> float:
    if lex is None:
        lex = lexicon_for_question(question)
    actors = query_actors(question, lex)
    if not actors:
        return 0.0
    blob = (title or "") + "\n" + (text or "")

    def _mentioned(actor: str) -> bool:
        if not aliases:
            return actor in blob
        al = lex.actor_aliases.get(actor) or (actor,)
        return any(alias in blob for alias in al)

    mention = sum(1 for a in actors if _mentioned(a)) / len(actors)
    speaker = _speaker_score(actors, fine_role, lex)
    return round(0.35 * mention + 0.65 * speaker, 4)


def claim_align(
    question: str,
    text: str,
    *,
    frames: bool = False,
    lex: CaseLexicon | None = None,
) -> float:
    if lex is None:
        lex = lexicon_for_question(question)
    q = question or ""
    body = text or ""
    active: list[set[str]] = []
    for group in lex.claim_groups():
        if not any(t in q for t in group):
            # 问句可能只命中触发面；若族已激活则仍对齐
            fam_hit = False
            for fam in lex.active_families:
                if set(group) & set(lex.family_surfaces.get(fam) or ()):
                    fam_hit = True
                    break
            if not fam_hit:
                continue
        terms = set(group)
        if frames:
            for q_terms, evidence in lex.claim_frames:
                if any(t in q for t in q_terms) and any(t in group for t in q_terms):
                    terms.update(evidence)
        active.append(terms)
    if not active:
        # 退路：按已激活族
        for fam in lex.active_families:
            terms = set(lex.family_surfaces.get(fam) or ())
            if frames:
                terms.update(lex.family_frames.get(fam) or ())
            if terms:
                active.append(terms)
    if not active:
        return 0.0
    hit = sum(1 for terms in active if any(t in body for t in terms))
    return round(hit / len(active), 4)


def tag_evidence(text: str, lex: CaseLexicon | None = None) -> list[str]:
    """段内实际出现、可被问句对齐的表面词。"""
    body = text or ""
    found: list[str] = []
    pool: list[str] = []
    if lex is None:
        from app.kg_lab.case_lexicon import FAMILY_CATALOG
        for spec in FAMILY_CATALOG.values():
            pool.extend(spec["surfaces"])
            pool.extend(spec["frames"])
    else:
        for group in lex.claim_groups():
            pool.extend(group)
        for _q, evidence in lex.claim_frames:
            pool.extend(evidence)
    for term in pool:
        if term in body and term not in found:
            found.append(term)
    return found


def _amount_on(question: str) -> bool:
    q = question or ""
    return any(s in q for s in ("万", "元", "金额"))


def _time_on(question: str) -> bool:
    q = question or ""
    return any(s in q for s in ("年", "月", "日", "何时"))


def paragraph_features(
    question: str,
    *,
    title: str,
    text: str,
    fine_role: str,
    frames: bool = False,
    lex: CaseLexicon | None = None,
) -> dict[str, float]:
    if lex is None:
        lex = lexicon_for_question(question)
    slots = extract_slots(title, text)
    amount = 0.0
    if _amount_on(question) and slots.get("amount_status") not in (None, "", "none"):
        amount = 1.0
    time_anchor = 0.0
    if _time_on(question) and slots.get("procedure_dates"):
        time_anchor = 1.0
    return {
        "subject_match": subject_match(
            question, title, text, fine_role, aliases=frames, lex=lex,
        ),
        "source_role": float(ROLE_UNIT.get(fine_role or "", 0.1)),
        "claim_align": claim_align(question, text, frames=frames, lex=lex),
        "amount_status": amount,
        "time_anchor": time_anchor,
    }


def zero_coeff() -> dict[str, float]:
    return {d: 0.0 for d in DIMS}


def combine_score(rrf: float, feats: dict[str, float], coeff: dict[str, float]) -> float:
    """RRF 加各维。系数乘的是 0～1 特征，不是另一个角色乘子。"""
    total = float(rrf)
    for d in DIMS:
        total += float(coeff.get(d) or 0.0) * float(feats.get(d) or 0.0)
    return total


def build_bundle(
    rows: list[dict[str, Any]],
    fused: list[tuple[str, float]],
    question: str,
    *,
    frames: bool = False,
    prefer_ids: set[str] | None = None,
    lex: CaseLexicon | None = None,
    case_slug: str = "",
) -> dict[str, Any]:
    """特征与通稿簇只算一次，扫参只改系数。"""
    if lex is None:
        lex = lexicon_for_question(question, case_slug=case_slug)
    metas = {
        str(r["para_id"]): _meta_from_row(r, lex=lex)
        for r in rows if r.get("para_id")
    }
    rrf = {pid: float(sc) for pid, sc in fused if float(sc) > 0}
    rep_of = cluster_representatives(
        metas,
        prefer_ids=prefer_ids,
        scores=rrf if prefer_ids else None,
    )
    feats: dict[str, dict[str, float]] = {}
    for pid, meta in metas.items():
        feats[pid] = paragraph_features(
            question,
            title=str(meta.get("title") or ""),
            text=str(meta.get("text") or ""),
            fine_role=str(meta.get("fine_role") or ""),
            frames=frames,
            lex=lex,
        )
    rrf = {pid: float(sc) for pid, sc in fused if float(sc) > 0}
    groups: dict[str, list[str]] = {}
    for pid, rep in rep_of.items():
        groups.setdefault(rep, []).append(pid)
    return {
        "question": question,
        "metas": metas,
        "feats": feats,
        "rrf": rrf,
        "rep_of": rep_of,
        "groups": groups,
        "lexicon": lex.to_dict(),
    }


def rank_with_coeff(
    bundle: dict[str, Any],
    coeff: dict[str, float],
) -> list[tuple[str, float]]:
    """簇代表占该簇最高综合分的名次。不在 RRF 候选里的段不加分、不入名单。"""
    scores: dict[str, float] = {}
    for pid, rrf in bundle["rrf"].items():
        scores[pid] = combine_score(rrf, bundle["feats"].get(pid) or {}, coeff)
    cluster_best: dict[str, float] = {}
    for rep, members in bundle["groups"].items():
        vals = [scores[m] for m in members if m in scores]
        if not vals:
            continue
        cluster_best[rep] = max(vals)
    ranked = sorted(cluster_best.items(), key=lambda x: (-x[1], x[0]))
    return [(pid, round(sc, 6)) for pid, sc in ranked]
