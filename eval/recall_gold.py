"""选料金标（零 LLM）。

量的是「该留下的信源有没有进本次案卷」，不是模型答得对不对。
三条正例加一条占席反例：谣言淹没、答案在节内正文、实体只在标题、
不相关正式文件不得占满名额。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.core.corpus_store import DiskCorpusIndex
from app.core.evidence import Segment, Source, SourceType

_TYPES = {
    "report": SourceType.REPORT,
    "news": SourceType.NEWS,
    "note": SourceType.NOTE,
    "paper": SourceType.PAPER,
}


def _source(sid: str, title: str, kind: str, texts: list[str],
            subjects: list[str] | None = None) -> tuple[Source, list[str]]:
    src = Source.create(title, _TYPES[kind], id=sid)
    src.segments = [
        Segment(id=f"{sid}#s{i+1}", source_id=sid, text=t, index=i)
        for i, t in enumerate(texts)
    ]
    return src, list(subjects or [])


def gold_cases() -> list[dict]:
    """固定样例。relevant_ids 必须出现在选中信源里。"""
    off, off_sub = _source(
        "OFF", "中国银行2024年年度报告", "report",
        ["一、分红安排如下，不讨论市场传闻。"],
        ["中国银行"],
    )
    rumors = [
        _source(f"R{i}", f"网传{i}", "news", ["中国银行净利润暴雷" * 12])[0]
        for i in range(8)
    ]
    section, _ = _source("SEC", "年报摘录", "report", [
        "一、地区结构。",
        "华东区域占六成。",
        "二、成本上升很多。",
    ])
    titled, titled_sub = _source(
        "TITLE", "中国银行2024年年度报告", "report",
        ["一、分红安排如下，正文不再重复公司名。"],
        ["中国银行"],
    )
    titled_rumors = [
        _source(f"N{i}", f"帖子{i}", "news", ["中国银行净利润暴雷" * 12])[0]
        for i in range(6)
    ]
    answer, _ = _source(
        "ANS", "仓储月报", "news",
        ["华东仓储吞吐量达到十二万吨。"],
    )
    officials = [
        _source(f"U{i}", f"地铁通知{i}", "report", ["本市公园花期已过，与问句无关。"])[0]
        for i in range(5)
    ]
    return [
        {
            "id": "rumor-flood",
            "question": "中国银行净利润是多少",
            "max_sources": 3,
            "relevant_ids": ["OFF"],
            "sources": [(off, off_sub), *[(s, []) for s in rumors]],
        },
        {
            "id": "section-body",
            "question": "华东区域",
            "max_sources": 5,
            "relevant_ids": ["SEC"],
            "must_contain": ["华东区域占六成。", "一、地区结构。"],
            "must_lack": ["成本"],
            "sources": [(section, [])],
        },
        {
            "id": "entity-in-title",
            "question": "中国银行净利润是多少",
            "max_sources": 2,
            "relevant_ids": ["TITLE"],
            "sources": [(titled, titled_sub), *[(s, []) for s in titled_rumors]],
        },
        {
            "id": "unrelated-officials",
            "question": "华东仓储吞吐量",
            "max_sources": 2,
            "relevant_ids": ["ANS"],
            "crowd_ids": [s.id for s in officials],
            "sources": [(answer, []), *[(s, []) for s in officials]],
        },
    ]


def score_case(case: dict, db_path: Path) -> dict:
    index = DiskCorpusIndex.create(db_path, case["id"])
    try:
        for src, subjects in case["sources"]:
            index.upsert_source(src, subjects=subjects)
        result = index.select(
            case["question"],
            max_sources=case["max_sources"],
            material_budget=8000,
        )
    finally:
        index.close()
    selected = [s.id for s in result.dossier.sources]
    relevant = list(case["relevant_ids"])
    hit = [sid for sid in relevant if sid in selected]
    text = "\n".join(
        seg.text for src in result.dossier.sources for seg in src.segments)
    missing_bits = [b for b in case.get("must_contain") or [] if b not in text]
    leaked = [b for b in case.get("must_lack") or [] if b in text]
    crowd = set(case.get("crowd_ids") or [])
    crowd_n = sum(1 for sid in selected if sid in crowd)
    recall = (len(hit) / len(relevant)) if relevant else 1.0
    return {
        "id": case["id"],
        "recall": recall,
        "hit": hit,
        "selected": selected,
        "missing_bits": missing_bits,
        "leaked": leaked,
        "crowd_n": crowd_n,
        "max_sources": case["max_sources"],
        "ok": (recall == 1.0 and not missing_bits and not leaked
               and crowd_n < case["max_sources"]),
    }


def run_recall() -> list[dict]:
    cases = gold_cases()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        return [score_case(case, root / f"{case['id']}.sqlite") for case in cases]
