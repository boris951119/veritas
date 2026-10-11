"""真实语料选料召回：小合成库冒烟（不依赖桌面全量 PDF）。"""

from pathlib import Path

from app.core.corpus_store import DiskCorpusIndex
from app.core.evidence import Segment, Source, SourceType
from eval.recall_real import find_must_keep, load_questions, score_question


def test_load_questions_has_twenty_to_fifty():
    qs = load_questions()
    assert 20 <= len(qs) <= 50


def test_score_question_on_tiny_indexed_corpus(tmp_path: Path):
    db = tmp_path / "idx.sqlite"
    index = DiskCorpusIndex.create(db, project_id="南山铝业")
    keep = Source.create("南山铝业2024年年度报告摘要", SourceType.REPORT, id="KEEP")
    keep.segments = [
        Segment(id="KEEP#s1", source_id="KEEP", index=0,
                text="累计现金分红比例为40.92%，其余说明从略。"),
    ]
    noise = Source.create("地铁花期通知", SourceType.REPORT, id="NOISE")
    noise.segments = [
        Segment(id="NOISE#s1", source_id="NOISE", index=0,
                text="本市公园花期已过，与分红无关。"),
    ]
    index.upsert_source(keep, path="年报.pdf", subjects=["南山铝业"])
    index.upsert_source(noise, path="地铁.pdf", subjects=[])
    # 再灌一些无关正式件，凑选料竞争
    for i in range(8):
        s = Source.create(f"无关公告{i}", SourceType.REPORT, id=f"U{i}")
        s.segments = [Segment(
            id=f"U{i}#s1", source_id=f"U{i}", index=0,
            text=f"第{i}号园区绿化维护通知，无财务数字。")]
        index.upsert_source(s, path=f"u{i}.pdf")
    index.close()

    must = find_must_keep(
        db, metric="累计现金分红比例", value="40.92%", company="南山铝业",
        question="南山铝业2024年：累计现金分红比例为多少")
    assert "KEEP" in must

    row = score_question(
        {
            "company": "南山铝业",
            "question": "南山铝业2024年：累计现金分红比例为多少",
            "metric": "累计现金分红比例",
            "value": "40.92%",
        },
        db,
        max_sources=3,
    )
    assert row["ok"] is True
    assert "KEEP" in row["hit"]
