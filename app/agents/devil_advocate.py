"""反方质检员（C-47 件③）：只读案卷、零 LLM 输出质疑条目。

边界：不改 pipeline／core 判定；不调模型。产出是独立 JSON，
若要把条目嵌进 report.md／工作台主流程，需要改 pipeline 渲染——
本单禁止动 pipeline，故「出现在报告／工作台」该项如实记未达。
"""

from __future__ import annotations

from typing import Any

from app.core.evidence import Dossier

AGENT_NAME = "反方质检员 devil-advocate"
AGENT_DUTY = "只读案卷，机械输出质疑条目（无证结论／降级因果／缺重启条件）"
AGENT_ISOLATION = "独立模块；只读 Dossier，不写回结论与置信度"
AGENT_GATES = "零 LLM；输出条目须带 conclusion_id 或 conflict_id 可回溯"


def critique_dossier(dossier: Dossier, *, question_id: str = "") -> list[dict[str, Any]]:
    """对单题案卷出质疑条目。确定性、可复跑、零模型调用。"""
    items: list[dict[str, Any]] = []
    ev_by_con: dict[str, list] = {}
    for ev in dossier.evidences:
        ev_by_con.setdefault(ev.conclusion_id, []).append(ev)

    for con in dossier.conclusions:
        evs = ev_by_con.get(con.id) or []
        if not evs:
            items.append({
                "kind": "no_evidence",
                "severity": "high",
                "question_id": question_id,
                "conclusion_id": con.id,
                "detail": f"结论 {con.id} 无挂接证据",
            })
        for ev in evs:
            reason = (ev.degraded_reason or "").strip()
            if reason:
                items.append({
                    "kind": "causal_degraded",
                    "severity": "medium",
                    "question_id": question_id,
                    "conclusion_id": con.id,
                    "evidence_id": ev.id,
                    "detail": f"证据 {ev.id} 因果主张已降级——{reason}",
                })

    for pair in dossier.conflicts or []:
        if not isinstance(pair, dict):
            continue
        res = pair.get("resolution") if isinstance(pair.get("resolution"), dict) else {}
        restart = res.get("重启条件")
        if restart is None:
            restart = res.get("restart_condition")
        if not str(restart or "").strip():
            items.append({
                "kind": "missing_reopen",
                "severity": "medium",
                "question_id": question_id,
                "conflict_id": str(pair.get("id") or ""),
                "detail": (
                    f"冲突 {pair.get('id') or '？'} 消解记录缺非空重启条件"
                ),
            })
    return items


def run_on_report_dict(data: dict, *, question_id: str = "") -> dict[str, Any]:
    """从 report.json 形态的 dict 跑一遍，返回可落盘记录。"""
    dossier = Dossier.from_dict(data)
    qid = question_id or str(data.get("question_id") or "")
    items = critique_dossier(dossier, question_id=qid)
    return {
        "agent": AGENT_NAME,
        "question_id": qid,
        "question": str(data.get("question") or dossier.question or ""),
        "n_items": len(items),
        "items": items,
        "n_calls": 0,
        "note": (
            "零 LLM 机械质检；产出未接入 pipeline.render_report_md／"
            "工作台主流程（接入需改 pipeline，本单禁止）"
        ),
    }
