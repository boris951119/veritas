"""冲突配对：程序按「主体 × 议题维」生成候选，跨主体永不进场。

丢弃必披露（conflict_drops 账本）。同主体极性对立强制进候选，防漏检。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.evidence import Dossier

# 客户B / 客户 C / 客户甲
_CUSTOMER_RE = re.compile(
    r"客户\s*([A-Za-z]|[甲乙丙丁戊己庚辛壬癸]|[一二三四五六七八九十])"
)

_TOPIC_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("payment", ("回款", "应收账款", "坏账", "质保金", "应收")),
    ("delay", ("延期", "进度延迟", "进度延误", "验收延迟", "延迟")),
    ("staff", ("人员流失", "离职", "人力流失", "核心人员")),
    ("delivery", ("交付", "完成率", "进度")),
]

_NEG = re.compile(
    r"不存在|无坏账|无回款风险|无延期|无人员流失|并未|没有.{0,4}风险"
)
_POS = re.compile(
    r"(?<!不)存在.{0,12}风险|有坏账|有回款风险|坏账计提|计提坏账|"
    r"可能导致.{0,8}延迟"
)


def extract_subject(statement: str) -> str | None:
    """结论文案中的客户标签；抽不到返回 None。"""
    m = _CUSTOMER_RE.search(statement or "")
    if not m:
        return None
    return f"客户{m.group(1).upper() if m.group(1).isalpha() else m.group(1)}"


def extract_topics(statement: str) -> set[str]:
    text = statement or ""
    out: set[str] = set()
    for key, words in _TOPIC_GROUPS:
        if any(w in text for w in words):
            out.add(key)
    return out


def polarity_of(statement: str) -> str | None:
    """pos / neg / None（看不清）。"""
    text = statement or ""
    neg = bool(_NEG.search(text))
    pos = bool(_POS.search(text))
    if neg and not pos:
        return "neg"
    if pos and not neg:
        return "pos"
    if neg and pos:
        # 「不存在延期，但存在回款风险」→ 不给单一极性
        return None
    return None


def subjects_compatible(a: str | None, b: str | None) -> bool:
    """双方都有主体且不同 → 不兼容；其余放行。"""
    if a and b and a != b:
        return False
    return True


def _meta(dossier: Dossier, cid: str) -> dict[str, Any] | None:
    con = dossier.conclusion(cid)
    if con is None:
        return None
    stmt = con.statement or ""
    return {
        "id": cid,
        "statement": stmt,
        "subject": extract_subject(stmt),
        "topics": extract_topics(stmt),
        "polarity": polarity_of(stmt),
    }


def subject_mismatch_reason(dossier: Dossier, a_id: str, b_id: str
                            ) -> str | None:
    """跨主体则返回原因串；否则 None。"""
    ma, mb = _meta(dossier, a_id), _meta(dossier, b_id)
    if ma is None or mb is None:
        return "结论不存在"
    if not subjects_compatible(ma["subject"], mb["subject"]):
        return (
            f"主体不一致（{ma['subject']} vs {mb['subject']}）"
        )
    return None


def build_candidate_pairs(
    dossier: Dossier, conclusion_ids: list[str],
) -> list[dict]:
    """同主体 × 议题维重叠，或同主体极性对立 → 候选对。

    无主体的结论不在此自动两两配对（避免 O(n²)）；留给 LLM 自由检出后再过闸。
    """
    metas = []
    for cid in conclusion_ids:
        m = _meta(dossier, cid)
        if m is None:
            continue
        if not dossier.evidences_of(cid):
            continue
        metas.append(m)

    cands: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for i, a in enumerate(metas):
        for b in metas[i + 1:]:
            if not subjects_compatible(a["subject"], b["subject"]):
                continue
            # 至少一方有主体才自动配（无主体对走自由检出）
            if not a["subject"] and not b["subject"]:
                continue
            topics_hit = bool(a["topics"] & b["topics"])
            polar_opp = (
                a["polarity"] and b["polarity"]
                and a["polarity"] != b["polarity"]
                and a["subject"] and a["subject"] == b["subject"]
            )
            if not topics_hit and not polar_opp:
                continue
            key = tuple(sorted((a["id"], b["id"])))
            if key in seen:
                continue
            seen.add(key)
            topic = "、".join(sorted(a["topics"] & b["topics"])) or (
                "同主体极性对立" if polar_opp else "议题相关"
            )
            cands.append({
                "a": a["id"],
                "b": b["id"],
                "topic": topic,
                "forced_polarity": bool(polar_opp),
                "subject": a["subject"] or b["subject"],
            })
    cands.sort(key=lambda x: (x.get("subject") or "", x["a"], x["b"]))
    return cands


def drops_record(
    drops: list[dict],
    *,
    n_candidates: int = 0,
    n_accepted: int = 0,
) -> dict:
    """账本 + 报告用摘要。"""
    by_reason: dict[str, int] = {}
    for d in drops:
        r = str(d.get("reason") or "其他")
        # 归并展示键
        if "主体不一致" in r:
            key = "主体不一致"
        elif "非真对立" in r or "非对立" in r:
            key = "非真对立"
        elif "非法" in r or "不存在" in r:
            key = "非法对"
        else:
            key = r[:16]
        by_reason[key] = by_reason.get(key, 0) + 1
    n = len(drops)
    bits = [f"{k} {v}" for k, v in sorted(by_reason.items())]
    note = (
        f"冲突配对丢弃 {n} 对"
        + (f"（{'；'.join(bits)}）" if bits else "")
        + f"；候选 {n_candidates} · 采纳 {n_accepted}"
    ) if n else (
        f"冲突配对丢弃 0 对；候选 {n_candidates} · 采纳 {n_accepted}"
        if n_candidates or n_accepted else ""
    )
    return {
        "kind": "conflict_drops",
        "n_dropped": n,
        "n_candidates": n_candidates,
        "n_accepted": n_accepted,
        "by_reason": by_reason,
        "drops": drops[:40],
        "note": note,
    }
