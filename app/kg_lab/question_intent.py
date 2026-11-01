"""R20：问句意图——裁决型 vs 一般核验。

裁决型（哪一口径成立／是A还是B）→ 召回走对立选项＋证据，不做纯语义扩写。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.kg_lab.event_frame import EventFrame, extract_event_frame, option_paraphrases

_ADJUDICATE_CUES = (
    "还是", "哪一方", "哪一口径", "哪方", "以哪", "为准", "站得住",
    "能否以", "是否属", "是否真", "哪一说法", "哪一",
)
_EVIDENCE_CUES = (
    "证实", "证据", "通报", "原话", "监控", "档案", "数据", "调查",
)


@dataclass
class QuestionIntent:
    kind: str  # adjudicate | verify | open
    adjudication: bool
    options: list[str] = field(default_factory=list)
    evidence_first: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_intent(question: str, frame: EventFrame | None = None) -> QuestionIntent:
    q = question or ""
    frame = frame or extract_event_frame(q)
    opts = list(frame.options)
    has_or = "还是" in q or bool(re.search(r"是.+还是", q))
    cue_hit = any(c in q for c in _ADJUDICATE_CUES)
    evid = any(c in q for c in _EVIDENCE_CUES)
    if (has_or and len(opts) >= 2) or (cue_hit and opts):
        return QuestionIntent(
            kind="adjudicate",
            adjudication=True,
            options=opts,
            evidence_first=True,
            notes=["opposing_options", "evidence_not_semantic"],
        )
    if cue_hit or evid:
        return QuestionIntent(
            kind="verify",
            adjudication=False,
            options=opts,
            evidence_first=evid,
            notes=["verify_or_evidence"],
        )
    return QuestionIntent(kind="open", adjudication=False, options=opts, evidence_first=False)


def adjudication_queries(question: str, frame: EventFrame | None = None) -> list[dict[str, str]]:
    """裁决型专用检索视图：对立选项＋证据／时点，不含原因类语义扩写。"""
    frame = frame or extract_event_frame(question)
    intent = classify_intent(question, frame)
    actors = " ".join(frame.actors[:3])
    times = " ".join(frame.time_cues[:4])
    views: list[dict[str, str]] = []
    if not intent.adjudication and not frame.options:
        return views
    for i, opt in enumerate(frame.options[:3]):
        paras = " ".join(option_paraphrases(opt)[:4])
        views.append({
            "id": f"adj_opt{i}",
            "view": "conclusion",
            "query": f"{actors} {paras}".strip(),
        })
        views.append({
            "id": f"adj_opt_core{i}",
            "view": "conclusion",
            "query": " ".join(option_paraphrases(opt)[:3]),
        })
    if len(frame.options) >= 2:
        views.append({
            "id": "adj_or",
            "view": "conclusion",
            "query": f"{actors} {frame.options[0]} 还是 {frame.options[1]} 口径".strip(),
        })
    views.append({
        "id": "adj_evidence",
        "view": "evidence",
        "query": (
            f"{actors} {times} 通报 证实 证据 监控 档案 调查 回应 "
            f"{' '.join(frame.evidence_cues[:3])}"
        ).strip(),
    })
    if frame.time_cues:
        views.append({
            "id": "adj_time",
            "view": "evidence",
            "query": f"{actors} {times} {' '.join(frame.options[:1])} 通稿 监控".strip(),
        })
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for v in views:
        qq = " ".join((v.get("query") or "").split())
        if len(qq) < 4 or qq in seen:
            continue
        seen.add(qq)
        out.append({"id": v["id"], "view": v["view"], "query": qq})
    return out
