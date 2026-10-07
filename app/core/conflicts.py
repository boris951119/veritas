"""冲突识别与消解（榜单硬需求 4）。

职责边界：
- 冲突的**语义判定**（谁和谁矛盾）由 LLM 完成（agents/arbiter.py）；
- 本模块负责机械侧：冲突/裁决的数据结构、裁决结果的确定性校验
  （id 存在、双方确实各自挂证、winner 合法）、以及消解簿记
  （败方转少数意见保留、胜方挂 dissent 记录）——程序只做校验与
  簿记，不做语义决策。

消解语义：winner ∈ {a_id, b_id} 时败方 Conclusion.status 转
"dissent"（保留，不删除），胜方结论挂 dissent 记录；winner="tie"
表示证据加权后无法裁决，双方均保留为 majority 并记录分歧。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.core.confidence import evidence_strength_of
from app.core.evidence import Conclusion, Dossier


def _new_id() -> str:
    return f"CFL-{uuid.uuid4().hex[:10]}"


@dataclass
class Resolution:
    """一次消解：程序算的证据加权对比 + 仲裁说理 + 质证原文。"""

    winner_id: str                     # a_id / b_id / "tie"
    method: str = "arbitration"        # arbitration / tie / evidence_weight
    rationale: str = ""                # 仲裁理由（LLM 说理，原样保留）
    evidence_weight: dict = field(default_factory=dict)  # {"CON-x": 0.72, ...}
    rebuts: dict = field(default_factory=dict)  # {"a": 质证文本, "b": ...}

    def to_dict(self) -> dict:
        return {
            "winner_id": self.winner_id, "method": self.method,
            "rationale": self.rationale,
            "evidence_weight": self.evidence_weight, "rebuts": self.rebuts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Resolution":
        return cls(winner_id=str(d.get("winner_id", "tie")),
                   method=str(d.get("method", "arbitration")),
                   rationale=str(d.get("rationale", "")),
                   evidence_weight=dict(d.get("evidence_weight") or {}),
                   rebuts=dict(d.get("rebuts") or {}))


@dataclass
class ConflictPair:
    id: str = field(default_factory=_new_id)
    a_id: str = ""
    b_id: str = ""
    topic: str = ""
    description: str = ""
    resolution: Resolution | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "a_id": self.a_id, "b_id": self.b_id,
            "topic": self.topic, "description": self.description,
            "resolution": self.resolution.to_dict() if self.resolution else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConflictPair":
        return cls(id=str(d.get("id") or _new_id()),
                   a_id=str(d.get("a_id", "")), b_id=str(d.get("b_id", "")),
                   topic=str(d.get("topic", "")),
                   description=str(d.get("description", "")),
                   resolution=(Resolution.from_dict(d["resolution"])
                               if d.get("resolution") else None))


def validate_conflict(pair: ConflictPair, dossier: Dossier) -> list[str]:
    """冲突对机械校验：id 存在、a≠b、双方各挂至少一条存活证据。"""
    problems: list[str] = []
    if pair.a_id == pair.b_id:
        problems.append("冲突双方 id 相同")
    for cid in (pair.a_id, pair.b_id):
        con = dossier.conclusion(cid)
        if con is None:
            problems.append(f"结论不存在: {cid}")
        elif not dossier.evidences_of(cid):
            problems.append(f"结论 {cid} 无存活证据，不构成可裁决冲突")
    return problems


_WEIGHT_MARGIN = 0.20  # 强度差超过此值才否决 LLM，避免同级证据微调翻案


def prefer_stronger_side(pair: ConflictPair, dossier: Dossier,
                         resolution: Resolution | None) -> Resolution | None:
    """票数不能压过证据质量：LLM 把明显更弱的一侧判胜时，改判强侧。

    强度打平（差 ≤ 边际）尊重 LLM / tie。只改 resolution，不落卷。
    """
    if resolution is None or resolution.winner_id == "tie":
        return resolution
    weight = resolution.evidence_weight or compute_evidence_weight(pair, dossier)
    resolution.evidence_weight = weight
    winner = resolution.winner_id
    if winner not in (pair.a_id, pair.b_id):
        return resolution
    loser = pair.b_id if winner == pair.a_id else pair.a_id
    w_win = float(weight.get(winner, 0.0))
    w_lose = float(weight.get(loser, 0.0))
    if w_lose > w_win + _WEIGHT_MARGIN:
        resolution.winner_id = loser
        resolution.method = "evidence_weight"
        resolution.rationale = (
            f"程序按证据强度否决票数：{loser}={w_lose:.2f} > "
            f"{winner}={w_win:.2f}（多数派引用不能压过更高强度证据）。"
            + (f" 原仲裁：{resolution.rationale}" if resolution.rationale else "")
        )
    return resolution


def compute_evidence_weight(pair: ConflictPair, dossier: Dossier) -> dict:
    """双方证据强度对比（程序口径，作为仲裁的机械输入写入消解记录）。"""
    return {
        pair.a_id: round(evidence_strength_of(pair.a_id, dossier), 4),
        pair.b_id: round(evidence_strength_of(pair.b_id, dossier), 4),
    }


def apply_resolution(pair: ConflictPair, dossier: Dossier) -> dict | None:
    """把合法裁决落进案卷簿记；非法裁决返回问题清单且不落卷。

    落卷动作：
    - winner=a/b：败方 status="dissent"（保留少数意见），胜方挂 dissent 记录；
    - winner=tie：双方保持 majority，冲突记为分歧未决。
    """
    if pair.resolution is None:
        return {"reason": "无裁决"}
    problems = validate_conflict(pair, dossier)
    if problems:
        return {"problems": problems}
    winner = pair.resolution.winner_id
    if winner not in (pair.a_id, pair.b_id):
        if winner != "tie":
            return {"problems": [f"winner 非法: {winner}"]}
        pair.resolution.method = "tie"
        return None  # tie：合法，双方不动
    loser_id = pair.b_id if winner == pair.a_id else pair.a_id
    winner_con = dossier.conclusion(winner)
    loser_con = dossier.conclusion(loser_id)
    loser_con.status = "dissent"
    winner_con.dissent.append({
        "conflict_id": pair.id,
        "conclusion_id": loser_id,
        "author": "、".join(loser_con.author_names()) or loser_id,
        "statement": loser_con.statement,
        "why": pair.resolution.rationale,
    })
    return None


def majority_conclusions(dossier: Dossier) -> list[Conclusion]:
    return [c for c in dossier.conclusions if c.status == "majority"]


def dissent_conclusions(dossier: Dossier) -> list[Conclusion]:
    return [c for c in dossier.conclusions if c.status == "dissent"]
