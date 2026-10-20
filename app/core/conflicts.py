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
from app.core.dup_check import duplicate_map, near_dup_pairs
from app.core.evidence import Conclusion, Dossier


def _new_id() -> str:
    return f"CFL-{uuid.uuid4().hex[:10]}"


# method 可能取值与这张表是同一份。漏映射在导入时失败，不许静默落「其他」。
# 官方五级是参考（rubric:327）；decks:325 允许在依据可核验时扩展。
# 依据用户口径 2026-10-16＋官方 decks:325 可扩展条款，未经 A/B。
RESOLUTION_METHODS = frozenset({
    "arbitration", "tie", "evidence_weight", "source_majority",
})
_OFFICIAL_RESOLUTION_TYPES = frozenset({
    "多数投票", "来源优先级", "时效性", "语义可信度", "其他",
})
# 同一张表同时覆盖 method 与 decision_path。类型以 decision_path 优先
# （strength 即使 method 仍是 arbitration，也是「语义可信度」）。
_DECISION_PATHS = frozenset({
    "strength", "source_majority", "tie", "llm_arbitration", "human_override",
})
METHOD_TO_RESOLUTION_TYPE = {
    "arbitration": "其他",
    "tie": "其他",
    "evidence_weight": "语义可信度",
    "source_majority": "多数投票",
    "strength": "语义可信度",
    "llm_arbitration": "其他",
    "human_override": "其他",
}
if set(METHOD_TO_RESOLUTION_TYPE) != RESOLUTION_METHODS | _DECISION_PATHS:
    raise RuntimeError("method 映射表键集与 method／decision_path 取值集不一致")
if not set(METHOD_TO_RESOLUTION_TYPE.values()) <= _OFFICIAL_RESOLUTION_TYPES:
    raise RuntimeError("method 映射落到了官方五级之外")

_REOPEN_WHEN = {
    "strength": (
        "败方取得新的一手信源（证据等级 ≥B）使双方强度差回落到 0.20 以内，"
        "或胜方证据被人工删除后，重启本冲突"
    ),
    "source_majority": (
        "败方独立信源数（去同源后）追平或超过胜方，"
        "或双方强度差扩大到 0.20 以上后，重启本冲突"
    ),
    "tie": "任一方补充新证据后即重启（本冲突此前无机械判据，仅凭仲裁说理）",
    "llm_arbitration": "任一方补充新证据后即重启（本冲突此前无机械判据，仅凭仲裁说理）",
    "human_override": "若人工撤销改判则恢复机械路径",
}


def reopen_when_for(decision_path: str) -> str:
    return _REOPEN_WHEN.get(decision_path) or _REOPEN_WHEN["llm_arbitration"]


@dataclass
class Resolution:
    """一次消解：程序算的证据加权对比 + 仲裁说理 + 质证原文。"""

    winner_id: str                     # a_id / b_id / "tie"
    method: str = "arbitration"        # arbitration / tie / evidence_weight / source_majority
    rationale: str = ""                # 仲裁理由（LLM 说理，原样保留）
    evidence_weight: dict = field(default_factory=dict)  # {"CON-x": 0.72, ...}
    rebuts: dict = field(default_factory=dict)  # {"a": 质证文本, "b": ...}
    basis: dict = field(default_factory=dict)
    resolution_type: str = ""
    decision_path: str = ""
    omissions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out = {
            "winner_id": self.winner_id, "method": self.method,
            "rationale": self.rationale,
            "evidence_weight": self.evidence_weight, "rebuts": self.rebuts,
            "basis": self.basis, "resolution_type": self.resolution_type,
            "decision_path": self.decision_path,
            "omissions": list(self.omissions or []),
        }
        if self.decision_path:
            out["重启条件"] = reopen_when_for(self.decision_path)
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Resolution":
        return cls(winner_id=str(d.get("winner_id", "tie")),
                   method=str(d.get("method", "arbitration")),
                   rationale=str(d.get("rationale", "")),
                   evidence_weight=dict(d.get("evidence_weight") or {}),
                   rebuts=dict(d.get("rebuts") or {}),
                   basis=dict(d.get("basis") or {}),
                   resolution_type=str(d.get("resolution_type") or ""),
                   decision_path=str(d.get("decision_path") or ""),
                   omissions=list(d.get("omissions") or []))


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
    """冲突对机械校验：id 存在、a≠b、双方挂证、主体一致。"""
    problems: list[str] = []
    if pair.a_id == pair.b_id:
        problems.append("冲突双方 id 相同")
    for cid in (pair.a_id, pair.b_id):
        con = dossier.conclusion(cid)
        if con is None:
            problems.append(f"结论不存在: {cid}")
        elif not dossier.evidences_of(cid):
            problems.append(f"结论 {cid} 无存活证据，不构成可裁决冲突")
    if not problems:
        from app.core.conflict_pairing import subject_mismatch_reason

        mismatch = subject_mismatch_reason(dossier, pair.a_id, pair.b_id)
        if mismatch:
            problems.append(mismatch)
    return problems


