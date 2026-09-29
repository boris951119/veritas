"""人机闭环：改结论、推翻裁决、重开冲突消解。

纯函数层，不写哈希链——由 server / 调用方负责 append human 事件。
"""

from __future__ import annotations

from app.agents.arbiter import Coordinator
from app.core.conflicts import (
    ConflictPair,
    Resolution,
    apply_resolution,
    validate_conflict,
)
from app.core.evidence import Dossier


def edit_conclusion(dossier: Dossier, conclusion_id: str, statement: str) -> None:
    """改写结论文案；结论不存在时抛 KeyError。"""
    con = dossier.conclusion(conclusion_id)
    if con is None:
        raise KeyError(f"结论不存在: {conclusion_id}")
    text = str(statement or "").strip()
    if not text:
        raise ValueError("statement 不能为空")
    con.statement = text


def _find_conflict(dossier: Dossier, conflict_id: str) -> tuple[int, ConflictPair]:
    for i, raw in enumerate(dossier.conflicts or []):
        pair = ConflictPair.from_dict(raw) if isinstance(raw, dict) else raw
        if pair.id == conflict_id:
            return i, pair
    raise KeyError(f"冲突不存在: {conflict_id}")


def override_resolution(dossier: Dossier, conflict_id: str,
                        winner_id: str) -> None:
    """人工指定胜方（a_id / b_id / tie）；非法 winner 抛 ValueError。

    先将双方恢复为 majority 并清空胜方旧 dissent 中与本冲突相关的记录，
    再按 apply_resolution 语义落卷。
    """
    idx, pair = _find_conflict(dossier, conflict_id)
    if winner_id not in (pair.a_id, pair.b_id, "tie"):
        raise ValueError(f"winner 非法: {winner_id}")
    problems = validate_conflict(pair, dossier)
    if problems:
        raise ValueError("; ".join(problems))

    for cid in (pair.a_id, pair.b_id):
        con = dossier.conclusion(cid)
        if con is None:
            continue
        con.status = "majority"
        con.dissent = [d for d in con.dissent
                       if d.get("conflict_id") != conflict_id]

    pair.resolution = Resolution(
        winner_id=winner_id,
        method=("tie" if winner_id == "tie" else "arbitration"),
        rationale="人工裁决",
        evidence_weight=(pair.resolution.evidence_weight
                         if pair.resolution else {}),
        rebuts=(pair.resolution.rebuts if pair.resolution else {}),
    )
    err = apply_resolution(pair, dossier)
    if err:
        raise ValueError(str(err.get("problems") or err))
    dossier.conflicts[idx] = pair.to_dict()


def reopen_conflicts(dossier: Dossier, coordinator: Coordinator,
                     conclusion_ids: list[str] | None = None) -> list:
    """对活跃结论重跑：冲突检测 → 质证 → 仲裁 → 落卷。

    返回新产生的 ConflictPair 列表；写入 dossier.conflicts（追加）。
    """
    if conclusion_ids is None:
        active = [c.id for c in dossier.conclusions
                  if c.status == "majority" and dossier.evidences_of(c.id)]
    else:
        active = list(conclusion_ids)
    # 重开前清掉旧冲突簿记，避免重复对；双方 status 拉回 majority
    for raw in list(dossier.conflicts or []):
        pair = ConflictPair.from_dict(raw) if isinstance(raw, dict) else raw
        for cid in (pair.a_id, pair.b_id):
            con = dossier.conclusion(cid)
            if con is not None and con.status == "dissent":
                con.status = "majority"
                con.dissent = [d for d in con.dissent
                               if d.get("conflict_id") != pair.id]
    dossier.conflicts = []

    pairs = coordinator.detect_conflicts(dossier, active)
    resolved: list = []
    for pair in pairs:
        rebuts = coordinator.run_rebuttals(dossier, pair)
        resolution = coordinator.arbitrate(dossier, pair, rebuts)
        if resolution is None:
            dossier.conflicts.append(pair.to_dict())
            resolved.append(pair)
            continue
        pair.resolution = resolution
        apply_resolution(pair, dossier)
        dossier.conflicts.append(pair.to_dict())
        resolved.append(pair)
    return resolved
