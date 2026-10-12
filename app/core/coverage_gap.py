"""覆盖诚实：含议题关键词却未被引用的段落；复合子问三态。"""

from __future__ import annotations

import re

from app.core.evidence import Dossier
from app.core.warrant_check import _THEME_GROUPS, _themes_in

_MAX_UNUSED = 8
_SNIP = 40


def _cited_segment_ids(dossier: Dossier) -> set[str]:
    out: set[str] = set()
    for ev in dossier.evidences:
        out.update(ev.segment_ids)
    return out


def _question_themes(question: str) -> set[str]:
    return _themes_in(question or "")


def unused_topic_segments(dossier: Dossier, *, limit: int = _MAX_UNUSED
                          ) -> list[dict]:
    """材料内命中议题主题词、密度靠前、却无任何结论引用的段落。"""
    themes = _question_themes(dossier.question)
    if not themes:
        return []
    cited = _cited_segment_ids(dossier)
    scored: list[tuple[int, dict]] = []
    for src in dossier.sources:
        for seg in src.segments:
            if seg.id in cited:
                continue
            text = seg.text or ""
            seg_themes = _themes_in(text)
            overlap = themes & seg_themes
            if not overlap:
                continue
            # 密度：命中主题词出现次数
            dens = 0
            for g in _THEME_GROUPS:
                if g[0] not in overlap:
                    continue
                dens += sum(text.count(t) for t in g)
            snip = re.sub(r"\s+", " ", text).strip()
            if len(snip) > _SNIP:
                snip = snip[: _SNIP - 1] + "…"
            scored.append((dens, {
                "segment_id": seg.id,
                "source_id": src.id,
                "themes": sorted(overlap),
                "density": dens,
                "snip": snip,
            }))
    scored.sort(key=lambda x: (-x[0], x[1]["segment_id"]))
    return [item for _, item in scored[:limit]]


def unused_topic_note(items: list[dict]) -> str:
    if not items:
        return ""
    bits = [f"{it['segment_id']}「{it['snip']}」" for it in items[:5]]
    return (
        "这些段落含议题关键词但未被使用（"
        + "；".join(bits)
        + ("…" if len(items) > 5 else "")
        + "）"
    )


_SUBQ_SPLIT = re.compile(r"[？?]|；|;")


def split_subquestions(question: str) -> list[str]:
    """把复合议题切成子问（保留问号语义）。"""
    q = (question or "").strip()
    if not q:
        return []
    # 按问号/分号切，再拼回问号
    parts: list[str] = []
    buf = ""
    for ch in q:
        buf += ch
        if ch in "？?；;":
            piece = buf.strip().strip("；;").strip()
            if piece:
                parts.append(piece)
            buf = ""
    tail = buf.strip()
    if tail:
        parts.append(tail)
    # 过滤过短碎片
    return [p for p in parts if len(re.sub(r"\s+", "", p)) >= 6]


_SUBQ_STOP = ("是否", "如何", "什么", "怎么样", "厂商", "技术", "方案")


def _content_grams(subq: str) -> list[str]:
    """无主题词的子问：滑动 4/3 字，避开停用碎片。"""
    s = "".join(re.findall(r"[\u4e00-\u9fff]", subq or ""))
    grams: list[str] = []
    for n in (4, 3):
        for i in range(0, max(0, len(s) - n + 1)):
            g = s[i:i + n]
            if "的" in g or any(w in g for w in _SUBQ_STOP):
                continue
            if g not in grams:
                grams.append(g)
    return grams


def _blob_covers(text: str, subq: str) -> bool:
    """子问主题词或区分性字串是否出现在结论/缺口文本里。"""
    themes = _themes_in(subq)
    if themes:
        return bool(themes & _themes_in(text))
    return any(g in (text or "") for g in _content_grams(subq))


def subquestion_status(dossier: Dossier,
                       synthesis: dict | None = None) -> list[dict]:
    """每个子问 → answered / gap / unanswered。

    synthesis 传入本轮主席汇总（含刚写入的缺口）。缺省才读案卷上的旧汇总。
    """
    subs = split_subquestions(dossier.question)
    if len(subs) < 2:
        return []
    answered_blob = "\n".join(
        c.statement for c in dossier.conclusions if c.statement)
    gap_blob = ""
    synth = synthesis if synthesis is not None else (dossier.synthesis or {})
    for o in synth.get("open_issues") or []:
        if o.get("kind") in ("gap", "note", "question"):
            gap_blob += "\n" + str(o.get("text") or "")
    # 前提黄灯也算缺口信号
    from app.core.premise_check import premise_flags
    for f in premise_flags(dossier):
        gap_blob += "\n" + str(f.get("detail") or "")

    out: list[dict] = []
    for sub in subs:
        if _blob_covers(answered_blob, sub):
            status = "answered"
        elif _blob_covers(gap_blob, sub) or _blob_covers(
                "\n".join(c.statement for c in dossier.conclusions
                          if "资料不足" in (c.statement or "")), sub):
            status = "gap"
        else:
            status = "unanswered"
        out.append({"text": sub, "status": status})
    return out
