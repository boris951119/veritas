"""语料索引：类型保底、父节限额扩窗、墓碑与切段版本。"""

import json

import pytest

from app.core.bm25 import rank_segments
from app.core.corpus_index import (
    CorpusIndex,
    CorpusIndexError,
    narrow_dossier,
)
from app.core.dup_check import lsh_near_dup_pairs
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.ingest.segment import SEGMENTER_VERSION


def _src(sid: str, title: str, stype: SourceType, texts: list[str]) -> Source:
    src = Source.create(title, stype, id=sid)
    src.segments = [
        Segment(id=f"{sid}#s{i+1}", source_id=sid, text=t, index=i)
        for i, t in enumerate(texts)
    ]
    return src


def test_protected_report_survives_rumor_flood():
    report = _src(
        "OFF", "中国银行2024年年度报告", SourceType.REPORT,
        ["一、分红安排如下，不讨论市场传闻。"],
    )
    index = CorpusIndex(project_id="demo")
    index.upsert_source(report, subjects=["中国银行"], published_at="2024-03-01")
    for i in range(12):
        rumor = _src(
            f"R{i}", f"网传{i}", SourceType.NEWS,
            ["中国银行净利润暴雷" * 30],
        )
        index.upsert_source(rumor)
    result = index.select("中国银行净利润是多少", max_sources=3, material_budget=8000)
    ids = [s.id for s in result.dossier.sources]
    assert "OFF" in ids
    assert result.disclosure["n_library_sources"] == 13
    assert result.disclosure["n_selected_sources"] <= 3
    assert result.disclosure["omitted_sources"] >= 10
    assert "未入候选不等于已审完全库" in result.disclosure["note"]


def test_parent_section_expands_but_not_preamble_or_over_cap():
    src = _src("S", "年报", SourceType.REPORT, [
        "一、地区结构。",
        "华东区域占六成。",
        "二、成本上升很多。",
    ])
    index = CorpusIndex()
    index.upsert_source(src)
    wide = index.select("华东区域", material_budget=8000)
    text = "\n".join(seg.text for s in wide.dossier.sources for seg in s.segments)
    assert "华东区域占六成。" in text
    assert "一、地区结构。" in text
    assert "成本" not in text
    assert wide.disclosure["n_expanded_segments"] >= 1

    huge = "一、地区结构" + "甲" * 80
    fat = _src("F", "年报", SourceType.REPORT, [huge, "华东区域。"])
    index2 = CorpusIndex()
    index2.upsert_source(fat)
    tight = index2.select("华东区域", material_budget=50)
    tight_text = "\n".join(seg.text for s in tight.dossier.sources for seg in s.segments)
    assert "华东" in tight_text
    assert "甲" * 20 not in tight_text


def test_incremental_upsert_tombstone_and_version(tmp_path):
    index = CorpusIndex(project_id="p1")
    index.upsert_source(_src("A", "旧", SourceType.NOTE, ["甲地营收十亿。"]))
    assert any(sid == "A#s1" for sid, _ in index.search("甲地营收"))
    index.upsert_source(_src("A", "新", SourceType.NOTE, ["乙地营收二十亿。"]))
    assert index.segments.get("A#s1") is None or "甲地" not in index.segments["A#s1"].text
    assert any("乙地" in index.segments[sid].text for sid, _ in index.search("乙地营收"))
    index.tombstone("A")
    assert index.search("乙地营收") == []

    path = tmp_path / "idx.json"
    index.upsert_source(_src("B", "留", SourceType.NOTE, ["丙地营收。"]))
    index.save(path)
    loaded = CorpusIndex.load(path)
    assert loaded.segmenter_version == SEGMENTER_VERSION
    assert any(sid.startswith("B#") for sid, _ in loaded.search("丙地"))

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["segmenter_version"] = "old"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(CorpusIndexError):
        CorpusIndex.load(path)


