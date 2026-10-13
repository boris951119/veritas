"""闸的准入探针：把「这道闸本次连一个对象都没检查到」显影出来。

为什么需要（2026-10-13 实测）：机械核对的输出只有「亮灯 / 没亮」两态，
**没亮** 既可能是「查过且干净」，也可能是「压根没进场」。计数闸是重灾区：
它只核显式「计数:M/N」格式，存量 304 条结论里只有 2 条写了这格式——
免检率 99.3%，于是它报的「零违规」几乎不含信息量。

这一层不改任何判定，只回答一个问题：**这道闸有没有可核对象**。
口径保守——只有在「可证明地一个对象都没碰到」时才记 not_evaluated，
宁可少记也不编造免检。

与 `audit_all` 的分工：`audit_all` 出旗，本模块出「未执行清单」；
`app.core.audit.audit_scan` 把两者合成一次扫描，供报告 / 工作台 / 评分器消费。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core.claim_check import _GROWTH          # noqa: PLC2701
from app.core.coverage_gap import _themes_in      # noqa: PLC2701
from app.core.evidence import Dossier, RelationKind
from app.core.numeric_check import (              # noqa: PLC2701
    _COUNT_RE, _parse_expr, _strip_noise, extract_nums)
from app.core.premise_check import extract_entities
from app.core.scope_check import scope_trigger
from app.core.temporal_check import find_collisions, source_date


@dataclass(frozen=True)
class GateSpec:
    """一道闸的准入条件：`has_work` 为假 ⇒ 该闸本次未执行，必须留痕。"""

    kind: str
    label: str
    has_work: Callable[[Dossier], bool]
    reason: str

    def to_note(self) -> dict:
        return {"kind": self.kind, "label": self.label, "reason": self.reason}


def _texts(dossier: Dossier) -> list[str]:
    """结论正文 + 证据说明——话语类闸的检查面就是这个集合。"""
    out = [c.statement or "" for c in dossier.conclusions if c.statement]
    out += [ev.note or "" for ev in dossier.evidences if ev.note]
    return out


def _has_conclusion_with_evidence(dossier: Dossier) -> bool:
    return any(dossier.evidences_of(c.id)
               for c in dossier.conclusions if c.status != "merged")


GATE_SPECS: tuple[GateSpec, ...] = (
    GateSpec(
        "counting", "计数复核",
        lambda d: any(_COUNT_RE.search(t) for t in _texts(d)),
        "结论与证据说明里没有任何显式「计数:M/N」断言——该闸只核这种写法，"
        "其余计数断言不经它手"),
    GateSpec(
        "calc", "计算复算",
        lambda d: any(_parse_expr(_strip_noise(t)) for t in _texts(d)),
        "本次结论里没有可复算的算式（如「A×B=C」「占比 M/N」），计算复算无对象"),
    GateSpec(
        "provenance", "数字溯源",
        lambda d: any(extract_nums(c.statement or "")
                      for c in d.conclusions if c.statement),
        "结论正文没有出现任何数字，数字溯源无对象"),
    GateSpec(
        "merge_conservation", "归并守恒",
        lambda d: any(c.status == "merged" or c.group_id
                      for c in d.conclusions),
        "本次没有发生归并（无组结论、无成员结论），归并守恒无对象"),
    GateSpec(
        "rebut_quote", "质证引文核对",
        lambda d: bool(d.conflicts),
        "本案卷没有冲突与消解记录，质证引文/引用核对未执行"),
    GateSpec(
        "causation_support", "因果机制词核对",
        lambda d: any(ev.relation is RelationKind.CAUSATION
                      for ev in d.evidences),
        "没有任何证据标注为 causation（因果），因果机制词核对未执行"),
    GateSpec(
        "stale", "旧时点引用核对",
        lambda d: bool(find_collisions(d)),
        "信源之间没有可比的时点差异（缺 published_at 或无同期对立数字），"
        "时效核对未执行"),
    GateSpec(
        "as_of", "结论时点锚定核对",
        lambda d: any(source_date(s) for s in d.sources),
        "所有信源都没有声明时点，as-of 锚定无从判断"),
    GateSpec(
        "near_dup", "同源转述核对",
        lambda d: len(d.sources) >= 2,
        "案卷不足两份信源，同源转述核对无从两两比较"),
    GateSpec(
        "premise", "议题前提核对",
        lambda d: bool(extract_entities(d.question or "")),
        "议题里抽不出可核对的实体词，前提闸未执行"),
    GateSpec(
        "percent_no_base", "涨跌百分比基数核对",
        lambda d: any(_GROWTH.search(c.statement or "")
                      for c in d.conclusions if c.statement),
        "结论没有出现增长/下降类百分比表述，该核对未执行"),
    GateSpec(
        "scope", "范围诚实核对",
        lambda d: any(scope_trigger(c.statement or "")
                      for c in d.conclusions if c.status != "merged"),
        "没有结论声称范围（无全称量词、无「不存在类」表述），范围诚实核对未执行"),
    GateSpec(
        "warrant_theme", "理由—主张主题词核对",
        lambda d: (any(_themes_in(c.statement or "")
                       for c in d.conclusions if c.statement)
                   and _has_conclusion_with_evidence(d)),
        "结论正文未命中任何主题组，或没有结论挂证据——理由与主张脱节无从判定"),
    GateSpec(
        "hedge", "低可信信源配断言语气核对",
        _has_conclusion_with_evidence,
        "没有任何「结论挂到了证据」的对象，转述级语气核对未执行"),
    GateSpec(
        "level_tone", "措辞强度与证据等级核对",
        _has_conclusion_with_evidence,
        "没有任何带证据的结论，措辞强度核对未执行"),
    GateSpec(
        "level_consistency", "证据等级与信源类型核对",
        lambda d: bool(d.evidences),
        "本案卷没有任何证据节点，等级一致性核对未执行"),
    GateSpec(
        "source_unverified", "信源出处核验",
        lambda d: bool(d.sources),
        "案卷没有信源，出处核验未执行"),
    GateSpec(
        "injection", "指令注入扫描",
        lambda d: any(src.segments for src in d.sources),
        "案卷没有可扫描的段落，注入特征扫描未执行"),
    GateSpec(
        "question", "议题表述聚焦核对",
        lambda d: bool((d.question or "").strip()),
        "议题为空，表述聚焦核对未执行"),
)


def not_evaluated(dossier: Dossier) -> list[dict]:
    """本次未能执行的闸清单（口径见模块文档：只在可证明无对象时记）。"""
    notes: list[dict] = []
    for spec in GATE_SPECS:
        try:
            ran = bool(spec.has_work(dossier))
        except Exception:                     # 探针自身失灵也是「未执行」，不能默认通过
            notes.append({"kind": spec.kind, "label": spec.label,
                          "reason": "准入探针执行异常，按未执行处理"})
            continue
        if not ran:
            notes.append(spec.to_note())
    return notes


def gates_considered() -> set[str]:
    """本层覆盖到的闸 kind（供测试与文档核对，不含 always-on 的少数几类）。"""
    return {s.kind for s in GATE_SPECS}


def not_evaluated_note(notes: list[dict]) -> str:
    """给报告/工作台的一句话文案；空清单返回空串。"""
    if not notes:
        return ""
    kinds = "、".join(f"{n['label']}（{n['kind']}）" for n in notes[:6])
    more = f" 等 {len(notes)} 项" if len(notes) > 6 else ""
    return (f"以下机械核对本次**未能执行**（无可核对象）：{kinds}{more}。"
            f"「无警示」不等于「全部核对通过」")


__all__ = ["GATE_SPECS", "GateSpec", "gates_considered", "not_evaluated",
           "not_evaluated_note"]
