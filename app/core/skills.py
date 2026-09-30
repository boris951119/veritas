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

# 配对闸的合法 kind（闸本体在 numeric_check / discourse_check / citation_check /
# temporal_check / question_check）
KNOWN_GATES = {
    "citation", "calc", "provenance", "counting",
    "hedge", "level_tone", "as_of", "question",
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
    """一条提示词纪律：trigger 命中时按模型档位注入对应版本。

    - rule      建议版：compliant 档注入（探测显示模型会遵从）；
    - rule_hard 强化版：noncompliant 档注入——祈使句 + 结构化 derived
      字段 + 告知会被机械闸打回；**停用的 skill 只是停了建议版**，
      其强化版随 noncompliant 档参与注入（配对闸不变）。
    """

    name: str
    description: str            # 防什么幻觉（答辩/审计口径）
    rule: str                   # 注入文本（≤3 行，强制语气）
    trigger: Callable[[Dossier], bool]
    gate: str                   # 配对机械闸 kind（必须在 KNOWN_GATES）
    enabled: bool = True
    disabled_reason: str = ""
    rule_hard: str = ""         # 强化版；空则沿用 rule

    def text_for(self, tier: str) -> str:
        if tier == "noncompliant" and self.rule_hard:
            return self.rule_hard
        return self.rule


SKILLS: list[GateSkill] = [
    GateSkill(
        name="calc_discipline",
        description="推导数字（比率/合计/差额）心算出错",
        rule="凡结论涉及推导数字，必须在对应证据的 note 里写显式算式："
             "「计算:a/b=c%」或「计算:a-b=c」，输入数用资料原值，禁止只给结果。",
        trigger=lambda d: _numeric_share(d) >= 0.25,
        gate="calc",
        rule_hard="每个含推导数字的结论都必须写 derived 数组，formula 用"
                  "资料原值写完整算式；漏写、缺输入或算错，程序复算后该结论"
                  "整条打回。",
    ),
    GateSkill(
        name="number_provenance",
        description="来源外数字（行业惯例值/估计值混入）",
        rule="结论与说明中的每个数字必须出自所引段落原文，或已写明算式的"
             "计算结果；资料没有的数字一律不写，改下「资料不足」类结论。",
        trigger=lambda d: _numeric_share(d) >= 0.25,
        gate="provenance",
        rule_hard="结论与 note 里出现的每一个数字，都必须能在所引段落原文中"
                  "逐字找到，或是 derived 数组里已写算式的结果；找不到的数字"
                  "程序会检出并打回——写不出出处的数字直接删掉，改下「资料不足」。",
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
        rule_hard="统计资料份数的断言必须在 note 写「计数:M/N 信源，见 SRC-x、"
                  "SRC-y」并逐个列出所数信源编号；编号不存在或数目对不上，"
                  "程序会检出并打回。",
    ),
    GateSkill(
        name="hedged_claim",
        description="低可信信源的单方声称被写成已证事实",
        rule="当你的证据全部来自新闻/网页/笔记类低可信信源时，结论必须用"
             "转述语气（「报道称」「疑似」「未经官方证实」），不得写成已证事实。",
        trigger=lambda d: _lowcred_share(d) >= 0.4,
        gate="hedge",
        rule_hard="你的证据全部来自新闻/网页/笔记类低可信信源时，statement 必须"
                  "含转述标记（「报道称」「疑似」「未经官方证实」任一），否则"
                  "程序会以「声称当事实」打回；禁止把单方声称写成已证事实。",
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
        rule_hard="表格引文必须摘自同一行的连续内容并逐字含列名与数值；"
                  "跨行/跨单元格拼接的引文程序逐字核对必然不命中，整条打回。",
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
        rule_hard="证据等级为 C/D 时，statement 里禁止出现「必然/肯定/无疑/"
                  "确凿/必将/一定」等断言词，程序逐词扫描，命中即打回；"
                  "把断言改成「可能/或/待证」。",
    ),
    GateSkill(
        name="as_of_discipline",
        description="时序冲突：旧状态被写成当前事实（快照当永恒）",
        rule="涉及状态/数值的结论必须锚定时点（「截至2025年报」「2026年3月"
             "进展」）；资料含多时点版本时，引用最新时点或明示变化。",
        trigger=lambda d: any(s.meta.get("published_at") or s.meta.get("year")
                              for s in d.sources),
        gate="as_of",
        rule_hard="涉及状态/数值的结论必须含时点词（如「截至2025年报」「2026年"
                  "3月」）；程序核对所引信源时点与结论时点词，缺锚即打回。",
    ),
    GateSkill(
        name="question_focus",
        description="宽泛议题下给出笼统总体判断（各主题混为一谈）",
        rule="本议题表述宽泛：按主题分维度组织结论，每条结论聚焦单一主题"
             "并各自挂证据；不要给缺乏单一证据锚点的笼统总体判断。",
        trigger=lambda d: _question_tier(d) == "vague",
        gate="question",
    ),
    GateSkill(
        name="question_scoped",
        description="复合议题的子问题被揉在一起回答",
        rule="本议题含多个子问题：逐子问题作答，statement 开头标注所属"
             "子题（如「回款方面：…」「交付方面：…」）。",
        trigger=lambda d: _question_tier(d) == "compound",
        gate="question",
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

def _question_tier(dossier: Dossier) -> str:
    from app.core.question_check import question_preflight

    return question_preflight(dossier.question)["tier"]


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


def _eligible(s: GateSkill, tier: str) -> bool:
    if _ONLY:
        return s.name in _ONLY  # 消融白名单覆盖 enabled 标志
    if tier == "noncompliant":
        return True  # 强化档：全部纪律按 rule_hard 参与触发判定
    return s.enabled


def detect_skills(dossier: Dossier, tier: str = "standard") -> list[GateSkill]:
    """按模型档位返回 trigger 命中的 skill（决定注入什么）。"""
    if not _SKILLS_ENABLED:
        return []
    return [s for s in SKILLS
            if _eligible(s, tier) and (s.trigger is _always or s.trigger(dossier))]


def render_skills_rules(dossier: Dossier, tier: str = "standard") -> str:
    """命中 skill → 系统提示词注入块（无命中返回空串）。

    noncompliant 档额外携带结构化 derived 字段契约——把「写算式」从
    劝说变成输出 schema 的一部分，物化器再机械归一进 note。"""
    fired = detect_skills(dossier, tier)
    if not fired:
        return ""
    if tier == "noncompliant":
        lines = ["输出契约（本任务的输出将被零 LLM 机械闸逐条复核，"
                 "不合规的结论会被程序打回并要求重写，请严格执行）："]
        lines += [f"{i}. {s.text_for(tier)}" for i, s in enumerate(fired, 1)]
        lines.append(
            "凡结论含推导数字（占比/合计/差额），该结论必须附加 derived 数组："
            '"derived": [{"value": "40%", "formula": "512/1280=40%"}]，'
            "formula 用资料原值写完整算式，禁止只给结果。")
        return "\n" + "\n".join(lines) + "\n"
    lines = ["专项纪律（下列为强制要求，违反将过不了对应的零 LLM 机械核对闸）："]
    lines += [f"{i}. {s.text_for(tier)}" for i, s in enumerate(fired, 1)]
    return "\n" + "\n".join(lines) + "\n"


def skill_status(dossier: Dossier, tier: str = "standard") -> list[dict]:
    """注册表全景（工作台/审计用）：每条 skill 的启用与命中状态。"""
    return [{
        "name": s.name,
        "description": s.description,
        "gate": s.gate,
        "enabled": _eligible(s, tier) if _ONLY else s.enabled,
        "triggered": bool(_SKILLS_ENABLED and _eligible(s, tier)
                          and s.trigger(dossier)),
        "disabled_reason": s.disabled_reason,
    } for s in SKILLS]
