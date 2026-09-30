"""资料预算装箱：BM25 精排、跨信源轮转、预算披露——量大输入保产出。"""

import json
from pathlib import Path
from types import SimpleNamespace

from app.agents.prompts import render_segments_block
from app.core.bm25 import rank_segments
from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
)
from app.core.material import pack_material, set_material_budget
from app.pipeline import run_case


def _dossier(question: str, texts: list[str]) -> Dossier:
    d = Dossier(question=question)
    for i, text in enumerate(texts, 1):
        src = Source.create(f"S{i}", SourceType.REPORT, id=f"SRC{i}")
        src.segments.append(Segment(id=f"SRC{i}#s1", source_id=f"SRC{i}",
                                    text=text))
        d.add_source(src)
    return d


# -- BM25 精排 ------------------------------------------------------------------


def test_relevant_segment_ranks_first():
    d = _dossier("客户B的回款率是多少？", [
        "客户B回款512万元，回款率四成。",       # 全部查询词命中
        "今天天气晴朗，适合晾晒衣物。",           # 零命中
        "客户B的合同金额为1280万元。",           # 部分命中
    ])
    ranked = rank_segments(d)
    assert ranked[0][0] == "SRC1#s1"
    assert ranked[1][0] == "SRC3#s1"
    assert ranked[2][1] == 0.0


def test_idf_downweights_ubiquitous_terms():
    """每个段落都有的词（如「公司」）被 IDF 压制，独有词决定排序。"""
    d = _dossier("哪家公司出现了回款异常？", [
        "公司甲的回款出现异常，账期翻倍。",
        "公司乙经营正常，回款按时到账。",
    ])
    ranked = dict(rank_segments(d))
    assert ranked["SRC1#s1"] > ranked["SRC2#s1"]


# -- 装箱器 ---------------------------------------------------------------------


def _wide_dossier() -> Dossier:
    d = Dossier(question="客户B的回款率是多少？")
    texts = {
        "SRC1": ["客户B回款率40%，回款512万元。", "客户B合同金额1280万元。"],
        "SRC2": ["今天天气晴朗，适合晾晒衣物。", "公园里有人遛狗散步。"],
        "SRC3": ["客户B回款率被审计修正为45%。", "审计调整说明附件若干。"],
    }
    for sid, seg_texts in texts.items():
        src = Source.create(sid, SourceType.REPORT, id=sid)
        for j, t in enumerate(seg_texts, 1):
            src.segments.append(Segment(id=f"{sid}#s{j}", source_id=sid, text=t))
        d.add_source(src)
    return d


def test_all_in_when_under_budget():
    d = _wide_dossier()
    pack = pack_material(d, budget_chars=100_000)
    assert not pack["excluded"]
    # SRC2（天气/遛狗段）被相关性分层判零相关整源出局 → 资格线上 4 段
    assert pack["n_total"] == 4
    assert pack["n_selected"] == 4


def test_tiny_budget_keeps_top_and_discloses_rest():
    d = _wide_dossier()
    pack = pack_material(d, budget_chars=40)
    assert pack["selected"]                        # 至少装入最高分段
    assert len(pack["excluded"]) >= 2
    assert all("预算" in e["reason"] for e in pack["excluded"])
    # 确定性：同案卷同预算两次装箱结果一致
    again = pack_material(d, budget_chars=40)
    assert again["selected"] == pack["selected"]
    assert again["excluded"] == pack["excluded"]


def test_round_robin_prevents_single_source_domination():
    """轮转填充：预算跨甲/乙两族信源都有代表，而非高分族独占。"""
    d = _dossier("甲信源乙信源各有何情况？", [
        "甲信源第一段。" + "甲" * 40,
        "甲信源第二段。" + "甲" * 40,
        "乙信源第一段。" + "乙" * 40,
        "乙信源第二段。" + "乙" * 40,
    ])
    pack = pack_material(d, budget_chars=150)
    by_source = {sid.split("#")[0] for sid in pack["selected"]}
    assert {"SRC1", "SRC3"} <= by_source  # 轮转让甲乙两家都有代表


def test_oversize_segment_alone_excluded():
    d = _dossier("客户B回款？", ["客户B回款明细超长。" + "长" * 200])
    pack = pack_material(d, budget_chars=50)
    assert not pack["selected"] and len(pack["excluded"]) == 1


def test_render_respects_packing():
    set_material_budget(40)
    try:
        d = _wide_dossier()
        block = render_segments_block(d)
        pack = pack_material(d)
        for seg_id in pack["selected"]:
            assert seg_id in block
        for e in pack["excluded"]:
            assert e["seg_id"] not in block
    finally:
        set_material_budget(80_000)


# -- 报告披露与管线入链 -----------------------------------------------------------


def test_report_discloses_budget_exclusions():
    set_material_budget(40)
    try:
        d = _wide_dossier()
        con = Conclusion.create("客户B回款率40%", author="a", id="CON1")
        d.conclusions.append(con)
        d.add_evidence(EvidenceNode.create("CON1", "回款率40%", ["SRC1#s1"]))
        from app.core.hashchain import HashChain
        from app.pipeline import render_report_md

        md = render_report_md(d, HashChain(), [])
        assert "因预算未进入研判的段落" in md
    finally:
        set_material_budget(80_000)


def test_pipeline_material_pack_event(tmp_path):
    case_dir = tmp_path / "cases" / "demo"
    case_dir.mkdir(parents=True)
    (case_dir / "manifest.yaml").write_text(
        "question: 客户B的回款情况如何？\n"
        "sources:\n  - file: a.md\n    type: report\n", encoding="utf-8")
    (case_dir / "a.md").write_text("客户B回款512万元。\n", encoding="utf-8")

    PANEL_JSON = json.dumps({"conclusions": [{
        "statement": "客户B回款512万元",
        "evidence": [{"quote": "客户B回款512万元。", "segment_id": "SRC1#s1",
                      "relation": "correlation", "level": "B", "note": "x"}]}]},
        ensure_ascii=False)

    class Fake:
        def chat(self, model, messages, json_mode=False):
            return SimpleNamespace(content=PANEL_JSON)

    from app.config import Settings

    settings = Settings(material_char_budget=10)
    result = run_case(case_dir, out_dir=case_dir / "out", client=Fake(),
                      analysts=[], settings=settings, probe=False)
    events = {r.event: r.payload for r in result.chain.records}
    assert events["material_pack"]["n_excluded"] >= 0
    assert events["material_pack"]["budget"] == 10
    assert result.chain.verify_chain().ok
