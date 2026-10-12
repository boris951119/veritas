"""编队减员显影：有人未交付时必须写进报告首屏，不得装成全员到齐。"""

from __future__ import annotations

import re

from app.core.evidence import Dossier


def _short_reason(err: str) -> str:
    text = (err or "").strip()
    if not text:
        return "失败"
    if re.search(r"timeout|超时", text, re.I):
        return "超时"
    if re.search(r"RateLimit|额度|quota", text, re.I):
        return "额度/限流"
    head = text.split(":", 1)[0].strip()
    return head[:24] if head else "失败"


def panel_attrition_record(roster: list[str],
                           failures: dict[str, str]) -> dict | None:
    """failures 非空 → 账本记录；否则 None。"""
    roster = [str(x) for x in roster if str(x).strip()]
    fails = {str(k): str(v) for k, v in (failures or {}).items() if k}
    if not roster or not fails:
        return None
    delivered = [n for n in roster if n not in fails]
    n, m = len(roster), len(fails)
    # 一致性按原编队人数封顶：单人署名时 agreement ≤ 1/N
    agree_cap = round(1.0 / n, 4)
    parts = [f"{name}（{_short_reason(err)}）"
             for name, err in fails.items()]
    note = (
        f"本次编队 {n} 人中 {m} 人未交付（{'、'.join(parts)}）；"
        f"编队名仅列实际交付者；全部结论为单人署名时一致性分量已封顶 "
        f"{agree_cap}"
    )
    return {
        "kind": "panel_attrition",
        "roster": roster,
        "delivered": delivered,
        "failures": {k: _short_reason(v) for k, v in fails.items()},
        "failure_detail": fails,
        "n_roster": n,
        "n_failed": m,
        "agreement_cap": agree_cap,
        "note": note,
    }


def apply_panel_attrition(dossier: Dossier, roster: list[str],
                          failures: dict[str, str]) -> dict | None:
    """写入 accounting，并把 dossier.panel 收成实际交付者。"""
    rec = panel_attrition_record(roster, failures)
    if rec is None:
        dossier.panel = list(roster)
        return None
    dossier.panel = list(rec["delivered"])
    dossier.accounting["panel_attrition"] = rec
    return rec
