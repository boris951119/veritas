"""外部智能体结论入卷（MCP / 第三方接入）。

把外部 agent 的结构化研判物化进案卷，再走与管线相同的引文机械闸：
假引文进 rejected 并移出存活证据；结论 id 仍返回给调用方。
"""

from __future__ import annotations

from app.core.citation_check import audit_dossier
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    RelationKind,
)


def ingest_external_judgment(dossier: Dossier, payload: dict) -> list[str]:
    """外部 payload → 结论/证据入卷；返回新结论 id 列表。

    payload: {"agent": str, "conclusions":[{"statement", "evidence":[...]}]}
    """
    agent = str(payload.get("agent") or "external").strip() or "external"
    new_ids: list[str] = []
    for item in payload.get("conclusions") or []:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or "").strip()
        if not statement:
            continue
        con = Conclusion.create(statement=statement, author=agent)
        dossier.conclusions.append(con)
        new_ids.append(con.id)
        for ev in item.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            seg_id = str(ev.get("segment_id") or "").strip()
            if not seg_id or dossier.segment(seg_id) is None:
                continue
            try:
                relation = RelationKind(str(ev.get("relation") or "correlation"))
            except ValueError:
                relation = RelationKind.CORRELATION
            try:
                level = EvidenceLevel(str(ev.get("level") or "C"))
            except ValueError:
                level = EvidenceLevel.C
            node = EvidenceNode.create(
                conclusion_id=con.id,
                quote=str(ev.get("quote") or ""),
                segment_ids=[seg_id],
                relation=relation,
                level=level,
                note=str(ev.get("note") or ""),
                author=agent,
            )
            dossier.add_evidence(node)

    failures = audit_dossier(dossier)
    # 仅处理本次新结论上的失败证据，避免误伤案卷既有内容
    new_set = set(new_ids)
    for f in failures:
        if f.conclusion_id not in new_set:
            continue
        ev = dossier.evidence(f.evidence_id)
        dossier.rejected.append({
            "evidence_id": f.evidence_id,
            "conclusion_id": f.conclusion_id,
            "quote": ev.quote if ev else "",
            "problems": f.problems,
        })
        dossier.remove_evidence(f.evidence_id)
    return new_ids


def audit_ingested(dossier: Dossier, conclusion_ids: list[str]) -> list[dict]:
    """外部入卷结论的数字/计数机械闸（与主管线同口径）。

    引文核对已在入卷时打回；本函数补齐 numeric 侧（计算复算/溯源/
    计数）——外部智能体的数字主张与内部结论同权受审，MCP 摘要随
    返回，不入卷剔除（与主管线的黄牌语义一致）。"""
    from app.core.numeric_check import audit_counting, audit_numeric

    wanted = set(conclusion_ids)
    return [f for f in audit_numeric(dossier) + audit_counting(dossier)
            if f.get("conclusion_id") in wanted]
