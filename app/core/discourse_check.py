"""话语机械核对器：质证引文/引用闸 + 仲裁引用闸（零 LLM）。

协同段里归并、质证、仲裁三个环节都会对外产出文本，此前无任何机械
校验。本模块补上便宜而硬的两类口径：

- 质证引文闸：质证文本中「」/『』/"" 引号内的逐字引文必须能在本案卷
  任一来源段落中命中（复用 citation_check 归一化口径）——防「稻草人」
  （把对方没说的话安到对方头上）；
- 引用存在性闸：质证与仲裁理由中提及的证据/结论/信源/冲突 id 必须
  真实存在——防「编造依据」。

违规记黄色警示（不阻断协同——语义判定仍归 LLM 与仲裁程序，机械侧
只亮灯不留后门）。全部字符串运算，零模型调用。
"""

from __future__ import annotations

import re

from app.core.citation_check import check_quote
from app.core.evidence import Dossier

# 「…」『…』“…” 引号内 ≥6 字的逐字引文（更短的 span 误报太多不查）
_QUOTE_SPAN = re.compile(r"[「『“\"]([^「」『』“”\"]{6,})[」』”\"]")
# 结构化 id：EV-/CON-/SRC-/CFL- 前缀 + ≥4 位字母数字
_ID_TOKEN = re.compile(r"\b(EV|CON|SRC|CFL)-[0-9a-zA-Z]{4,}\b")


def _id_exists(dossier: Dossier, token: str) -> bool:
    prefix, _, _ = token.partition("-")
    if prefix == "CON":
        return dossier.conclusion(token) is not None
    if prefix == "EV":
        return dossier.evidence(token) is not None
    if prefix == "SRC":
        return any(s.id == token for s in dossier.sources)
    if prefix == "CFL":
        return any(c.get("id") == token for c in dossier.conflicts or [])
    return True  # 未知前缀不武断


def _check_refs(dossier: Dossier, text: str, kind: str,
                conclusion_id: str, conflict_id: str, side: str) -> list[dict]:
    flags = []
    for m in _ID_TOKEN.finditer(text):
        token = m.group(0)
        if not _id_exists(dossier, token):
            flags.append({
                "kind": kind, "severity": "medium",
                "conclusion_id": conclusion_id, "conflict_id": conflict_id,
                "side": side, "value": token,
                "detail": f"引用了案卷中不存在的编号 {token}",
            })
    return flags


def audit_discourse(dossier: Dossier) -> list[dict]:
    """全部已消解冲突的质证引文/引用闸 + 仲裁理由引用闸。"""
    flags: list[dict] = []
    all_segments = [seg.text for src in dossier.sources for seg in src.segments]
    for raw in dossier.conflicts or []:
        resolution = raw.get("resolution") if isinstance(raw, dict) else None
        if not resolution:
            continue
        conflict_id = str(raw.get("id") or "")
        for side, text in (resolution.get("rebuts") or {}).items():
            text = str(text or "")
            for m in _QUOTE_SPAN.finditer(text):
                quote = m.group(1)
                if not any(check_quote(quote, seg).ok for seg in all_segments):
                    flags.append({
                        "kind": "rebut_quote", "severity": "medium",
                        "conflict_id": conflict_id, "side": side,
                        "value": quote[:50],
                        "detail": f"{side}方质证中的引文「{quote[:40]}…」"
                                  "未在任何来源段落中逐字命中（疑似歪曲对方）",
                    })
            flags.extend(_check_refs(dossier, text, "rebut_ref", "",
                                     conflict_id, str(side)))
        rationale = str(resolution.get("rationale") or "")
        flags.extend(_check_refs(dossier, rationale, "arbiter_ref", "",
                                 conflict_id, "arbiter"))
    return flags


# ---------------------------------------------------------------- 措辞闸

# 转述语气词（低可信信源支撑的结论应出现其一）
_HEDGE_RE = re.compile(
    r"报道称|据报道|据悉|疑似|传闻|未经官方证实|尚未证实|有待核实|"
    "或涉|或将|可能|或因|声称|自述|尚待")
# 断言语气词（弱证据配强措辞即不匹配）
_ASSERT_RE = re.compile(
    r"必然|肯定|无疑|确凿|必将|一定|绝对|百分之百|注定")


def _supporting_sources(dossier: Dossier, conclusion_id: str) -> list:
    types = []
    for ev in dossier.evidences_of(conclusion_id):
        for sid in ev.segment_ids:
            src = dossier.source_of_segment(sid)
            if src is not None:
                types.append(src)
    return types


def audit_hedge(dossier: Dossier) -> list[dict]:
    """转述级闸：证据全部来自低可信信源（新闻/网页/笔记）且结论无
    转述语气 → 黄牌（声称≠事实，OSINT 场景的核心幻觉）。"""
    flags: list[dict] = []
    for con in dossier.conclusions:
        if con.status == "merged":
            continue
        sources = _supporting_sources(dossier, con.id)
        if not sources or not all(s.source_type.value in ("news", "web", "note")
                                  for s in sources):
            continue
        if _HEDGE_RE.search(con.statement):
            continue
        flags.append({
            "kind": "hedge", "severity": "medium",
            "conclusion_id": con.id,
            "value": con.statement[:40],
            "detail": "结论的全部证据来自低可信信源（新闻/网页/笔记），"
                      "但使用了断言语气——应转述（报道称/疑似/未经证实）",
        })
    return flags


def audit_level_tone(dossier: Dossier) -> list[dict]:
    """措辞-等级闸：证据仅为 C/D 级却用断言词 → 黄牌。"""
    flags: list[dict] = []
    for con in dossier.conclusions:
        if con.status == "merged":
            continue
        evs = dossier.evidences_of(con.id)
        if not evs or not all(e.level.value in ("C", "D") for e in evs):
            continue
        m = _ASSERT_RE.search(con.statement)
        if not m:
            continue
        flags.append({
            "kind": "level_tone", "severity": "medium",
            "conclusion_id": con.id,
            "value": m.group(0),
            "detail": f"结论证据仅为 C/D 级，却使用断言词「{m.group(0)}」"
                      "——措辞强度应与证据等级匹配",
        })
    return flags
