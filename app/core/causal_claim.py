"""结构化因果主张卡：校验声称完整性，缺则降级为相关（C-32）。

边界：系统校验因果声称的结构完整性与措辞纪律，不做效应估计、不做完整因果引擎。
降级通过改 ``ev.relation → CORRELATION`` 实现——``confidence.py`` 一行不碰；
``:187`` 读的就是 ``ev.relation``，降级后 1.15 加成自然不生效。
"""

from __future__ import annotations

from app.core.evidence import Dossier, EvidenceNode, RelationKind

# 报告／边界披露（跨面复用时点名工件）
BOUNDARY_NOTE = (
    "系统校验因果声称的结构完整性与措辞纪律，"
    "不做效应估计、不做完整因果引擎"
)

CLAIM_KEYS = ("intervention", "outcome", "population", "counterfactual")
MECHANISM_VALUES = frozenset({"direct", "indirect", "correlation_only"})
MISSING_LINK_VALUES = frozenset({"mediator", "temporal", "contrast"})
DESIGN_TIER_VALUES = frozenset({"rct", "quasi", "observational", "claim_only"})

MISSING_LINK_CN = {
    "mediator": "缺中介",
    "temporal": "缺时序",
    "contrast": "缺对照",
}


def normalize_claim_fields(ev: EvidenceNode) -> None:
    """缺省与非法枚举回落（不抛）；旧产物兼容。"""
    if not ev.mechanism_completeness or ev.mechanism_completeness not in MECHANISM_VALUES:
        ev.mechanism_completeness = "correlation_only"
    if not ev.design_tier or ev.design_tier not in DESIGN_TIER_VALUES:
        ev.design_tier = "claim_only"
    if ev.missing_links is None:
        ev.missing_links = []
    else:
        ev.missing_links = [
            x for x in ev.missing_links if x in MISSING_LINK_VALUES]
    if not ev.declared_relation:
        ev.declared_relation = ev.relation.value
    if ev.degraded_reason is None:
        ev.degraded_reason = ""


def claim_missing_keys(claim) -> list[str]:
    """四要素缺哪些键（值空也算缺）。"""
    if not isinstance(claim, dict):
        return list(CLAIM_KEYS)
    out: list[str] = []
    for k in CLAIM_KEYS:
        val = claim.get(k)
        if val is None or (isinstance(val, str) and not str(val).strip()):
            out.append(k)
    return out


def degrade_reasons(ev: EvidenceNode) -> list[str]:
    """若该证据当前标 causation，返回须降级的原因列表（空＝可保持）。"""
    reasons: list[str] = []
    missing = claim_missing_keys(ev.causal_claim)
    if missing:
        reasons.append("缺主张卡要素：" + "、".join(missing))
    if ev.mechanism_completeness == "indirect":
        links = [x for x in (ev.missing_links or []) if x in MISSING_LINK_VALUES]
        if not links:
            reasons.append("indirect 未填 missing_links（须 mediator／temporal／contrast）")
    return reasons


def apply_causal_claim_gates(dossier: Dossier) -> dict:
    """在 recompute_all 之前跑一遍：缺卡／缺环的 causation → 降级为相关。

    返回 accounting 摘要（n_degraded / n_kept）。不写 flags——黄牌由
    ``audit_causal_claim_missing`` 即时重算（与其它闸同形）。
    """
    n_degraded = 0
    n_kept = 0
    for ev in dossier.evidences:
        normalize_claim_fields(ev)
        if ev.relation != RelationKind.CAUSATION:
            # 已降级残留：保留 declared_relation／degraded_reason 供展示
            continue
        reasons = degrade_reasons(ev)
        if reasons:
            ev.declared_relation = "causation"
            ev.relation = RelationKind.CORRELATION
            ev.degraded_reason = "；".join(reasons)
            n_degraded += 1
        else:
            ev.declared_relation = "causation"
            ev.degraded_reason = ""
            n_kept += 1
    return {"n_degraded": n_degraded, "n_kept": n_kept,
            "note": BOUNDARY_NOTE}