def test_search_scores_match_bm25():
    d = Dossier(question="华东营收", sources=[
        _src("S", "年报", SourceType.REPORT, ["华东营收增长。", "无关的天气。"]),
    ])
    index = CorpusIndex()
    index.upsert_source(d.sources[0])
    got = dict(index.search(d.question))
    base = {sid: sc for sid, sc in rank_segments(d) if sc > 0}
    assert got.keys() == base.keys()
    assert got == base


def test_lsh_finds_copies_not_unrelated():
    rumor = "网传某银行即将暴雷，转发请扩散。" * 8
    items = [(f"C{i}", rumor) for i in range(6)]
    items.append(("U", "今天天气晴朗适合出门散步。"))
    pairs = lsh_near_dup_pairs(items)
    ids = {a for a, b, _ in pairs} | {b for a, b, _ in pairs}
    assert "C0" in ids and "C1" in ids
    assert "U" not in ids


def test_corpus_select_default_threshold_and_force_off(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("VERITAS_CORPUS_SELECT_MIN", raising=False)
    assert Settings.from_env().corpus_select_min_sources == 50
    monkeypatch.setenv("VERITAS_CORPUS_SELECT_MIN", "0")
    assert Settings.from_env().corpus_select_min_sources == 0
    monkeypatch.setenv("VERITAS_CORPUS_SELECT_MIN", "100")
    assert Settings.from_env().corpus_select_min_sources == 100


def test_report_puts_select_scope_up_front_and_small_case_silent():
    from app.core.hashchain import HashChain
    from app.pipeline import render_report_md

    plain = Dossier(question="小案例", sources=[
        _src("A", "简报", SourceType.NEWS, ["没有选料。"]),
    ])
    plain_md = render_report_md(plain, HashChain(), [])
    assert "选料范围" not in plain_md

    note = "库内 40 份 / 80 段，本次纳入 3 份 / 6 段。未入候选不等于已审完全库。"
    selected = Dossier(question="中国银行净利润", sources=[
        _src("OFF", "公告", SourceType.REPORT, ["净利润稳健。"]),
    ])
    selected.accounting["corpus_select"] = {"note": note}
    selected.ingest_notes.append(
        {"file": "", "kind": "corpus_select", "detail": note})
    md = render_report_md(selected, HashChain(), [])
    head, _, tail = md.partition("## 结论")
    assert "选料范围" in head and "库内 40 份" in head and "本次纳入 3 份" in head
    assert "库内 40 份" not in tail


def test_load_case_dossier_skips_index_below_threshold(tmp_path):
    from app.config import Settings
    from app.pipeline import _load_case_dossier

    (tmp_path / "manifest.yaml").write_text(
        "question: 小案\ntitle: 小案\n", encoding="utf-8")
    for i in range(3):
        (tmp_path / f"a{i}.txt").write_text(f"材料{i}", encoding="utf-8")

    out = _load_case_dossier(tmp_path, Settings(corpus_select_min_sources=50))
    assert len(out.sources) == 3
    assert "corpus_select" not in (out.accounting or {})
    assert not (tmp_path / ".corpus").exists()

    forced_off = _load_case_dossier(
        tmp_path, Settings(corpus_select_min_sources=0))
    assert len(forced_off.sources) == 3
    assert "corpus_select" not in (forced_off.accounting or {})


def test_narrow_keeps_triage_and_disclosure():
    d = Dossier(
        question="中国银行净利润",
        title="案",
        sources=[
            _src("OFF", "中国银行公告", SourceType.REPORT, ["净利润稳健。"]),
            _src("N", "帖子", SourceType.WEB, ["别的话题完全无关。"]),
        ],
        triage=[{"file": "a.md", "route": "native", "reason": "ok"}],
    )
    out = narrow_dossier(d, max_sources=5, material_budget=8000)
    assert out.title == "案"
    assert out.triage[0]["file"] == "a.md"
    assert out.accounting["corpus_select"]["n_library_sources"] == 2
    assert any(n.get("kind") == "corpus_select" for n in out.ingest_notes)
