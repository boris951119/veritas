"""Skill 注册表：条件触发的提示词纪律 + 配对机械闸。

纪律（承自 token-burner，按 veritas 语义重写）：
- **没有闸的 skill 是许愿**——每条 rule 必须配一道零 LLM 机械闸；
  skill 教模型「怎么诚实」，闸负责「不诚实就亮灯」，缺一不注册；
- **trigger 条件触发**——命中案卷特征才注入，守提示词预算；
- **enabled=False 只注册不下发**——disabled_reason 写明在等什么语料；
- **无 A/B 红绿差不下发**——新 skill 上线前按 docs/ab-protocol.md
  跑开关对照，打回率/复现率无可度量差异则不启用。

注入路径：core.skills.render_skills_rules(dossier) → Analyst.analyze
把命中规则拼进系统提示词；闸在 core/audit.audit_all 统一执行。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core.evidence import Dossier, SourceType

# 配对闸的合法 kind（闸本体在 numeric_check / discourse_check / citation_check）
KNOWN_GATES = {
    "citation", "calc", "provenance", "counting",
    "hedge", "level_tone",
}

_LOWCRED = {SourceType.NEWS, SourceType.WEB, SourceType.NOTE}


# ---------------------------------------------------------------- 触发器


def _table_share(dossier: Dossier) -> float:
    segs = [s.text for src in dossier.sources for s in src.segments]
    if not segs:
        return 0.0
    hit = sum(1 for t in segs if sum(1 for ln in t.splitlines()
                                     if ln.strip().startswith("|")) >= 2)
    return hit / len(segs)


def _numeric_share(dossier: Dossier) -> float:
    segs = [s.text for src in dossier.sources for s in src.segments]
    if not segs:
        return 0.0
    import re

    hit = sum(1 for t in segs if len(re.findall(r"\d", t)) >= 6)
    return hit / len(segs)


def _lowcred_share(dossier: Dossier) -> float:
    if not dossier.sources:
        return 0.0
    return sum(1 for s in dossier.sources if s.source_type in _LOWCRED) \
        / len(dossier.sources)


def _always(dossier: Dossier) -> bool:
    return True


@dataclass
class GateSkill:
    """一条提示词纪律：trigger 命中时把 rule 注入分析师系统提示。"""

    name: str
    description: str            # 防什么幻觉（答辩/审计口径）
    rule: str                   # 注入文本（≤3 行，强制语气）
    trigger: Callable[[Dossier], bool]
    gate: str                   # 配对机械闸 kind（必须在 KNOWN_GATES）
    enabled: bool = True
    disabled_reason: str = ""


SKILLS: list[GateSkill] = [
    GateSkill(
        name="calc_discipline",
        description="推导数字（比率/合计/差额）心算出错",
        rule="凡结论涉及推导数字，必须在对应证据的 note 里写显式算式："
             "「计算:a/b=c%」或「计算:a-b=c」，输入数用资料原值，禁止只给结果。",
        trigger=lambda d: _numeric_share(d) >= 0.25,
        gate="calc",
    ),
    GateSkill(
        name="number_provenance",
        description="来源外数字（行业惯例值/估计值混入）",
        rule="结论与说明中的每个数字必须出自所引段落原文，或已写明算式的"
             "计算结果；资料没有的数字一律不写，改下「资料不足」类结论。",
        trigger=lambda d: _numeric_share(d) >= 0.25,
        gate="provenance",
        enabled=False,
        disabled_reason="首轮A/B(2026-09-30,3+3):provenance黄牌中位2↔2无改善"
                        "（flash级模型未遵从建议性纪律），溯源闸本身照常运行；"
                        "改写为强制格式后重测",
    ),
    GateSkill(
        name="counting_discipline",
        description="「N 份中 M 份」类计数断言凭印象",
        rule="涉及统计资料份数的断言，必须在 note 写「计数:M/N 信源，见 "
             "SRC-…、SRC-…」并列出全部所数信源编号。",
        trigger=lambda d: len(d.sources) >= 4,
        gate="counting",
    ),
    GateSkill(
        name="hedged_claim",
        description="低可信信源的单方声称被写成已证事实",
        rule="当你的证据全部来自新闻/网页/笔记类低可信信源时，结论必须用"
             "转述语气（「报道称」「疑似」「未经官方证实」），不得写成已证事实。",
        trigger=lambda d: _lowcred_share(d) >= 0.4,
        gate="hedge",
        enabled=False,
        disabled_reason="首轮A/B主指标hedge黄牌中位3↔3与对照持平，逐条消融"
                        "(3跑)亦并列→按预注册协议停用；单条注入时冲突正常"
                        "(1/5/4)，证实组级冲突塌缩非本skill所致",
    ),
    GateSkill(
        name="table_citation",
        description="表格型信源的引文跨单元格拼接/脑补",
        rule="涉及表格的引文必须摘自同一行的连续内容并逐字含列名与数值；"
             "禁止从不同行/不同单元格拼接句子。",
        trigger=lambda d: _table_share(d) >= 0.15,
        gate="citation",
        enabled=False,
        disabled_reason="首轮A/B:引文打回率中位0.239→0.318（预注册主指标反向）；"
                        "rule需改写为可机械定位的行内摘录格式后重测",
    ),
    GateSkill(
        name="level_tone",
        description="C/D 级弱证据配断言语气",
        rule="证据仅为 C/D 级时，禁用「必然/肯定/无疑/确凿」等断言词；"
             "措辞强度必须与证据等级匹配。",
        trigger=_always,
        gate="level_tone",
    ),
    # ---- 注册未启用：等对应语料出现再按 A/B 协议开启 -------------------
    GateSkill(
        name="negation_guard",
        description="否定结构（无/未/不）在摘录或转述中被丢失/翻转",
        rule="摘录或转述含「无/未/不」的否定句时必须原样保留否定词；"
             "结论极性不得与所引原文相反。",
        trigger=lambda d: False,
        gate="citation",
        enabled=False,
        disabled_reason="等待否定结构密集的真实语料（案例语料否定句稀疏，"
                        "A/B 无统计功效）",
    ),
    GateSkill(
        name="sic_verbatim",
        description="OCR 错字被模型「好心纠正」导致引文打回（错杀好证据）",
        rule="引文逐字照抄原文（含错字）；需要勘误时写进 note 并标注"
             "「[原文如此] 正字应为 X」，不得在 quote 里无声纠正。",
        trigger=lambda d: False,
        gate="citation",
        enabled=False,
        disabled_reason="等待 OCR/扫描件语料（现有案例无错字源）",
    ),
]

# 注册表完整性自检：每条 skill 的闸声明必须落在已知闸集合里
assert all(s.gate in KNOWN_GATES for s in SKILLS)


# ---------------------------------------------------------------- 接口

import os

# 运行时总开关（A/B 对照用；pipeline 按 Settings.skills_enabled 置位。
# 对照组只关「教」——render_skills_rules 返回空——机械闸照常运行）
_SKILLS_ENABLED = True
# 逐 skill 消融白名单（VERITAS_SKILLS_ONLY=name1,name2）：非空时视为
# 实验指定的参与名单，覆盖 enabled 标志——供单条 skill 的公平重测
_ONLY = {s.strip() for s in
         (os.environ.get("VERITAS_SKILLS_ONLY") or "").split(",") if s.strip()}


def set_skills_enabled(value: bool) -> None:
    global _SKILLS_ENABLED
    _SKILLS_ENABLED = bool(value)


def skills_enabled() -> bool:
    return _SKILLS_ENABLED


def _eligible(s: GateSkill) -> bool:
    if _ONLY:
        return s.name in _ONLY  # 消融白名单覆盖 enabled 标志
    return s.enabled


def detect_skills(dossier: Dossier) -> list[GateSkill]:
    """enabled 且 trigger 命中的 skill（决定注入什么）。"""
    if not _SKILLS_ENABLED:
        return []
    return [s for s in SKILLS
            if _eligible(s) and (s.trigger is _always or s.trigger(dossier))]


def render_skills_rules(dossier: Dossier) -> str:
    """命中 skill → 系统提示词注入块（无命中返回空串）。"""
    fired = detect_skills(dossier)
    if not fired:
        return ""
    lines = ["专项纪律（下列为强制要求，违反将过不了对应的零 LLM 机械核对闸）："]
    for i, s in enumerate(fired, 1):
        lines.append(f"{i}. {s.rule}")
    return "\n" + "\n".join(lines) + "\n"


def skill_status(dossier: Dossier) -> list[dict]:
    """注册表全景（工作台/审计用）：每条 skill 的启用与命中状态。"""
    return [{
        "name": s.name,
        "description": s.description,
        "gate": s.gate,
        "enabled": _eligible(s) if _ONLY else s.enabled,
        "triggered": bool(_SKILLS_ENABLED and _eligible(s)
                          and s.trigger(dossier)),
        "disabled_reason": s.disabled_reason,
    } for s in SKILLS]
