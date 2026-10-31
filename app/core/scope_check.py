"""范围诚实闸（零 LLM）：声称了范围，就必须声明覆盖。

拦的是 2026-10-13 实测到的那一类：17 条全称量词结论**全部**引用覆盖低于 25%
（最低 1.8%），例如「所有客户项目中未发现已发生的人员流失风险」只引了 7% 的段落。
现有闸查引文真不真、数字对不对，没有一道问过**「你说『全部』，你看的真是全部吗」**。

三条判定：

1. 结论出现全称量词（全部/所有/无一/每个/没有任何/均显示…）或「不存在类」表述
   （未发现/未检索到/无相关…）⇒ 视为**声称了范围**；
2. 声称了范围却没有 `coverage` 声明 ⇒ 黄牌（`scope`），detail 里给出该结论
   实际引用覆盖，让人一眼看到「说全部、引 2%」；
3. 声明了 `complete` 却一条证据都没挂 ⇒ 黄牌（自相矛盾的声明一样要亮）。

只亮灯不删结论——语义取舍仍归人，机械侧只保证「声称的范围有出处」。
"""

from __future__ import annotations

import re

from app.core.evidence import Dossier

# 全称量词：把结论说成覆盖某个集合的全部成员
_UNIVERSAL_RE = re.compile(r"全部|所有|无一|每个|每一|没有任何|均(?:显示|表明|存在|为|未)")
# 「不存在类」：把「没找到」说成「不存在」——REA 的原话是 missing coverage is unknown, not absence
_ABSENCE_RE = re.compile(
    r"未检索到|没有找到|未发现|无相关|不存在|未见|未提及|没有.{0,3}(证据|信源|记载)")


def scope_trigger(statement: str) -> tuple[str, str] | None:
    """该结论是否声称了范围：返回 (命中词, 类型)，没声称返回 None。"""
    st = statement or ""
    m = _UNIVERSAL_RE.search(st)
    if m:
        return m.group(0), "universal"
    m = _ABSENCE_RE.search(st)
    if m:
        return m.group(0), "absence"
    return None


def cited_share(dossier: Dossier, conclusion_id: str) -> float:
    """该结论实际引用到的段落占案卷段落总数（衡量「看的真是全部吗」）。"""
    n_segments = sum(len(src.segments) for src in dossier.sources)
    if not n_segments:
        return 0.0
    cited = {sid for ev in dossier.evidences_of(conclusion_id) for sid in ev.segment_ids}
    return len([s for s in cited if dossier.segment(s) is not None]) / n_segments


def audit_scope(dossier: Dossier) -> list[dict]:
    """范围声明闸：声称范围而未声明覆盖 → 黄牌。"""
    flags: list[dict] = []
    for con in dossier.conclusions:
        if con.status == "merged":
            continue
        hit = scope_trigger(con.statement or "")
        if not hit:
            continue
        trigger, kind = hit
        cov = con.coverage
        if cov is None:
            share = cited_share(dossier, con.id)
            kind_cn = "声称覆盖全部" if kind == "universal" else "把「没找到」说成「不存在」"
            flags.append({
                "kind": "scope", "severity": "medium",
                "conclusion_id": con.id, "value": trigger,
                "detail": (f"结论用了「{trigger}」——{kind_cn}，但没有覆盖声明；"
                           f"本次实际引用覆盖 {share:.0%}。"
                           "改写建议：写明「在本次纳入的 N 份中未见…」，"
                           "或给出 coverage（partial 须写局限）"),
            })
        elif cov.state == "complete" and not dossier.evidences_of(con.id):
            flags.append({
                "kind": "scope", "severity": "medium",
                "conclusion_id": con.id, "value": trigger,
                "detail": (f"覆盖声明写的是「已覆盖全部」，但该结论没有挂任何证据，"
                           f"声明与证据自相矛盾（触发词「{trigger}」）"),
            })
    return flags
