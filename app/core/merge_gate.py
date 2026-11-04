"""C-145：归并硬约束闸（同主体 × 同指标 × 可核验才合）。

治的病：LLM 语义归并只按「语义相同或高度相近」判（MERGE_SYSTEM），模型把
两条**不同主体／不同指标**的结论揉成一组时，组结论以「已一致」的面目出现在
交卷面——一致性分量（agreement）被错并灌水，且差异被静默吃掉。机械归并
（``merge_mechanical``）的分组键本来就要求同主体×窄议题×同极性×有证据，
对本闸天然合规；本闸只看住 **LLM 段**提出的每个 ≥2 人组。

四道腿（任一不过 → 整组否决，成员保持独立——宁可留重复，不可错并，
与机械归并同一原则）：
- 同主体：``extract_subject`` 全员在场且相等；有人抽不到 → 缺主体；
  任两方不同 → 主体不一致；
- 同指标：``narrow_topic``（与机械归并同一窄词表）全员命中同一维；
  命中 0 个或 ≥2 个（判不清）→ 缺指标；互不相同 → 指标不一致；
- 极性不反：双方极性都判得出且相反 → 否决（该对立交还冲突面配对，
  不许并成「已一致」）；判不出不拦；
- 可核验：成员结论仍挂着 ≥1 条在场证据——坏证据在引文核对已被打回、
  active 结论本必有证据，此处为防绕过复述检查。

开关：随 ``VERITAS_CONFLICT_TRACE``（C-145a 起出厂默认开；＝0 时闸与
留痕全关，归并行为与改前逐字一致）。否决事件写入
``accounting["merge_gate"]``，并由 ``conflict_trace.apply_conflict_trace``
折进回放面 payload（``conflict_trace.json`` 顶层 ``merge_gate`` 节），
与 C-143 展示面衔接。

禁：数值冲突加权／打分零改动（Boyu STOP 线）；不碰质证／仲裁；
不做部分拆组（整组否决＝最小实现，组内混入一条不合规即全组不并）。
"""

from __future__ import annotations

from typing import Any

from app.core.conflict_pairing import extract_subject, polarity_of
from app.core.merge_mechanical import narrow_topic

# 账本键与回放面节名（pipeline 两处 kept 白名单须登记 ACCOUNTING_KEY）
ACCOUNTING_KEY = "merge_gate"
SECTION_KEY = "merge_gate"

_FAIL_CODES = {
    "missing_subject": "缺主体：组内存在抽不到客户标签的结论",
    "subject_mismatch": "主体不一致：组内出现不同客户标签",
    "missing_metric": "缺指标：组内存在窄议题维判不清（0 或 ≥2 维）的结论",
    "metric_mismatch": "指标不一致：组内窄议题维互不相同",
    "polarity_opposed": "极性对立：正反判断应交冲突面，不并为「已一致」",
    "unverifiable": "不可核验：组内存在无在场证据的结论",
}


def gate_active(settings: Any | None = None) -> bool:
    """闸随 C-115 旗走（C-145a 起默认开；env=0 全关＝改前行为）。"""
    from app.core.conflict_trace import conflict_trace_enabled

    return conflict_trace_enabled(settings)


def check_group(dossier: Any, member_ids: list[str]) -> dict[str, Any]:
    """一个候选归并组 → {ok, fail_legs, legs}。纯机械、零 LLM、确定性。"""
    legs: dict[str, Any] = {"subject": [], "metric": [], "polarity": []}
    fails: list[str] = []
    subjects: list[str | None] = []
    metrics: list[str | None] = []
    polarities: list[str | None] = []
    n_unverified = 0
    for cid in member_ids:
        con = dossier.conclusion(cid)
        stmt = str(getattr(con, "statement", "") or "")
        subjects.append(extract_subject(stmt))
        metrics.append(narrow_topic(stmt))
        polarities.append(polarity_of(stmt))
        if con is None or not dossier.evidences_of(cid):
            n_unverified += 1
    legs["subject"] = subjects
    legs["metric"] = metrics
    legs["polarity"] = polarities
    if any(s is None for s in subjects):
        fails.append("missing_subject")
    elif len({s for s in subjects}) > 1:
        fails.append("subject_mismatch")
    if any(m is None for m in metrics):
        fails.append("missing_metric")
    elif len({m for m in metrics}) > 1:
        fails.append("metric_mismatch")
    known_pols = {p for p in polarities if p}
    if len(known_pols) > 1:
        fails.append("polarity_opposed")
    if n_unverified:
        fails.append("unverifiable")
    # 稳定顺序：按 _FAIL_CODES 的声明序去重
    seen: set[str] = set()
    ordered = [c for c in _FAIL_CODES if c in fails and not seen.add(c)]
    return {"ok": not ordered, "fail_legs": ordered, "legs": legs,
            "n_unverified": n_unverified}


def block_row(member_ids: list[str], check: dict[str, Any], *,
              index: int) -> dict[str, Any]:
    """一条否决事件（回放面行）——只记 id 与腿读数，不落结论文本。"""
    codes = list(check.get("fail_legs") or [])
    return {
        "id": f"MERGE-{index:04d}",
        "n_members": len(member_ids),
        "member_ids": [str(m) for m in member_ids],
        "legs": {
            "subject": list(check["legs"]["subject"]),
            "metric": list(check["legs"]["metric"]),
            "polarity": list(check["legs"]["polarity"]),
        },
        "fail_legs": codes,
        "reason_code": codes[0] if codes else "unknown",
        "reason_short": "；".join(_FAIL_CODES[c] for c in codes if c in _FAIL_CODES),
    }


def write_accounting(dossier: Any, *, n_checked: int, blocked: list[dict],
                     note: str = "") -> dict[str, Any] | None:
    """旗开写 ``accounting["merge_gate"]``；旗关＝None、不写键。"""
    if not gate_active():
        return None
    acc = getattr(dossier, "accounting", None)
    if acc is None:
        dossier.accounting = {}
        acc = dossier.accounting
    n_blocked = len(blocked)
    payload: dict[str, Any] = {
        "enabled": True,
        "n_groups_checked": int(n_checked),
        "n_blocked": n_blocked,
        "blocked": blocked[:40],
        "note": note or (
            f"归并硬约束闸：核查 {n_checked} 组，否决 {n_blocked} 组"
            f"（缺主体／缺指标／不可核验／极性对立不放行为「已一致」）"
            if n_checked or n_blocked else
            "归并硬约束闸：核查 0 组（无 ≥2 人的 LLM 归并组）"),
    }
    acc[ACCOUNTING_KEY] = payload
    return payload


def fold_into_trace_payload(payload: dict[str, Any], accounting: Any) -> None:
    """把账本里的 merge_gate 节折进 conflict_trace 回放面 payload。

    C-143 展示面衔接：``conflict_trace.json`` 顶层多一个 ``merge_gate`` 节；
    三类分布／处置分布（records 汇总）不动——否决事件不冒充第四类冲突。
    """
    if not isinstance(payload, dict):
        return
    acc = accounting if isinstance(accounting, dict) else {}
    section = acc.get(ACCOUNTING_KEY)
    if isinstance(section, dict):
        payload[SECTION_KEY] = section