def audit_causal_claim_missing(dossier: Dossier) -> list[dict]:
    """已降级或缺卡的因果声明 → 黄牌 causal_claim_missing。"""
    flags: list[dict] = []
    for ev in dossier.evidences:
        normalize_claim_fields(ev)
        reason = (ev.degraded_reason or "").strip()
        declared = (ev.declared_relation or "").strip()
        if not reason:
            continue
        if declared != "causation" and ev.relation != RelationKind.CAUSATION:
            continue
        flags.append({
            "kind": "causal_claim_missing",
            "severity": "medium",
            "conclusion_id": ev.conclusion_id,
            "value": ev.id,
            "detail": (
                f"证据 {ev.id} 原声明 causation，因主张卡不完整已降级为 "
                f"correlation——{reason}"
            ),
        })
    return flags


def missing_links_cn(ev: EvidenceNode) -> list[str]:
    """报告可见的缺环中文标签（indirect 且已填时）。"""
    if ev.mechanism_completeness != "indirect":
        return []
    return [MISSING_LINK_CN[x] for x in (ev.missing_links or [])
            if x in MISSING_LINK_CN]


VERDICT_DIRECT = "直接因果"
VERDICT_INDIRECT = "间接传导"
VERDICT_CORRELATION = "仅相关"
VERDICT_VALUES = (VERDICT_DIRECT, VERDICT_INDIRECT, VERDICT_CORRELATION)


def verdict_of(ev: EvidenceNode) -> dict:
    """官方加分 4.1.1 三档判定＝**只读已有结构化事实**的机械派生。

    对齐锚点原文「对『X 导致 Y』类结论明确区分直接因果／间接传导／仅相关，
    并说明判定理由（如是否存在中间环节缺失）」。这里不新造任何内容：
    输入只有 ``relation／declared_relation／mechanism_completeness／
    missing_links／causal_claim 四要素／degraded_reason``（都是生产侧已落的字段），
    卡没填就是没填——判到「仅相关」时理由点名缺哪几项，并给出升档条件
    （＝补齐后由 ``apply_causal_claim_gates`` 复评，通过才回到间接／直接）。
    """
    normalize_claim_fields(ev)
    missing = claim_missing_keys(ev.causal_claim)
    cn_links = missing_links_cn(ev)
    declared_causal = (ev.declared_relation == "causation"
                       or ev.relation == RelationKind.CAUSATION)
    causation_kept = ev.relation == RelationKind.CAUSATION

    if causation_kept and ev.mechanism_completeness == "direct" and not missing:
        verdict = VERDICT_DIRECT
        reason = "主张卡四要素齐＋自述无中间环节缺失，且未被降为相关"
    elif (causation_kept and ev.mechanism_completeness == "indirect"
            and not missing):
        verdict = VERDICT_INDIRECT
        reason = (f"仍按因果记，但中间环节未闭合（缺：{'、'.join(cn_links)}）"
                  if cn_links else
                  "仍按因果记且自述为间接，但未指明缺哪一环（missing_links 空）")
    else:
        verdict = VERDICT_CORRELATION
        if ev.degraded_reason:
            reason = f"原声明因果，已按闸降级：{ev.degraded_reason}"
        elif not declared_causal:
            reason = "未声明因果关系（relation=correlation），按仅相关记"
        else:
            reason = "因果主张卡不完整，按仅相关记"

    steps: list[str] = []
    if missing:
        steps.append("补齐主张卡缺项：" + "、".join(missing))
    if (ev.mechanism_completeness == "indirect"
            and declared_causal and not cn_links):
        steps.append("indirect 须指明缺环（mediator／temporal／contrast）")
    if declared_causal and not causation_kept:
        steps.append("补齐后由 apply_causal_claim_gates 复评，通过才回到间接／直接")
    if not steps:
        steps.append("已达标，无需升档")
    return {"因果判定": verdict, "判定理由": reason,
            "升档条件": "；".join(steps)}
