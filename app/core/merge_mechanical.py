"""机械归并：LLM 归并之后，把**字面可判定**的重复结论强制收成一组（零 LLM）。

为什么需要：归并判据「语义相同或高度相近」整个交给模型，本地 14B 判得保守，
实测 bi 案例 24 条主流结论**归并 0 组**——客户拿到的是一份没去重的清单
（同一个客户的同一个话题最多被写 3 遍），而且一致性分量被单署名压死在
1/3，置信度天花板 0.27。这正好是榜单点名的「独立判断或简单投票」。

本模块不替模型做语义判断，只收它漏掉的三类**全部可机械核对**的相同：
同一主体 × 同一议题维 × 同一极性。三条任一不满足、或任何一条判不清 → 不动。
原则是**宁可留重复，也不可错并**：错并把两个不同判断揉成一句，比多两行重复
严重得多——那正是这台审计机器存在的理由。

接线：agents/arbiter.merge_conclusions 在 LLM 归并后调用本模块补一轮；
组结论用成员原句做代表陈述（不造新句，避免归并概括漂移），成员标 merged
保留溯源，署名取并集（跨人会签由此产生，agreement 分量随之抬升）。
开关：VERITAS_MECH_MERGE=0 关闭（A/B 对照用）。
"""

from __future__ import annotations

import os
from typing import Any

from app.core.conflict_pairing import extract_subject, polarity_of
from app.core.evidence import Dossier

# 归并键比冲突配对的议题维**更窄**：conflict_pairing 把「回款/应收账款/坏账/
# 计提」算同一维（配成对让模型判对立是安全的，判错了只是多看一眼），但归并是
# 真的把两条并成一条——「存在回款风险」与「存在坏账风险」在信贷分析里是两回事
# （钱回不来 vs 已确认损失），并了就把差异吃掉了。所以这里拆开，且一句话同时
# 命中两个窄维时判为「说不清」，不参与归并。
_NARROW_TOPICS: list[tuple[str, tuple[str, ...]]] = [
    ("bad_debt", ("坏账", "计提")),
    ("payment", ("回款", "应收账款", "质保金", "应收")),
    ("delay", ("延期", "延迟", "进度")),
    ("staff", ("人员流失", "离职", "人力流失")),
    ("delivery", ("交付", "完成率")),
]


def enabled() -> bool:
    return os.environ.get("VERITAS_MECH_MERGE", "1") != "0"


def narrow_topic(statement: str) -> str | None:
    """唯一窄议题维；命中 0 个或 ≥2 个 → None（说不清就不并）。"""
    hits = [key for key, words in _NARROW_TOPICS
            if any(w in statement for w in words)]
    return hits[0] if len(hits) == 1 else None


def merge_key(dossier: Dossier, conclusion_id: str) -> tuple | None:
    """可机械归并的分组键；判不清返回 None（该结论不参与机械归并）。

    五道不并：无主体标签、议题维不唯一（一句同时谈回款与延期）、回款与坏账
    混说、极性判不出或正反同现（「不存在延期，但存在回款风险」）、无证据挂载。
    """
    con = dossier.conclusion(conclusion_id)
    if con is None or not con.statement:
        return None
    if not dossier.evidences_of(conclusion_id):
        return None
    subject = extract_subject(con.statement)
    if not subject:
        return None
    topic = narrow_topic(con.statement)
    if topic is None:
        return None
    polarity = polarity_of(con.statement)
    if polarity is None:
        return None
    return (subject, topic, polarity)


def mechanical_groups(dossier: Dossier, active_ids: list[str]
                      ) -> list[list[str]]:
    """活跃结论 → 需要强制合并的组（每组 ≥2 个 id，按首次出现排序）。"""
    buckets: dict[tuple, list[str]] = {}
    for cid in active_ids:
        key = merge_key(dossier, cid)
        if key is None:
            continue
        buckets.setdefault(key, []).append(cid)
    return [ids for ids in buckets.values() if len(ids) >= 2]


def merge_stats(dossier: Dossier, groups: list[list[str]],
                llm_group_ids: list[str]) -> dict[str, Any]:
    """披露用的账本记录：机械归并动了多少条、其中几条是跨人会签。

    丢弃/未合并的必须能解释——归并率本身是答辩要念的数字。
    """
    n_members = sum(len(g) for g in groups)
    cross = 0
    for g in groups:
        authors = {a for cid in g
                   for a in (dossier.conclusion(cid).author_names()
                             if dossier.conclusion(cid) else [])}
        if len(authors) >= 2:
            cross += 1
    return {
        "n_llm_groups": len(llm_group_ids),
        "n_mech_groups": len(groups),
        "n_members_absorbed": n_members,
        "n_cross_author_groups": cross,
        "note": (f"机械归并 {len(groups)} 组（吸收 {n_members} 条，"
                 f"其中跨分析师会签 {cross} 组）" if groups
                 else "机械归并未触发（无同主体×同议题×同极性的重复结论）"),
    }
