"""摘要槽位（R4）：段内有据才写角色／对立口径／数额属性／手续日期。

facts 仍 ≤3。槽位由规则抽取（可审计），模型只负责压缩事实句；
模型槽位若与原文对不上，以规则为准。不把通稿背景和赛绩灌进索引。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.citation_check import normalize
from app.kg_lab.source_role import infer_source_role
from app.kg_lab.summarize import summary_blob

SLOT_VERSION = "r4-v1"

_ROLE_ZH = {
    "official_primary": "官方",
    "institution_def": "制度",
    "party_claim": "当事人",
    "media_relay": "转述",
    "commentary": "评论",
}

# 对立口径：只收录段内实际出现的表面词
_OPPOSITION_SURFACES: tuple[str, ...] = (
    "买断费",
    "买断",
    "经济补偿金",
    "经济补偿",
    "补偿金",
    "自主择业",
    "组织安置",
    "不是我不想走",
    "没让我走",
    "不想走",
    "不愿走",
    "未放行",
)

_AMOUNT = re.compile(r"\d+(?:\.\d+)?\s*万|\d{5,}\s*元")
# 「未公开」单独出现常指办事未声张，不是数额未确认，故不收
_UNCONFIRMED = ("尚未公开", "未确认", "没有公布", "未披露", "明细标准尚未", "核算依据尚未")
_DATE = re.compile(r"(?:\d{4}年)?\d{1,2}月\d{1,2}日")


def extract_slots(title: str, text: str) -> dict[str, Any]:
    """只从本段字面抽取。没有证据的槽留空，不补对立面、不补金额。"""
    body = text or ""
    info = infer_source_role(title or "", body, None)
    role = info["role"]
    role_zh = _ROLE_ZH.get(role, "")

    opp: list[str] = []
    for term in _OPPOSITION_SURFACES:
        if term in body and term not in opp:
            # 「买断」被「买断费」包含时只留更长的
            if term == "买断" and "买断费" in opp:
                continue
            if term == "经济补偿" and ("经济补偿金" in opp):
                continue
            if term == "补偿金" and "经济补偿金" in opp:
                continue
            opp.append(term)
    if "买断费" in opp and "买断" in opp:
        opp = [t for t in opp if t != "买断"]

    amount_status = "none"
    amount_note = ""
    has_money = bool(_AMOUNT.search(body)) or ("49.4" in body)
    unconfirmed = any(s in body for s in _UNCONFIRMED)
    established = "按规定给予" in body and ("补偿" in body or "经济补偿" in body)
    if unconfirmed and (has_money or "买断" in body or "补偿" in body):
        amount_status = "officially_unconfirmed"
        amount_note = "段内写明数额或明细尚未公开"
    elif has_money and role == "official_primary" and established:
        amount_status = "established"
        amount_note = "官方既定并写出数额"
    elif has_money:
        amount_status = "disclosed"
        amount_note = "段内披露了数额"
    elif established:
        amount_status = "established"
        amount_note = "官方写明已给经济补偿，段内无具体数额"

    dates: list[str] = []
    for m in _DATE.finditer(body):
        window = body[m.start(): m.start() + 36]
        label = m.group()
        if "申请" in window:
            label += "递交申请"
        elif any(s in window for s in ("手续", "办结", "办理完结")):
            label += "手续"
        elif "捐" in window:
            label += "捐赠"
        if label not in dates:
            dates.append(label)
        if len(dates) >= 3:
            break

    # 角色只在段内有标记时写入索引行，避免每段都灌「评论」
    write_role = role != "commentary" or any(
        s in ((title or "") + body) for s in ("评论", "热评", "网友", "舆论")
    )
    return {
        "source_role": role_zh if write_role else "",
        "source_role_id": role,
        "opposition_terms": opp[:6],
        "amount_status": amount_status,
        "amount_note": amount_note if amount_status != "none" else "",
        "procedure_dates": dates,
        "slot_version": SLOT_VERSION,
    }


def slot_line(slots: dict[str, Any]) -> str:
    """一行检索字段。空槽不写。"""
    bits: list[str] = []
    role = str(slots.get("source_role") or "").strip()
    if role:
        bits.append(f"角色:{role}")
    opp = [str(x) for x in (slots.get("opposition_terms") or []) if str(x).strip()]
    if opp:
        bits.append("口径:" + "/".join(opp[:4]))
    status = str(slots.get("amount_status") or "none")
    status_zh = {
        "disclosed": "披露",
        "established": "既定",
        "officially_unconfirmed": "官方未确认",
    }.get(status)
    if status_zh:
        bits.append(f"数额:{status_zh}")
    dates = [str(x) for x in (slots.get("procedure_dates") or []) if str(x).strip()]
    if dates:
        bits.append("时间:" + ";".join(dates[:3]))
    return " ".join(bits)


def with_slot_text(summary: dict[str, Any]) -> str:
    base = summary_blob(summary)
    line = slot_line(summary)
    if not line:
        return base
    return (base + "\n" + line).strip() if base else line


def slots_from_llm(parsed: dict[str, Any], text: str) -> dict[str, Any]:
    """模型槽位只作提示；最终以规则抽取为准（防编造）。"""
    del parsed  # 规则优先，不采用模型自由填写的数额／角色
    return extract_slots("", text)


def _grounded_fact(fact: str, text: str) -> bool:
    n = normalize(fact)
    nt = normalize(text)
    if not n or not nt:
        return False
    if len(n) <= 8:
        return n in nt
    step = 4
    return any(n[i:i + 8] in nt for i in range(0, len(n) - 7, step))


def merge_facts(llm_facts: list[str], old_facts: list[str], text: str) -> list[str]:
    """最多 3 条。模型失败时保留原事实句。有模型句时丢掉对不上原文的，并保住对立原句。"""
    old_clean = [str(f).strip() for f in old_facts if str(f).strip()]
    llm_clean = [str(f).strip() for f in llm_facts if str(f).strip()]
    if not llm_clean:
        return old_clean[:3]
    rescue_keys = ("没让我走", "不想走", "不愿走", "未放行", "买断", "补偿")
    ordered: list[str] = []
    for f in list(old_facts) + list(llm_facts):
        s = str(f).strip()
        if not s or s in ordered:
            continue
        if not _grounded_fact(s, text):
            continue
        if any(k in s for k in rescue_keys):
            ordered.insert(0, s)
        else:
            ordered.append(s)
    # 救援句放前面之后再截断，但不要用三条救援把唯一事实挤光——已在前
    # 去近似重复：后者被前者包含则丢
    kept: list[str] = []
    for s in ordered:
        ns = normalize(s)
        if any(ns and ns in normalize(prev) for prev in kept):
            continue
        if any(normalize(prev) and normalize(prev) in ns and len(normalize(prev)) >= 12 for prev in kept):
            # 新句更长且包含已有短句：用更长的替换
            kept = [
                s if (normalize(prev) and normalize(prev) in ns and len(normalize(prev)) >= 12)
                else prev
                for prev in kept
            ]
            if s not in kept:
                kept.append(s)
            continue
        kept.append(s)
    # 稳定去重
    out: list[str] = []
    for s in kept:
        if s not in out:
            out.append(s)
    return out[:3]


def apply_slots_to_summary(
    summary: dict[str, Any],
    *,
    title: str,
    text: str,
    llm_facts: list[str] | None = None,
) -> dict[str, Any]:
    """在已有摘要上补槽位，并可选换上有据的新事实句。"""
    out = dict(summary or {})
    old_facts = [str(x).strip() for x in (out.get("facts") or []) if str(x).strip()]
    facts = merge_facts(list(llm_facts or []), old_facts, text) or old_facts[:3]
    slots = extract_slots(title, text)
    # 对立词并进 keywords（仍须是原文里出现的）
    keywords = [str(x).strip() for x in (out.get("keywords") or []) if str(x).strip()]
    for term in slots["opposition_terms"]:
        if term not in keywords:
            keywords.append(term)
    out["facts"] = facts
    out["keywords"] = keywords[:8]
    out.update(slots)
    out["summary_text"] = with_slot_text(out)
    out["ok"] = bool(out["facts"] or out.get("entities") or out["keywords"])
    return out


_LLM_PROMPT = """只根据段落写 JSON。facts 最多 3 条、每条≤40字。禁止赛绩、通稿套话和段外事实。
若段内有原话／对立口径，优先保留原句，不要改主语。
没有的槽位留空。

{{"facts":["..."],"opposition_terms":[],"amount_note":"","procedure_dates":[]}}

段落：
{text}
"""


def llm_fact_candidates(text: str) -> list[str]:
    """本机重摘要。失败返回空列表，调用方保留旧 facts。"""
    from app.kg_lab.ollama_client import generate_json
    from app.kg_lab.summarize import _salvage_json

    body = (text or "").strip()
    if len(body) > 1800:
        body = body[:1800] + "…"
    if not body:
        return []
    resp = generate_json(_LLM_PROMPT.format(text=body), num_predict=280, temperature=0.0)
    parsed = resp.get("parsed") or {}
    if not parsed:
        parsed = _salvage_json(str(resp.get("raw") or ""))
    facts = [str(x).strip() for x in (parsed.get("facts") or []) if str(x).strip()]
    return facts[:3]
