"""主席汇总层（仲裁汇总的「汇总」半边）：把已过闸结论组装成面向议题的答案。

赛题原文「仲裁汇总」——仲裁早已落地（冲突→质证→裁决），缺的是没人
正面回答议题。本模块补上，三条铁律（承讨论定稿）：

1. **输入封闭**：只喂已过全部闸的结论/冲突/少数意见/前提缺口——
   主席没有资格接触原始资料，只汇总已验证的事实，不做新研判；
2. **输出过闸**：结构化契约（headline/points/open_issues），每点挂
   con_id；四道机械闸——引用存在、**完整性（每条多数结论必须有着落：
   在 points 里，或自动补全）、数字溯源（headline/gloss 的数字必须能在
   所引结论 statement 里找到）、长度（单动作体裁才限字数：headline≤80、
   每条 gloss/issue≤60；汇总体裁的总长由结论数导出，不设魔法常数）**；
   违规点不丢结论——用零 LLM 模板点顶替（auto 标记）；
3. **零 LLM 兜底**：`render_chair_template` 纯程序渲染——LLM 失败/
   桩路径/未启用时，报告永远有综合意见，演示永不空。

synthesis 是研判终态快照：人工修改结论后不自动重算（报告可live回退
模板渲染），快照过期属已知开放问题（见 dev-journal §10）。
"""

from __future__ import annotations

import re

from app.agents.base import extract_json
from app.core.conflicts import majority_conclusions
from app.core.evidence import Dossier
from app.core.numeric_check import (
    _provenance_nums, _value_in_corpus, extract_nums,
)

_HEADLINE_MAX = 80
_GLOSS_MAX = 60
_ISSUE_MAX = 60

CHAIR_SYSTEM = """你是研判主席，负责把多名分析师经机械核对与仲裁后的结论汇总为面向议题的综合研判意见。

铁律（违反任何一条即无效）：
1. 只能依据下方「结论清单」汇总——禁止引入清单外的任何信息、数字或判断；
2. 每条要点必须挂对应的结论编号 con_id，你的概括里出现的每个数字必须能在该结论原文中找到；
3. 完整性：每条多数结论要么进 points，要么在 open_issues 给出不纳入的理由（kind=note）——不得静默丢弃；
4. 分歧必须明示：未决冲突与少数意见进 open_issues，不得抹平；
5. 资料不足要如实写进 open_issues（kind=gap），不要硬凑答案；
6. 长度：headline 为一句话（≤80字，正面回答议题）；每条 gloss ≤60字；每条 open_issue ≤60字。

输出 JSON（不要输出任何其他文字）：
{
  "headline": "一句话正面回答议题",
  "points": [{"con_id": "CON-x", "gloss": "对该结论的一句话概括"}],
  "open_issues": [{"kind": "conflict|dissent|gap|note", "ref": "CON-x 或 CFL-x 或议题", "text": "一句话说明"}]
}"""


# ---------------------------------------------------------------- 零 LLM 模板


