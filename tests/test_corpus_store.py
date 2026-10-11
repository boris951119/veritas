"""磁盘语料库：逐份入库，研判只 hydrate 选中段。"""

import json

import pytest

from app.core.corpus_index import CorpusIndexError
from app.core.corpus_store import DiskCorpusIndex, index_case
from app.core.evidence import Segment, Source, SourceType
from app.ingest.segment import SEGMENTER_VERSION


def _src(sid: str, title: str, stype: SourceType, texts: list[str]) -> Source:
    src = Source.create(title, stype, id=sid)
    src.segments = [
        Segment(id=f"{sid}#s{i+1}", source_id=sid, text=t, index=i)
        for i, t in enumerate(texts)
    ]
    return src


def test_disk_keeps_official_and_reopens(tmp_path):
    db = tmp_path / "index.sqlite"
    index = DiskCorpusIndex.create(db, "demo")
    index.upsert_source(
        _src("OFF", "中国银行2024年年度报告", SourceType.REPORT,
             ["一、分红安排如下，不讨论市场传闻。"]),
        subjects=["中国银行"], published_at="2024-03-01",
    )
    for i in range(6):
        index.upsert_source(_src(
            f"R{i}", f"网传{i}", SourceType.NEWS,
            ["中国银行净利润暴雷" * 20],
        ))
    result = index.select("中国银行净利润是多少", max_sources=2, material_budget=8000)
    assert "OFF" in [s.id for s in result.dossier.sources]
    assert result.disclosure["store"] == "sqlite"
    assert result.disclosure["n_selected_sources"] <= 2
    assert result.disclosure["omitted_sources"] >= 5
    index.close()

    again = DiskCorpusIndex.open(db)
    assert again.live_source_count() == 7
    assert any(sid.startswith("OFF#") for sid, _ in again.search("分红安排"))
    again.tombstone("OFF")
    assert not any(sid.startswith("OFF#") for sid, _ in again.search("分红安排"))
    again.close()

    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE meta SET value='old' WHERE key='segmenter_version'")
    conn.commit()
    conn.close()
    with pytest.raises(CorpusIndexError):
        DiskCorpusIndex.open(db)
    assert SEGMENTER_VERSION == "hier-v1"


def test_disk_parent_expand_respects_cap(tmp_path):
    index = DiskCorpusIndex.create(tmp_path / "a.sqlite")
    index.upsert_source(_src("S", "年报", SourceType.REPORT, [
        "一、地区结构。",
        "华东区域占六成。",
        "二、成本上升很多。",
    ]))
    wide = index.select("华东区域", material_budget=8000)
    text = "\n".join(seg.text for s in wide.dossier.sources for seg in s.segments)
    assert "华东区域占六成。" in text
    assert "一、地区结构。" in text
    assert "成本" not in text
    assert wide.disclosure["n_expanded_segments"] >= 1
    index.close()

    tight = DiskCorpusIndex.create(tmp_path / "b.sqlite")
    tight.upsert_source(_src("F", "年报", SourceType.REPORT, [
        "一、地区结构" + "甲" * 80,
        "华东区域。",
    ]))
    got = tight.select("华东区域", material_budget=50)
    blob = "\n".join(seg.text for s in got.dossier.sources for seg in s.segments)
    assert "华东" in blob
    assert "甲" * 20 not in blob
    tight.close()


def test_index_case_does_not_keep_sources_on_dossier(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        "question: 中国银行净利润是多少\n"
        "sources:\n"
        "  - file: official.md\n"
        "    type: report\n"
        "    title: 中国银行2024年年度报告\n"
        "  - file: rumor.md\n"
        "    type: news\n"
        "    title: 网传\n",
        encoding="utf-8",
    )
    (tmp_path / "official.md").write_text(
        "一、分红安排如下，不讨论市场传闻。\n", encoding="utf-8")
    (tmp_path / "rumor.md").write_text("中国银行净利润暴雷" * 20, encoding="utf-8")
    index, shell = index_case(tmp_path, tmp_path / ".corpus" / "index.sqlite",
                              project_id="case")
    try:
        assert shell.sources == []
        assert shell.question.startswith("中国银行")
        assert index.live_source_count() == 2
        assert any(t["route"] == "native" for t in shell.triage)
        picked = index.select(shell.question, max_sources=1, material_budget=8000)
        assert picked.dossier.sources[0].source_type == SourceType.REPORT
        raw = json.dumps([s.title for s in picked.dossier.sources], ensure_ascii=False)
        assert "中国银行" in raw
    finally:
        index.close()
