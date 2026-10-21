"""推理链完整性（榜单硬需求 3 的第四分量：信源可信度 / 数据数量与一致性 /
**推理链完整性**——前三项已有 strength+coverage+agreement 对应，第四项此前
只以黄灯形式存在，不进分数，评委照榜单原文勾分项时勾不出来）。

一条结论的"链"要走完六环才算闭合：

| 检查项 | 适用条件（不适用就不进分母） | 判据来源 |
|---|---|---|
| quote_hits        引文逐字命中 | 该结论挂了证据 | `citation_check.check_quote` |
| warrant_theme     理由与主张同主题 | 主张命中主题组且有证据 | `warrant_check` 的闸输出 |
| number_traceable  数字可溯源可复算 | 结论正文出现数字 | `numeric_check`/`counting`/`claim_check` 闸输出 |
| scope_declared    声称范围时有覆盖声明 | 结论用了范围词 | `scope_check` 闸输出 |
| as_of_anchored    涉及时点已锚定 | 所引信源**全部**带时点 | `temporal_check` 闸输出 |
| causation_mechanism 因果标注有机制词 | 有标 causation 的证据 | `discourse_check` 闸输出 |

**口径单一来源**：除引文命中外，六项全部复用各道机械闸的真实 flag 输出，
本模块不另写一套判定——否则会出现"分数说链完整、警示说脱节"这种自相矛盾。

两条 fail-closed 规矩（学 REA 的 unknown 不许当 pass）：
1. 适用项为 0（无从判定）时 **不给满分**，返回 `None`，由置信度按未知档计分；
2. 分母只算适用项，避免"没写数字"的结论白捡满分——但"没触发任何检查"本身
   会被记成 unknown，在分量面板上看得见。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.core.citation_check import check_quote
from app.core.evidence import Dossier, RelationKind
from app.core.numeric_check import extract_nums
from app.core.scope_check import scope_trigger
from app.core.temporal_check import source_date
from app.core.warrant_check import _themes_in

# 检查项 → 哪些闸的 kind 出现即算这一环断了
_BROKEN_BY_KIND: dict[str, frozenset[str]] = {
    "warrant_theme": frozenset({"warrant_theme"}),
    "number_traceable": frozenset({"calc", "provenance", "counting",
                                   "percent_no_base", "unit_mismatch"}),
    "scope_declared": frozenset({"scope"}),
    "as_of_anchored": frozenset({"as_of", "stale"}),
    "causation_mechanism": frozenset({
        "causation_support", "causal_claim_missing"}),
}


CHECK_LABEL_CN = {
    "quote_hits": "引文逐字命中",
    "warrant_theme": "理由支撑主张",
    "number_traceable": "数字可溯源",
    "scope_declared": "范围有声明",
    "as_of_anchored": "时点已锚定",
    "causation_mechanism": "因果有机制",
}
CHECK_ORDER = tuple(CHECK_LABEL_CN)


@dataclass
class ChainReport:
    """一条结论的链完整性结果。"""

    applicable: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)
    unknown: bool = False

    @property
    def score(self) -> float | None:
        """0-1；适用项为 0 时返回 None（无从判定 ≠ 满分）。"""
        if not self.applicable:
            return None
        return 1.0 - len(self.broken) / len(self.applicable)

    def to_parts(self) -> dict:
        return {"applicable": list(self.applicable),
                "broken": list(self.broken),
                "score": None if self.score is None else round(self.score, 4),
                "unknown": self.unknown}


def _flags_by_conclusion(dossier: Dossier) -> dict[str, set[str]]:
    """一次性取全部机械闸输出并按结论归堆（避免每条结论重算一遍全案卷）。"""
    from app.core.audit import audit_all

    out: dict[str, set[str]] = {}
    for flag in audit_all(dossier):
        cid = flag.get("conclusion_id")
        if cid:
            out.setdefault(str(cid), set()).add(str(flag.get("kind")))
    return out


def _quotes_hit(dossier: Dossier, conclusion_id: str) -> bool:
    """每条证据的引文都要能在它所指的段落里逐字找到。"""
    evs = dossier.evidences_of(conclusion_id)
    if not evs:
        return False
    for ev in evs:
        segs = [dossier.segment(sid) for sid in ev.segment_ids]
        if not any(seg is not None and check_quote(ev.quote, seg.text or "").ok
                   for seg in segs):
            return False
    return True


def _all_sources_dated(dossier: Dossier, conclusion_id: str) -> bool:
    """所引段落所属信源**全部**带时点——与 as_of 闸同一适用条件。"""
    sids = [sid for ev in dossier.evidences_of(conclusion_id) for sid in ev.segment_ids]
    if not sids:
        return False
    dated = 0
    for sid in sids:
        src = dossier.source_of_segment(sid)
        if src is not None and source_date(src):
            dated += 1
    return dated == len(sids)


def applicable_checks(dossier: Dossier, conclusion_id: str) -> list[str]:
    """该结论触发了哪些链检查（不进分母的项必须是真不适用，不是没算）。"""
    con = dossier.conclusion(conclusion_id)
    evs = dossier.evidences_of(conclusion_id)
    statement = (con.statement if con else "") or ""
    out: list[str] = []
    if evs:
        out.append("quote_hits")
    if evs and _themes_in(statement):
        out.append("warrant_theme")
    if extract_nums(statement):
        out.append("number_traceable")
    if scope_trigger(statement):
        out.append("scope_declared")
    if evs and _all_sources_dated(dossier, conclusion_id):
        # 适用条件与 as_of 闸一致：所引信源全带时点才要求锚定；
        # 「有没有锚」不由这里判，由 temporal_check 的闸输出说——否则
        # 这项会退化成「一适用必断链」，把分母灌成水
        out.append("as_of_anchored")
    # 当前标 causation，或曾声明过因果（declared_relation）——降级后仍进分母
    # 并按断链计；否则降级会让分母变小、分数反而涨（R-C32-1）
    if any(
        e.relation == RelationKind.CAUSATION
        or (e.declared_relation or "") == "causation"
        for e in evs
    ):
        out.append("causation_mechanism")
    return [c for c in CHECK_ORDER if c in out]


def chain_integrity(dossier: Dossier, conclusion_id: str,
                    flags_by_conclusion: dict[str, set[str]] | None = None
                    ) -> ChainReport:
    """单条结论的推理链完整性。"""
    flags = (flags_by_conclusion if flags_by_conclusion is not None
             else _flags_by_conclusion(dossier))
    kinds = flags.get(conclusion_id, set())
    report = ChainReport(applicable=applicable_checks(dossier, conclusion_id))
    if not report.applicable:
        report.unknown = True
        return report
    for check in report.applicable:
        if check == "quote_hits":
            if not _quotes_hit(dossier, conclusion_id):
                report.broken.append(check)
        elif kinds & _BROKEN_BY_KIND[check]:
            report.broken.append(check)
    return report


def chain_context(dossier: Dossier) -> dict[str, set[str]]:
    """给 `recompute_all` 用的共享上下文：全案卷只扫一遍闸。"""
    return _flags_by_conclusion(dossier)


def summarize_chain(reports: Iterable[ChainReport]) -> dict:
    """一批链结果的概览（评分器与答辩材料用：断在哪一环最多）。"""
    broken: dict[str, int] = {}
    n_unknown = n_scored = 0
    total = 0
    for rep in reports:
        total += 1
        if rep.unknown:
            n_unknown += 1
        for check in rep.broken:
            broken[check] = broken.get(check, 0) + 1
            n_scored += 1
    return {"n_conclusions": total, "n_unknown": n_unknown,
            "n_broken_checks": n_scored,
            "broken_by_check": {CHECK_LABEL_CN.get(k, k): v
                                for k, v in sorted(broken.items(),
                                                   key=lambda x: -x[1])}}
