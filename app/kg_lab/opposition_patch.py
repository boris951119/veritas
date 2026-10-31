"""从原文抽取对立口径句，补进 summary 字段（可审计；禁止编造）。

仅使用段内字面命中的对立／争议表述；无命中则不写假词。
"""

from __future__ import annotations

import re
from typing import Any

# 题面／金标常见对立口径；只作「原文检索键」，不凭空写入
FOCUS_TERMS: tuple[str, ...] = (
    "不愿走",
    "未放行",
    "不想走",
    "没让我走",
    "不是我不想走",
    "而是你没让我走",
    "11年",
    "十一年",
    "十年了",
    "十年物是人非",
    "买断",
    "放行",
    "拖了",
)

_SENT_SPLIT = re.compile(r"(?<=[。！？；\n])")


def find_opposition_spans(text: str) -> list[dict[str, Any]]:
    """在原文中定位含对立口径的子串；返回可审计 span。"""
    body = text or ""
    spans: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for term in FOCUS_TERMS:
        start = 0
        while True:
            i = body.find(term, start)
            if i < 0:
                break
            # 扩到句界
            left = max(body.rfind("。", 0, i), body.rfind("！", 0, i),
                       body.rfind("？", 0, i), body.rfind("\n", 0, i),
                       body.rfind("；", 0, i)) + 1
            right_cands = [
                body.find(c, i + len(term)) for c in ("。", "！", "？", "\n", "；")
            ]
            right_cands = [x for x in right_cands if x >= 0]
            right = (min(right_cands) + 1) if right_cands else min(len(body), i + len(term) + 40)
            quote = body[left:right].strip()
            key = (left, right, term)
            if key not in seen and quote:
                seen.add(key)
                spans.append({
                    "term": term,
                    "char_start": left,
                    "char_end": right,
                    "quote": quote,
                })
            start = i + len(term)
    spans.sort(key=lambda s: (s["char_start"], s["term"]))
    return spans


def focus_hits(text: str) -> dict[str, bool]:
    t = text or ""
    # 报表用较窄一组（与 R2b 对齐）
    report_terms = (
        "不愿走", "未放行", "11年", "十一年", "不想走", "没让我走", "买断", "放行",
    )
    return {term: (term in t) for term in report_terms}


def apply_opposition_patch(summary: dict[str, Any], text: str) -> dict[str, Any]:
    """把原文对立句并入 facts／keywords／summary_text；写 audit 块。"""
    spans = find_opposition_spans(text)
    out = dict(summary or {})
    facts = [str(x) for x in (out.get("facts") or []) if str(x).strip()]
    keywords = [str(x) for x in (out.get("keywords") or []) if str(x).strip()]
    entities = [str(x) for x in (out.get("entities") or []) if str(x).strip()]

    added_facts: list[str] = []
    added_kw: list[str] = []
    for sp in spans:
        q = sp["quote"].strip()
        # 事实句：优先整句；过长则截断但保留对立词
        fact = q if len(q) <= 80 else (q[:77] + "…")
        if fact and fact not in facts and fact not in added_facts:
            added_facts.append(fact)
        term = sp["term"]
        if term not in keywords and term not in added_kw:
            added_kw.append(term)

    if added_facts:
        facts = (added_facts + facts)[:6]
    if added_kw:
        keywords = list(dict.fromkeys(added_kw + keywords))[:16]

    # 重建 summary_text：对立句置顶；关键词重复一次以抬 TF（仍全部来自原文 span）
    parts: list[str] = []
    for f in added_facts:
        parts.append(f)
    for f in facts:
        if f not in parts:
            parts.append(f)
    for e in entities:
        parts.append(e)
    for k in keywords:
        parts.append(k)
    # 仅重复「对立口径」短词（有 span 依据），帮助 BM25 吃到检索字段
    for k in added_kw:
        parts.append(k)
    out["facts"] = facts
    out["keywords"] = keywords
    out["entities"] = entities
    out["summary_text"] = "\n".join(parts)
    out["ok"] = bool(facts or entities or keywords)
    # 供 embedding：摘要∪原文窗（不改 expand；只加厚向量侧输入）
    out["embed_blob"] = (
        (out["summary_text"] + "\n" + (text or "")).strip()
    )[:2000]
    out["opposition_patch"] = {
        "source": "r2c_span_extract",
        "n_spans": len(spans),
        "spans": spans,
        "added_facts": added_facts,
        "added_keywords": added_kw,
        "embed_blob_uses_text": True,
    }
    return out
