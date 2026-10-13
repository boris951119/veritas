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
    """完整性判据台账：每条义务 → answered / gap / unanswered。

    以前切不出 ≥2 个子问就直接返回空列表——等于**开放题没有任何完整性判据**，
    模型早退也量不出来（2026-10-13 实测：34 份产物里 5 份台账为空）。
    现在按四层来源保证非空，且来源偏弱时由 `ledger_limitation` 显影成一句声明，
    绝不把「拆不出来」写成「没有要做的事」。

    synthesis 传入本轮主席汇总（含刚写入的缺口与主席声明的义务）。
    """
    subs = obligations(dossier, synthesis)
    if not subs:
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
    for item in subs:
        text = item["text"]
        if _blob_covers(answered_blob, text):
            status = "answered"
        elif _blob_covers(gap_blob, text) or _blob_covers(
                "\n".join(c.statement for c in dossier.conclusions
                          if "资料不足" in (c.statement or "")), text):
            status = "gap"
        else:
            status = "unanswered"
        out.append({"text": text, "status": status, "source": item["source"]})
    return out


# ------------------------------------------------------------ 义务来源（台账地基）

# 台账来源偏弱的那些：判据存在，但覆盖面是机械兜底来的，不能当成「审全了」
WEAK_LEDGER_SOURCES = frozenset({"theme", "whole_question"})

LEDGER_SOURCE_CN = {
    "chair": "主席声明",
    "subquestion": "议题子问",
    "theme": "议题主题词",
    "whole_question": "整题兜底",
}


def _chair_obligations(synth: dict) -> list[str]:
    """主席显式声明的义务（最高优先级）：字符串或 {"text": ...} 都收。"""
    out: list[str] = []
    for raw in (synth.get("obligations") or []):
        text = str((raw or {}).get("text") if isinstance(raw, dict) else raw).strip()
        if len(re.sub(r"\s+", "", text)) >= 4 and text not in out:
            out.append(text)
    return out


def obligations(dossier: Dossier,
                synthesis: dict | None = None) -> list[dict]:
    """台账的条目从哪来——四层来源，命中即止，保证「有议题就有判据」。

    1. `chair`：主席本轮显式声明的义务（最贴题意）；
    2. `subquestion`：按问号/分号切出的子问；
    3. `theme`：议题命中的主题组（≥2 组时按组展开，一组一条义务）；
    4. `whole_question`：整题兜底——只有 1 条义务，且必须配一句
       「本题未能机械拆解」的局限声明（见 `ledger_limitation`）。

    主席只声明 1 条、而议题本可机械切成多条时走机械切分——**不许把判据做薄**；
    主席声明 1 条、且议题根本切不开时走主席声明——题意优先于整题兜底。
    """
    synth = synthesis if synthesis is not None else (dossier.synthesis or {})
    chair = _chair_obligations(synth)
    subs = split_subquestions(dossier.question or "")
    if len(chair) >= 2 or (chair and len(subs) < 2):
        return [{"text": t, "source": "chair"} for t in chair]
    if len(subs) >= 2:
        return [{"text": t, "source": "subquestion"} for t in subs]
    themes = sorted(_themes_in(dossier.question or ""))
    if len(themes) >= 2:
        return [{"text": f"{th}（议题主题词落点）", "source": "theme"}
                for th in themes]
    q = (dossier.question or "").strip()
    if not q:
        return []
    return [{"text": q, "source": "whole_question"}]


def ledger_limitation(items: list[dict]) -> str:
    """台账来源偏弱时给一句话声明；来源可靠则返回空串。

    这条声明是**给评委看的**：完整性判据有几条、是不是机械兜底来的，
    不许含糊。「拆不出来」与「没有要拆的」是两件事。
    """
    if not items:
        return "本题未产生任何完整性判据（议题为空或无法定位），覆盖结论不可用"
    weak = [i for i in items if i.get("source") in WEAK_LEDGER_SOURCES]
    if not weak:
        return ""
    n = len(items)
    src = LEDGER_SOURCE_CN.get(weak[0].get("source"), weak[0].get("source") or "")
    return (
        f"完整性判据共 {n} 条，来源为「{src}」——本题未能按子问拆解，"
        f"「已答」只表示触及该主题词，不表示已审完全部材料"
    )
