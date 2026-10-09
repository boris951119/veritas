"""议题前提核对器（零 LLM）：问题中的实体在信源零命中时前置亮灯。

「为什么客户B拖欠回款？」——前提「客户B拖欠」若在任何信源中都找不到，
模型顺着框架作答就是在编确认理由。本模块在研判开始前机械核对：从
议题里抽实体候选项（字母数字词 + 中文实义词），任一在全部段落中零
命中即记黄色警示——提示分析师与读者「该前提未被资料覆盖」，回答
须先核前提。纯字符串运算，宁漏勿误（只对高置信零命中最警）。
"""

from __future__ import annotations

import re

from app.core.citation_check import normalize
from app.core.evidence import Dossier

# 框架词：把议题长句切成实体候选的分隔符（疑问/连接/助词/分析动词）
_FRAME = re.compile(
    r"的|了|吗|呢|吧|是否|如何|为什么|怎么|什么样|什么|哪些|哪个|哪家|"
    "请|和|与|及|或|对|对于|关于|在|有|无|将|把|被|给|向|从|其|之|该|各|"
    "并|会不会|能不能|是不是|还有|以及|存在|出现|进行|"
    "年前|能否|之后|以后|何时|"
    "分析|评估|研判|总结|概述|判断|说明|给出|列出")
# 纯分析框架词与泛指后缀名词，本身不是实体，不参与核对
_GENERIC = {
    "风险", "问题", "情况", "影响", "原因",
    "现状", "进展", "趋势", "背景", "结论", "证据",
    "资料", "材料", "文档", "报告", "公司",
    "整体", "主要", "当前", "未来", "过去", "时间", "数据", "信息",
    "内容", "方面", "是否", "如何", "为什么", "什么", "哪些", "请",
    "第一大股东", "大股东", "股东", "持股", "持股比例", "持股数量",
    "截至", "期末", "报告期末", "半年度报告期末", "报告期",
    "年半年度报告期末", "半年度报告", "年度报告", "年报", "半年报",
}
# 以框架名词收尾的复合词（“交付风险”“回款情况”）不是实体
_GENERIC_SUFFIX = ("风险", "情况", "问题", "影响", "原因", "趋势",
                   "进展", "现状", "背景")
# 问句尾巴：实体候选上粘着的「是谁/是多少」不是专有名
_QUESTION_TAIL = re.compile(
    r"(是谁|是什么|是多少|有多少|怎么样|如何|为何|为什么)$")

_MAX_FLAGS = 5


def extract_entities(question: str) -> list[str]:
    """议题 → 实体候选清单（字母数字词 ≥2 字；中文实义词 2-8 字）。"""
    candidates: list[str] = []
    for latin in re.findall(r"[A-Za-z][A-Za-z0-9\-]+", question):
        candidates.append(latin)
    for run in re.findall(r"[\u4e00-\u9fff]+", question):
        for frag in _FRAME.split(run):
            frag = _QUESTION_TAIL.sub("", frag.strip())
            if not (2 <= len(frag) <= 8) or frag in _GENERIC:
                continue
            if frag.endswith(_GENERIC_SUFFIX):
                continue
            candidates.append(frag)
    # 去重保序
    seen: set[str] = set()
    return [c for c in candidates
            if not (c in seen or seen.add(c))]


def _covered(token: str, corpus: str) -> bool:
    """实体是否被语料覆盖：外文词整串命中；中文词按二元 shingle
    覆盖率判定（≥60%）——「乘用车上规模量产」拆开都在即算覆盖，
    「新荣集团」整词缺席才会亮灯。"""
    if any(c.isascii() for c in token):
        return token.lower() in corpus.lower()
    shingles = [token[i:i + 2] for i in range(len(token) - 1)]
    hits = sum(1 for sh in shingles if sh in corpus)
    return hits / len(shingles) >= 0.6


def premise_flags(dossier: Dossier) -> list[dict]:
    """议题实体 × 全部信源段落命中核对；零命中 → 黄色警示。"""
    corpus = normalize("".join(
        seg.text for src in dossier.sources for seg in src.segments))
    if not corpus:
        return []
    flags: list[dict] = []
    for token in extract_entities(dossier.question):
        if _covered(token, corpus):
            continue
        flags.append({
            "kind": "premise", "severity": "medium",
            "value": token,
            "detail": f"议题中的「{token}」在全部信源中零命中"
                      "——该前提未被资料覆盖，相关回答须先核前提",
        })
        if len(flags) >= _MAX_FLAGS:
            break
    return flags