def _trim(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_chair_template(dossier: Dossier) -> dict:
    """纯程序渲染的综合意见：确定性、离线可用、LLM 失败的兜底。"""
    majors = sorted(majority_conclusions(dossier),
                    key=lambda c: (-c.confidence, c.id))
    top = majors[0] if majors else None
    headline = _trim(f"置信度最高的判断：{top.statement}", _HEADLINE_MAX) \
        if top else "（无多数结论——检查资料覆盖或分析师输出）"
    points = [{"con_id": c.id, "gloss": _trim(c.statement, _GLOSS_MAX),
               "confidence": round(c.confidence, 2), "auto": True}
              for c in majors]
    open_issues: list[dict] = []
    for raw in dossier.conflicts or []:
        res = (raw or {}).get("resolution") if isinstance(raw, dict) else None
        winner = (res or {}).get("winner_id")
        state = "未决（并列保留）" if not winner or winner == "tie" else "已裁决"
        open_issues.append({"kind": "conflict", "ref": str(raw.get("id")),
                            "text": _trim(f"{raw.get('topic') or '结论对立'}"
                                          f"——{state}", _ISSUE_MAX)})
    for c in dossier.conclusions:
        if c.status == "dissent":
            open_issues.append({"kind": "dissent", "ref": c.id,
                                "text": _trim(f"少数意见保留：{c.statement}",
                                              _ISSUE_MAX)})
    from app.core.premise_check import premise_flags

    for f in premise_flags(dossier)[:3]:
        open_issues.append({"kind": "gap", "ref": "议题",
                            "text": _trim(f["detail"], _ISSUE_MAX)})
    from app.core.fact_ledger import find_collisions

    collisions = find_collisions(dossier)
    if collisions:
        open_issues.append({"kind": "note", "ref": "资料",
                            "text": _trim(f"资料内数字冲突 {len(collisions)} 处"
                                          "（见对撞台账，结论须正面回应）",
                                          _ISSUE_MAX)})
    return {"mode": "template", "headline": headline, "points": points,
            "open_issues": open_issues}


# ---------------------------------------------------------------- 四道闸


def _numbers_traceable(text: str, corpus: str) -> bool:
    """文本中的有效数字（剥日期/序数/计数噪声）必须能在语料中找到。"""
    for n in _provenance_nums(text, ""):
        if not _value_in_corpus(n, corpus):
            return False
    return True


def _validate_llm_output(dossier: Dossier, data: dict) -> tuple[dict, list[str]]:
    """LLM 输出 → 过闸并自动补全；返回 (synthesis, 闸记事)。"""
    majors = {c.id: c for c in majority_conclusions(dossier)}
    notes: list[str] = []

    headline = str(data.get("headline") or "").strip()
    full_corpus = "\n".join(c.statement for c in majors.values())
    if not headline or len(headline) > _HEADLINE_MAX \
            or not _numbers_traceable(headline, full_corpus):
        headline = render_chair_template(dossier)["headline"]
        notes.append("headline 违规（长度/数字无溯源）→ 模板顶替")

    points: list[dict] = []
    seen: set[str] = set()
    for p in data.get("points") or []:
        if not isinstance(p, dict):
            continue
        con = majors.get(str(p.get("con_id") or ""))
        gloss = str(p.get("gloss") or "").strip()
        if con is None:
            notes.append(f"points 引用不存在的结论 {p.get('con_id')} → 丢弃")
            continue
        if con.id in seen:
            continue
        if not gloss or len(gloss) > _GLOSS_MAX \
                or not _numbers_traceable(gloss, con.statement):
            gloss = _trim(con.statement, _GLOSS_MAX)
            notes.append(f"{con.id} 概括违规 → 原文顶替")
        points.append({"con_id": con.id, "gloss": gloss,
                       "confidence": round(con.confidence, 2), "auto": False})
        seen.add(con.id)

    n_auto = 0
    for cid, con in majors.items():  # 完整性：漏掉的多数结论自动补全
        if cid not in seen:
            points.append({"con_id": cid,
                           "gloss": _trim(con.statement, _GLOSS_MAX),
                           "confidence": round(con.confidence, 2), "auto": True})
            n_auto += 1
    if n_auto:
        notes.append(f"{n_auto} 条多数结论被遗漏 → 程序自动补全")

    conflict_ids = {str((c or {}).get("id")) for c in dossier.conflicts or []}
    open_issues: list[dict] = []
    kinds_seen: set[str] = set()
    for o in data.get("open_issues") or []:
        if not isinstance(o, dict):
            continue
        kind = str(o.get("kind") or "")
        ref = str(o.get("ref") or "")
        text = _trim(str(o.get("text") or ""), _ISSUE_MAX)
        if kind in ("conflict", "dissent") and ref not in conflict_ids \
                and dossier.conclusion(ref) is None:
            continue  # 引用不存在 → 丢弃
        if kind and text:
            open_issues.append({"kind": kind, "ref": ref, "text": text})
            kinds_seen.add(kind)
    # 分歧不得抹平：有冲突/异议而 LLM 全略过 → 模板补
    tmpl = render_chair_template(dossier)
    for issue in tmpl["open_issues"]:
        if issue["kind"] == "conflict" and "conflict" not in kinds_seen:
            open_issues.append(issue)
            notes.append("未决冲突被略过 → 模板补全")
        if issue["kind"] == "dissent" and "dissent" not in kinds_seen:
            open_issues.append(issue)
            notes.append("少数意见被略过 → 模板补全")

    points.sort(key=lambda p: (-p["confidence"], p["con_id"]))
    return {"mode": "llm", "headline": headline, "points": points,
            "open_issues": open_issues, "gate_notes": notes}, notes


# ---------------------------------------------------------------- 入口


def build_synthesis(dossier: Dossier, client, model: str) -> dict:
    """生产路径走 LLM+四道闸（违规点模板顶替，绝不整案弃用）；
    client 为 None（桩/离线/未启用）直接模板。结果写入 dossier.synthesis。"""
    template = render_chair_template(dossier)
    if client is None:
        dossier.synthesis = template
        return template
    from app.agents.prompts import render_conclusions_block

    user = [render_conclusions_block(
        dossier, [c.id for c in majority_conclusions(dossier)])]
    if dossier.conflicts:
        user.append("\n冲突与消解记录："
                    + "；".join(f"{c.get('topic')}({c.get('id')})" for c in
                                dossier.conflicts[:5]))
    dissents = [c for c in dossier.conclusions if c.status == "dissent"]
    if dissents:
        user.append("\n少数意见：" + "；".join(
            f"[{c.id}] {c.statement}" for c in dissents[:5]))
    gaps = template["open_issues"]
    if gaps:
        user.append("\n已知资料缺口：" + "；".join(
            g["text"] for g in gaps if g["kind"] == "gap"))
    try:
        data = extract_json(client.chat(model, [
            {"role": "system", "content": CHAIR_SYSTEM},
            {"role": "user", "content": "\n".join(user)},
        ], json_mode=True).content)
        synthesis, _notes = _validate_llm_output(dossier, data)
    except Exception as exc:
        synthesis = dict(template)
        synthesis["gate_notes"] = [f"主席调用失败（{type(exc).__name__}）→ 模板兜底"]
    dossier.synthesis = synthesis
    return synthesis
