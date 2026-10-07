"""输出侧个人信息掩码（展示层；案卷与哈希链仍存原文，可审计）。

金融/人事语料里的手机号、身份证、银行卡、邮箱不得原样出现在报告
与工作台视图。判定全正则、零 LLM。
"""

from __future__ import annotations

import re

from app.core.evidence import Dossier

_PHONE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_LANDLINE = re.compile(r"(?<!\d)(0\d{2,3}-)\d{3,4}(\d{4})(?!\d)")
_ID18 = re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?!\d)")
_BANK = re.compile(r"(?<!\d)(\d{4})\d{8,11}(\d{4})(?!\d)")
_EMAIL = re.compile(
    r"([^\s@]{1,64})@([A-Za-z0-9.-]+\.[A-Za-z]{2,})",
)


def mask_pii(text: str) -> str:
    """单段文本掩码；空串原样返回。"""
    if not text:
        return text
    out = _PHONE.sub(r"\1****\2", text)
    out = _LANDLINE.sub(r"\1****\2", out)
    out = _ID18.sub(r"\1********\2", out)
    out = _BANK.sub(r"\1********\2", out)
    out = _EMAIL.sub(r"***@\2", out)
    return out


def mask_pii_in_dossier(dossier: Dossier) -> Dossier:
    """就地掩码展示用案卷（应对 deepcopy 后的视图）。"""
    dossier.question = mask_pii(dossier.question)
    dossier.title = mask_pii(dossier.title)
    for src in dossier.sources:
        src.title = mask_pii(src.title)
        for seg in src.segments:
            seg.text = mask_pii(seg.text)
    for ev in dossier.evidences:
        ev.quote = mask_pii(ev.quote)
        ev.note = mask_pii(ev.note)
    for con in dossier.conclusions:
        con.statement = mask_pii(con.statement)
        for rec in con.dissent or []:
            if isinstance(rec, dict):
                if rec.get("statement"):
                    rec["statement"] = mask_pii(str(rec["statement"]))
                if rec.get("why"):
                    rec["why"] = mask_pii(str(rec["why"]))
    for raw in dossier.conflicts or []:
        if not isinstance(raw, dict):
            continue
        for k in ("topic", "description"):
            if raw.get(k):
                raw[k] = mask_pii(str(raw[k]))
        res = raw.get("resolution") or {}
        if isinstance(res, dict):
            if res.get("rationale"):
                res["rationale"] = mask_pii(str(res["rationale"]))
            rebuts = res.get("rebuts") or {}
            for side, text in list(rebuts.items()):
                rebuts[side] = mask_pii(str(text))
    synth = dossier.synthesis or {}
    if synth.get("headline"):
        synth["headline"] = mask_pii(str(synth["headline"]))
    for p in synth.get("points") or []:
        if p.get("gloss"):
            p["gloss"] = mask_pii(str(p["gloss"]))
    for o in synth.get("open_issues") or []:
        if o.get("text"):
            o["text"] = mask_pii(str(o["text"]))
    return dossier
