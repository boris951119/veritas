"""外部智能体结论入卷（MCP / 第三方接入）。

把外部 agent 的结构化研判物化进案卷，再走与管线相同的引文机械闸：
假引文进 rejected 并移出存活证据；结论 id 仍返回给调用方。

主张带署名：每条入卷结论/证据/打回都记下提交方（agent / agent_id /
submitted_at），出事可指认「哪家智能体被拒」。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.citation_check import audit_dossier
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    RelationKind,
)


def _submitter(payload: dict) -> dict:
    """从 payload 抽出可审计的提交方身份。"""
    agent = str(payload.get("agent") or "external").strip() or "external"
    agent_id = str(payload.get("agent_id") or payload.get("submitter_id")
                   or agent).strip() or agent
    submitted_at = str(payload.get("submitted_at") or "").strip() or (
        datetime.now(timezone.utc).isoformat()
    )
    return {"agent": agent, "agent_id": agent_id, "submitted_at": submitted_at}


def ingest_external_judgment(dossier: Dossier, payload: dict) -> list[str]:
    """外部 payload → 结论/证据入卷；返回新结论 id 列表。

    payload: {
      "agent": str,                 # 显示名（必填语义）
      "agent_id"?: str,             # 稳定标识（缺省同 agent）
      "submitted_at"?: str,         # ISO 时间（缺省此刻）
      "conclusions":[{"statement", "evidence":[...]}]
    }
    """
    who = _submitter(payload)
    agent = who["agent"]
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
            "agent": who["agent"],
            "agent_id": who["agent_id"],
            "submitted_at": who["submitted_at"],
            "source": "external_ingest",
        })
        dossier.remove_evidence(f.evidence_id)
    # 与主管线 _reject_failed_citations 同口径：证据全灭的结论标
    # insufficient，不得以默认 majority 当正式判断交出去。
    for cid in new_ids:
        con = dossier.conclusion(cid)
        if con is None or con.status == "merged":
            continue
        if dossier.evidences_of(cid):
            continue
        con.status = "insufficient"
        if "资料不足" not in (con.statement or ""):
            con.statement = f"资料不足：{con.statement}" if con.statement \
                else "资料不足，无法形成可核验结论"
        con.confidence = 0.0
    return new_ids


def attribution_summary(dossier: Dossier, conclusion_ids: list[str],
                        payload: dict) -> dict:
    """入卷后的责任摘要：谁提交、过了几条、打回几条（MCP/演示用）。"""
    who = _submitter(payload)
    wanted = set(conclusion_ids)
    n_evidence = sum(1 for e in dossier.evidences if e.conclusion_id in wanted)
    rejected = [r for r in dossier.rejected
                if r.get("conclusion_id") in wanted
                and r.get("source") == "external_ingest"]
    return {
        **who,
        "ingested_ids": list(conclusion_ids),
        "n_conclusions": len(conclusion_ids),
        "n_evidence_kept": n_evidence,
        "n_rejected": len(rejected),
        "rejected": [
            {
                "conclusion_id": r.get("conclusion_id"),
                "quote": (r.get("quote") or "")[:120],
                "problems": r.get("problems") or [],
            }
            for r in rejected
        ],
    }


def audit_ingested(dossier: Dossier, conclusion_ids: list[str]) -> list[dict]:
    """外部入卷结论的数字/计数机械闸（与主管线同口径）。

    引文核对已在入卷时打回；本函数补齐 numeric 侧（计算复算/溯源/
    计数）——外部智能体的数字主张与内部结论同权受审，MCP 摘要随
    返回，不入卷剔除（与主管线的黄牌语义一致）。"""
    from app.core.numeric_check import audit_counting, audit_numeric

    wanted = set(conclusion_ids)
    return [f for f in audit_numeric(dossier) + audit_counting(dossier)
            if f.get("conclusion_id") in wanted]