_WEIGHT_MARGIN = 0.20  # 强度差超过此值才否决 LLM，避免同级证据微调翻案


def _cited_source_ids(conclusion_id: str, dossier: Dossier) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for ev in dossier.evidences_of(conclusion_id):
        for seg_id in ev.segment_ids:
            src = dossier.source_of_segment(seg_id)
            if src is None or src.id in seen:
                continue
            seen.add(src.id)
            ids.append(src.id)
    return ids


def _source_fold(conclusion_id: str, dossier: Dossier,
                 exact: dict[str, str] | None = None,
                 pairs: list | None = None) -> tuple[int, int, int]:
    """(独立信源数, 精确重复折掉件数, 近似同源折掉件数)。只调 dup_check 两道闸。

    exact／pairs 由调用方传入时不再重算。prefer_stronger_side 每次调用只算一次。
    """
    if exact is None or pairs is None:
        exact = duplicate_map(dossier)
        pairs = near_dup_pairs(dossier)
    cited = _cited_source_ids(conclusion_id, dossier)
    exact_folded = 0
    folded: list[str] = []
    for sid in cited:
        canon = exact.get(sid, sid)
        if canon != sid:
            exact_folded += 1
        if canon not in folded:
            folded.append(canon)
    node_set = set(folded)
    graph: dict[str, set[str]] = {sid: set() for sid in folded}
    for a, b, _jac in pairs:
        if a in node_set and b in node_set:
            graph[a].add(b)
            graph[b].add(a)
    order = {src.id: i for i, src in enumerate(dossier.sources)}
    seen: set[str] = set()
    near_folded = 0
    kept = 0
    for node in folded:
        if node in seen:
            continue
        stack = [node]
        seen.add(node)
        comp = [node]
        while stack:
            cur = stack.pop()
            for nxt in graph[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
                    comp.append(nxt)
        comp.sort(key=lambda sid: order.get(sid, 10**9))
        kept += 1
        near_folded += len(comp) - 1
    return kept, exact_folded, near_folded


def independent_source_count(conclusion_id: str, dossier: Dossier) -> int:
    """存活证据所挂信源，去掉精确重复与近似同源后的个数。"""
    count, _exact, _near = _source_fold(conclusion_id, dossier)
    return count


def _fmt(value: float) -> str:
    return format(value, ".4f")


def _loser_clearly_stronger(w_win: float, w_lose: float) -> bool:
    """败方强度明显高出胜方（超过 margin）——prefer／mechanical 共用这一条。"""
    return w_lose > w_win + _WEIGHT_MARGIN


def _stamp(resolution: Resolution, pair: ConflictPair, dossier: Dossier,
           decision_path: str, exact: dict[str, str] | None = None,
           pairs: list | None = None,
           mechanical_path: str = "") -> None:
    """只补 basis / resolution_type / decision_path，不改 winner、method、rationale。

    resolution_type 由 decision_path 查表，不看 method。
    """
    sa = evidence_strength_of(pair.a_id, dossier)
    sb = evidence_strength_of(pair.b_id, dossier)
    na, ea, na_near = _source_fold(pair.a_id, dossier, exact, pairs)
    nb, eb, nb_near = _source_fold(pair.b_id, dossier, exact, pairs)
    exact_count = ea + eb
    near = na_near + nb_near
    gap = abs(sa - sb)
    basis = {
        "strength": {pair.a_id: sa, pair.b_id: sb},
        "independent_sources": {pair.a_id: na, pair.b_id: nb},
        "margin": _WEIGHT_MARGIN,
        "decision_path": decision_path,
        "dedup": {"exact": exact_count, "near": near},
        "strength_gap": gap,
    }
    winner = resolution.winner_id
    margin_s = f"{_WEIGHT_MARGIN:.2f}"
    gap_s = _fmt(gap)
    omissions: list[str] = list(resolution.omissions or [])
    if decision_path == "human_override" and winner in (pair.a_id, pair.b_id):
        win_s = sa if winner == pair.a_id else sb
        lose_s = sb if winner == pair.a_id else sa
        mech = mechanical_path or "llm_arbitration"
        basis["mechanical_path"] = mech
        type_applies = (
            f"人工改判，机械判断原为 {mech}"
            f"（胜方强度 {_fmt(win_s)} vs 败方 {_fmt(lose_s)}）"
        )
        loser_excluded = f"人工改判后未采信（原机械判断：{mech}）"
        if "人工改判" not in omissions:
            omissions.append("人工改判")
    elif decision_path == "strength" and winner in (pair.a_id, pair.b_id):
        win_s = sa if winner == pair.a_id else sb
        lose_s = sb if winner == pair.a_id else sa
        type_applies = f"双方强度差 {gap_s} > {margin_s}，按证据强度裁决"
        if win_s <= lose_s:
            loser_excluded = "未按强度关系排除败方（数值关系不成立）"
            if "假不等式已拦截" not in omissions:
                omissions.append("假不等式已拦截")
        else:
            loser_excluded = f"败方强度 {_fmt(lose_s)} ＜ 胜方 {_fmt(win_s)}"
    elif decision_path == "source_majority" and winner in (pair.a_id, pair.b_id):
        win_n = na if winner == pair.a_id else nb
        lose_n = nb if winner == pair.a_id else na
        type_applies = (
            f"双方强度差 {gap_s} ≤ {margin_s}，强度不足以裁决，转入独立信源数比较"
        )
        loser_excluded = (
            f"败方独立信源 {lose_n} 个 ＜ 胜方 {win_n} 个"
            f"（已折掉 {exact_count + near} 件同源转载）"
        )
    elif decision_path == "tie":
        type_applies = (
            f"双方强度差 {gap_s} ≤ {margin_s}，独立信源数同为 {na} 与 {nb}，无机械胜负"
        )
        loser_excluded = "双方均未排除"
    else:
        type_applies = f"双方强度差 {gap_s}，未进入机械破平，仅凭仲裁说理"
        loser_excluded = "未按强度或独立信源数排除败方"
    basis["type_applies"] = type_applies
    basis["loser_excluded"] = loser_excluded
    resolution.basis = basis
    resolution.decision_path = decision_path
    resolution.resolution_type = METHOD_TO_RESOLUTION_TYPE[decision_path]
    resolution.omissions = omissions


def _break_tie_by_sources(resolution: Resolution, pair: ConflictPair,
                          dossier: Dossier, exact: dict[str, str] | None = None,
                          pairs: list | None = None) -> str:
    """势均力敌时用独立信源数破平。

    依据用户口径 2026-10-16＋官方 decks:325 可扩展条款，未经 A/B。
    未验证「数票是否更接近人的判断」。信源数相同则 tie，不按 id 或顺序定胜负。
    """
    na = _source_fold(pair.a_id, dossier, exact, pairs)[0]
    nb = _source_fold(pair.b_id, dossier, exact, pairs)[0]
    if na == nb:
        resolution.winner_id = "tie"
        resolution.method = "tie"
        return "tie"
    resolution.winner_id = pair.a_id if na > nb else pair.b_id
    resolution.method = "source_majority"
    return "source_majority"


def prefer_stronger_side(pair: ConflictPair, dossier: Dossier,
                         resolution: Resolution | None) -> Resolution | None:
    """票数不能压过证据质量。

    强度差 > _WEIGHT_MARGIN：按强度定胜负，票数不参与，与改前的改判文案逐字相同。
    强度差 ≤ _WEIGHT_MARGIN 且 LLM 已指定胜方：独立信源数多的一方胜；仍相同则 tie。
    LLM 已判 tie 则维持 tie。
    依据用户口径 2026-10-16＋官方 decks:325 可扩展条款，未经 A/B。
    """
    if resolution is None:
        return resolution
    exact = duplicate_map(dossier)
    pairs = near_dup_pairs(dossier)
    if resolution.winner_id == "tie":
        _stamp(resolution, pair, dossier, "tie", exact, pairs)
        return resolution
    weight = resolution.evidence_weight or compute_evidence_weight(pair, dossier)
    resolution.evidence_weight = weight
    winner = resolution.winner_id
    if winner not in (pair.a_id, pair.b_id):
        _stamp(resolution, pair, dossier, "llm_arbitration", exact, pairs)
        return resolution
    loser = pair.b_id if winner == pair.a_id else pair.a_id
    w_win = float(weight.get(winner, 0.0))
    w_lose = float(weight.get(loser, 0.0))
    if _loser_clearly_stronger(w_win, w_lose):
        resolution.winner_id = loser
        resolution.method = "evidence_weight"
        resolution.rationale = (
            f"程序按证据强度否决票数：{loser}={w_lose:.2f} > "
            f"{winner}={w_win:.2f}（多数派引用不能压过更高强度证据）。"
            + (f" 原仲裁：{resolution.rationale}" if resolution.rationale else "")
        )
        path = "strength"
    elif abs(w_win - w_lose) <= _WEIGHT_MARGIN:
        path = _break_tie_by_sources(resolution, pair, dossier, exact, pairs)
    else:
        path = "strength"
    _stamp(resolution, pair, dossier, path, exact, pairs)
    return resolution


def mechanical_decision_path(pair: ConflictPair, dossier: Dossier,
                             resolution: Resolution,
                             exact: dict[str, str] | None = None,
                             pairs: list | None = None) -> str:
    """按现有强度差／信源数规则读出路径，不改 winner／method／rationale。

    人工改判用它读出机械原判；盖章路径另走 human_override。
    """
    if resolution.winner_id == "tie":
        return "tie"
    weight = resolution.evidence_weight or compute_evidence_weight(pair, dossier)
    if resolution.winner_id not in (pair.a_id, pair.b_id):
        return "llm_arbitration"
    winner = resolution.winner_id
    loser = pair.b_id if winner == pair.a_id else pair.a_id
    w_win = float(weight.get(winner, 0.0))
    w_lose = float(weight.get(loser, 0.0))
    if _loser_clearly_stronger(w_win, w_lose) or abs(w_win - w_lose) > _WEIGHT_MARGIN:
        return "strength"
    na = _source_fold(pair.a_id, dossier, exact, pairs)[0]
    nb = _source_fold(pair.b_id, dossier, exact, pairs)[0]
    if na == nb:
        return "tie"
    return "source_majority"


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
        "reopen_when": reopen_when_for(
            pair.resolution.decision_path or "llm_arbitration"),
    })
    return None


def majority_conclusions(dossier: Dossier) -> list[Conclusion]:
    return [c for c in dossier.conclusions if c.status == "majority"]


def dissent_conclusions(dossier: Dossier) -> list[Conclusion]:
    return [c for c in dossier.conclusions if c.status == "dissent"]
