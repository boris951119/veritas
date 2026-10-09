"""零 LLM 引文核对器（token-burner acceptance_judge 思想平移）。

「可信」的机械抓手：每条证据的逐字引文必须在其所指来源段落中命中，
不合格证据打回——判定全程字符串运算，零模型调用、秒级、可复现。

命中口径：
- 归一化（NFC + 去除全部空白/全角空格 + Markdown 记号剔除 + 全半角
  标点统一）后子串匹配——只宽容排版差异，内容一字不改仍须逐字命中；
- 引文含省略号（……/.../。。。）时按省略段切分，各段须按原顺序
  依次命中（支持跨段摘录的省略式引文）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.core.evidence import Dossier, EvidenceNode

_ELLIPSIS = re.compile(r"(\.{3,}|…+|。{2,})")
_MD_MARKS = re.compile(r"[*_`#~]|<br\s*/?>", re.IGNORECASE)
_FULLWIDTH = str.maketrans({
    "：": ":", "，": ",", "；": ";", "！": "!", "？": "?",
    "（": "(", "）": ")", "［": "[", "］": "]", "．": ".",
})


def normalize(text: str) -> str:
    """引文比对归一化：NFC + 去空白 + 去 Markdown 记号 + 全半角标点统一。"""
    collapsed = unicodedata.normalize("NFC", text)
    collapsed = "".join(collapsed.split()).translate(_FULLWIDTH)
    return _MD_MARKS.sub("", collapsed)


@dataclass
class QuoteCheck:
    ok: bool
    reason: str = ""


def check_quote(quote: str, segment_text: str) -> QuoteCheck:
    """单条引文对单个段落文本的机械核对。"""
    q = normalize(quote)
    if not q:
        return QuoteCheck(False, "空引文")
    t = normalize(segment_text)
    parts = [p for p in _ELLIPSIS.split(q) if p and not _ELLIPSIS.fullmatch(p)]
    if not parts:
        return QuoteCheck(False, "引文仅含省略号")
    cursor = 0
    for part in parts:
        hit = t.find(part, cursor)
        if hit < 0:
            return QuoteCheck(False, "引文未在来源段落中逐字命中")
        cursor = hit + len(part)
    return QuoteCheck(True)


def check_evidence(ev: EvidenceNode, dossier: Dossier) -> list[str]:
    """单条证据的全部机械校验，返回问题清单（空 = 通过）。

    命中窗口：所指段本身；同信源相邻段拼接（表行跨段时数字与标签
    可能分落两段——拼接后再比，避免误杀已核数字）。
    """
    if not normalize(ev.quote):
        return ["空引文"]
    problems: list[str] = []
    if not ev.segment_ids:
        problems.append("证据未指明来源段落")
        return problems
    texts = []
    for sid in ev.segment_ids:
        seg = dossier.segment(sid)
        if seg is None:
            problems.append(f"来源段落不存在: {sid}")
        else:
            texts.append(seg.text)
            texts.extend(_adjacent_texts(dossier, sid))
    if not texts and problems:
        return problems
    if not texts:
        return problems
    if not any(check_quote(ev.quote, t).ok for t in texts):
        problems.append(f"引文未命中任何所指段落（{','.join(ev.segment_ids)}）")
    return problems


def _adjacent_texts(dossier: Dossier, segment_id: str) -> list[str]:
    """同信源上一段/下一段，及与当前段的正反拼接。"""
    src = dossier.source_of_segment(segment_id)
    if src is None:
        return []
    segs = src.segments
    idx = next((i for i, s in enumerate(segs) if s.id == segment_id), -1)
    if idx < 0:
        return []
    out: list[str] = []
    cur = segs[idx].text
    if idx > 0:
        prev = segs[idx - 1].text
        out.extend([prev, prev + "\n" + cur, cur + "\n" + prev])
    if idx + 1 < len(segs):
        nxt = segs[idx + 1].text
        out.extend([nxt, cur + "\n" + nxt, nxt + "\n" + cur])
    return out


@dataclass
class CitationFailure:
    evidence_id: str
    conclusion_id: str
    problems: list[str]


def audit_dossier(dossier: Dossier) -> list[CitationFailure]:
    """全案卷引文审计：不合格证据汇总（id 以 EV- 开头，供修复环消费）。"""
    failures: list[CitationFailure] = []
    for ev in dossier.evidences:
        problems = check_evidence(ev, dossier)
        ev.verified = not problems
        if problems:
            failures.append(CitationFailure(ev.id, ev.conclusion_id, problems))
    return failures
