"""议题预检（零 LLM）：表述质量分级 + 机械回读 + 澄清建议。

自然语言议题可能清晰也可能模糊。本模块回答「这个问题本身问得好不好」
——此前太宽/复合/指代不明的问题会静默走完全程，用户不知道是资料不行
还是问题不行。五级分类（判定全机械）：

- clear     有实质对象实体，无未消解指代
- ambiguous 含指代词（他/这个/该/其…）——机械无法消解所指
- compound  多问句或多主题连接（回款、交付和风险分别怎么样）
- vague     无实质对象实体（分析一下这个行业）——含通用词补充表
- empty     过短/无实义字符

处置原则（承讨论定稿）：
- **不改写问题**（改写=替用户决定问什么），做**机械回读**——把系统
  抽到的研判要素（对象/时点）摆出来让用户纠偏，问题定义权在用户；
- 澄清走**协议**不走无限反问：MCP 返回 needs_clarification 由调用方
  智能体去问它的用户，至多 2 轮，问不透以最佳解读继续+歧义显式披露
  （主席层 kind=question 条目原文照录）；
- 批处理形态输出澄清建议文本，改 manifest 重跑=新研判（链上留议题
  演化史）；
- 语义歧义（一词多义）机械不可判——由多视角解读分歧→冲突消解显式化，
  不是预检的职责。
"""

from __future__ import annotations

import re

from app.core.premise_check import _GENERIC, extract_entities

_PRONOUN_RE = re.compile(r"他|她|它|这个|那个|这些|那些|此处|该")
# 议题侧通用词补充（比 premise_check 的 _GENERIC 更宽：问题里的
# 「行业/市场」是范畴词不是对象）
_QUESTION_GENERIC = {
    "行业", "市场", "领域", "方向", "各方面", "整体情况", "整体",
    "本次", "该项目", "该方案",
}
# 问句功能词（extract_entities 切块常粘着它们，先剥再判实质）
_FUNCTION_TOKENS = (list(_GENERIC) + list(_QUESTION_GENERIC)
                    + ["做个", "一下", "多少", "是什么", "是多少", "怎么样",
                       "如何", "能不能", "会不会", "请", "帮忙", "大概"])
_TAIL_PARTICLES = "吧吗呢了的啊"


def _substantive_entities(question: str) -> list[str]:
    """抽出的实体块 → 剥范畴词/问句功能词后的实质对象清单。

    「行业整体情况做个」剥完为空=无实质对象；「回款率是多少」剥完
    剩「回款率」=实质。返回清洗后的去重保序列表。"""
    out: list[str] = []
    for e in extract_entities(question):
        chunk = e
        changed = True
        while changed:
            changed = False
            for token in _FUNCTION_TOKENS:
                if token and token in chunk:
                    chunk = chunk.replace(token, "")
                    changed = True
        chunk = chunk.strip(_TAIL_PARTICLES)
        if len(chunk) >= 2 and (any("\u4e00" <= c <= "\u9fff" for c in chunk)
                                or any(c.isascii() and c.isalnum()
                                       for c in chunk)):
            if chunk not in out:
                out.append(chunk)
    return out
_TOPIC_CONNECTORS = ["和", "以及", "还有", "同时", "另外", "再加",
                     "顺便", "其次", "分别"]
_TIER_CN = {"clear": "清晰", "vague": "宽泛", "compound": "复合",
            "ambiguous": "指代含糊", "empty": "空洞"}

_CLARIFY = {
    "vague": ["请明确分析对象（如：客户B／某项目）与关注指标"
              "（如：回款率／交付进度）"],
    "compound": ["议题含多个子问题：建议拆分为单议题分别研判，"
                 "或指明优先关注项"],
    "ambiguous": ["议题含指代词（他／这个／该…）：请把所指对象写出全称"],
    "empty": ["议题为空或过短：请给出完整的研判问题"],
}


def question_preflight(question: str) -> dict:
    """议题体检 → {tier, tier_cn, entities, dates, readback, clarify,
    signals}。确定性：同问题同结果。"""
    q = (question or "").strip()
    entities = _substantive_entities(q)
    dates = re.findall(r"(?:19|20)\d{2}\s*年(?:\d{1,2}\s*月)?"
                       r"|\d{4}[-/.]\d{1,2}", q)
    n_qmarks = q.count("？") + q.count("?")
    n_conn = (sum(q.count(c) for c in "、，,;；")
              + sum(q.count(w) for w in _TOPIC_CONNECTORS))
    pron = _PRONOUN_RE.search(q)
    signals: list[str] = []

    if len(q) < 4 or not re.search(r"[\u4e00-\u9fffA-Za-z]", q):
        tier = "empty"
        signals.append("议题过短或无实义内容")
    elif pron:
        tier = "ambiguous"
        signals.append(f"含指代词「{pron.group(0)}」，所指对象机械不可消解")
    elif n_qmarks >= 2 or (n_conn >= 2 and len(entities) >= 2):
        tier = "compound"
        signals.append(f"多问句({n_qmarks})或主题连接词过多({n_conn})")
    elif not entities:
        tier = "vague"
        signals.append("未抽出实质对象实体（仅范畴/框架词）")
    else:
        tier = "clear"
        signals.append(f"对象实体 {'、'.join(entities[:4])}"
                       + (f"，时点 {dates[0]}" if dates else ""))

    readback = {"原文": q, "对象": entities[:4], "时点": dates[:2]}
    return {
        "tier": tier, "tier_cn": _TIER_CN[tier],
        "entities": entities, "dates": dates, "readback": readback,
        "clarify": _CLARIFY.get(tier, []), "signals": signals,
    }


def question_flag(question: str) -> dict | None:
    """非清晰议题 → 黄牌（进 audit_all 与报告警示）。"""
    pf = question_preflight(question)
    if pf["tier"] == "clear":
        return None
    return {
        "kind": "question", "severity": "medium",
        "value": pf["tier_cn"],
        "detail": f"议题表述{pf['tier_cn']}（{'；'.join(pf['signals'])}）——"
                  "结论按资料视角分别给出；澄清建议见议题体检章节",
    }


def readback_line(question: str) -> str:
    """机械回读（二次确认语义）：系统抽到的要素摆给用户，问题定义权
    在用户——不改写、只确认。"""
    pf = question_preflight(question)
    rb = pf["readback"]
    parts = [f"对象：{('、'.join(rb['对象']) or '（未识别）')}"]
    if rb["时点"]:
        parts.append(f"时点：{'、'.join(rb['时点'])}")
    return f"研判议题确认——{ '；'.join(parts) }；原文照录：「{rb['原文']}」"
