"""输入生命周期三机制：事实对撞台账 / 时序核对 / 相关性分层。"""

import re

from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
)
from app.core.fact_ledger import (
    _scan, extract_facts, facts_block, find_collisions, format_dropped_disclosure,
)
from app.core.relevance import classify_sources, unadopted_sources
from app.core.temporal_check import audit_temporal
from app.core.hashchain import HashChain
from app.pipeline import render_report_md


def _seg(d: Dossier, source_id: str, text: str, source_type=SourceType.REPORT,
         meta: dict | None = None) -> Source:
    src = Source.create(source_id, source_type, id=source_id, meta=meta or {})
    src.segments.append(Segment(id=f"{source_id}#s1", source_id=source_id,
                                text=text))
    d.add_source(src)
    return src


# -- 事实对撞台账 ---------------------------------------------------------------


def _two_source_collision_dossier() -> Dossier:
    d = Dossier(question="客户B的回款情况如何？")
    _seg(d, "SRC1", "客户B回款率40%，回款正常。", meta={"published_at": "2025-06"})
    _seg(d, "SRC2", "客户B回款率45%，回款正常。", meta={"published_at": "2026-03"})
    return d


def test_cross_source_collision_detected():
    d = _two_source_collision_dossier()
    collisions = find_collisions(d)
    assert len(collisions) == 1
    c = collisions[0]
    assert (c.entity, c.metric) == ("客户b", "回款率") or c.entity == "客户B"
    assert c.cross_source
    assert {f.raw for f in c.facts} == {"40%", "45%"}


def test_different_entities_do_not_collide():
    d = Dossier(question="回款情况")
    _seg(d, "SRC1", "客户B回款率40%。")
    _seg(d, "SRC2", "客户C回款率45%。")
    assert find_collisions(d) == []


def test_unit_scaling_prevents_false_collision():
    d = Dossier(question="回款情况")
    _seg(d, "SRC1", "客户B累计回款512万元。")
    _seg(d, "SRC2", "客户B累计回款0.0512亿元。")
    assert find_collisions(d) == []


def test_years_are_not_facts():
    d = Dossier(question="营收情况")
    _seg(d, "SRC1", "2026年3月，客户B营收1200万元。")
    facts = extract_facts(d)
    assert all(f.metric != "" for f in facts)
    assert not any(f.raw.startswith("2026") for f in facts)


def test_facts_block_injected_only_with_collisions():
    clean = Dossier(question="回款情况")
    _seg(clean, "SRC1", "客户B回款率40%。")
    assert facts_block(clean) == ""
    d = _two_source_collision_dossier()
    block = facts_block(d)
    assert "数字冲突" in block and "SRC1" in block and "SRC2" in block


def test_split_metric_number_counts_no_metric_and_stays_out():
    """指标词与数字分到两段 → no_metric≥1，且该数不入 facts（C-2 主靶复现）。"""
    d = Dossier(question="伤亡情况如何？")
    src = Source.create("SRC1", SourceType.NEWS, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text="事故造成死亡", index=0))
    src.segments.append(Segment(
        id="SRC1#s2", source_id="SRC1", text="12人，另有伤者。", index=1))
    d.add_source(src)
    facts, stats = _scan(d)
    assert stats["dropped"]["no_metric"] >= 1
    assert not any(f.raw == "12" or abs(f.value - 12) < 1e-9 for f in facts)
    assert stats["n_numbers"] == stats["n_facts"] + sum(stats["dropped"].values())
    # 报告出口能读到「未采信数字分类计数」
    d.accounting["fact_ledger_stats"] = stats
    md = render_report_md(d, HashChain(), [])
    assert "未采信数字分类计数" in md
    assert "no_metric" in md


def test_dropped_reasons_year_clause_ordinal_are_disjoint():
    """年份 / 条款引用 / 序数 各进自己的桶，不许混类。"""
    d = Dossier(question="合同进度")
    _seg(d, "Y", "2026年发布。")                 # → year
    _seg(d, "C", "合同第3.1条约定付款。")         # → clause_ref（after=条）
    _seg(d, "O", "第3次会议召开。")               # → ordinal（after=次，非条款尾）
    facts, stats = _scan(d)
    dropped = stats["dropped"]
    assert dropped["year"] >= 1
    assert dropped["clause_ref"] >= 1
    assert dropped["ordinal"] >= 1
    # 守恒：每个数字恰好进一个桶或入台账
    assert stats["n_numbers"] == stats["n_facts"] + sum(dropped.values())
    # 三个种子数字不得串桶：year 段只有年份、clause 段只有条款数、ordinal 段只有序数
    assert dropped["year"] == 1
    assert dropped["clause_ref"] == 1
    assert dropped["ordinal"] == 1
    assert facts == []


def test_all_numbers_facted_means_dropped_sum_zero():
    """全部数字正常入台账时 dropped 合计为 0（防空转假披露）。"""
    d = Dossier(question="回款与营收")
    _seg(d, "SRC1", "客户B回款率40%。")
    _seg(d, "SRC2", "客户C营收1200万元。")
    facts, stats = _scan(d)
    assert stats["n_facts"] >= 2
    assert stats["n_numbers"] == stats["n_facts"]
    assert sum(stats["dropped"].values()) == 0
    assert set(stats["dropped"]) == {
        "year", "clause_ref", "ordinal", "no_metric", "metric_rejected", "entity_stop",
    }
    assert "未采信数字分类计数" in format_dropped_disclosure(stats)


# -- 时序核对（时效闸 + as-of 闸） -------------------------------------------------


def _stale_dossier(cited_old: bool, anchor_time: bool) -> Dossier:
    d = _two_source_collision_dossier()
    con = Conclusion.create(
        "客户B回款率40%" + ("，截至2025年报" if anchor_time else ""),
        author="a", id="CON1")
    d.conclusions.append(con)
    _seg(d, "SRC3", "客户B经营平稳。")  # 供引用的非对撞段落
    d.add_evidence(EvidenceNode.create(
        "CON1", "客户B回款率40%，回款正常。" if cited_old
        else "客户B回款率45%，回款正常。",
        ["SRC1#s1"] if cited_old else ["SRC2#s1"], author="a"))
    return d


def test_stale_flag_when_citing_only_old_source():
    d = _stale_dossier(cited_old=True, anchor_time=True)
    flags = [f for f in audit_temporal(d) if f["kind"] == "stale"]
    assert flags and "SRC2(2026-03)" in flags[0]["detail"]


def test_no_stale_flag_when_citing_newest():
    d = _stale_dossier(cited_old=False, anchor_time=True)
    assert not [f for f in audit_temporal(d) if f["kind"] == "stale"]


def test_as_of_flag_without_time_anchor():
    d = _stale_dossier(cited_old=False, anchor_time=False)
    flags = [f for f in audit_temporal(d) if f["kind"] == "as_of"]
    assert flags and "未锚定时点" in flags[0]["detail"]


def test_undated_sources_produce_no_as_of_flags():
    d = Dossier(question="Q")
    _seg(d, "SRC1", "客户B回款率40%。")  # 无时点
    con = Conclusion.create("客户B回款率40%", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "回款率40%", ["SRC1#s1"]))
    assert audit_temporal(d) == []


# -- 相关性分层 ------------------------------------------------------------------


def _mixed_dossier() -> Dossier:
    d = Dossier(question="固态电池2030年前能否规模上车？")
    _seg(d, "SRC1", "固态电池的中试良率尚不足百分之四十，装车验证推进中。")
    _seg(d, "SRC2", "固态电池相关专利数量逐年上升，产业化路径逐步清晰。")
    _seg(d, "SRC3", "红烧肉的做法：五花肉焯水后加冰糖炒糖色，小火慢炖四十分钟。")
    return d


def test_irrelevant_source_classified_zero():
    # C-70：软闸默认开＝自动路径不再产出 zero；红烧肉档改标 low（进候选但降权）
    # 改前断言 levels["SRC3"]=="zero"；现＝"low"。关闸回归见 test_c70_*。
    from app.core.relevance import set_relevance_soft_gate
    set_relevance_soft_gate(True)
    levels = {s["source_id"]: s["level"] for s in classify_sources(_mixed_dossier())}
    assert levels["SRC3"] == "low"
    assert levels["SRC1"] == "high"


def test_weakly_related_source_classified_low():
    d = Dossier(question="固态电池2030年前能否规模上车？")
    _seg(d, "SRC1", "固态电池的中试良率尚不足百分之四十。")
    _seg(d, "SRC2", "锂价今夏小幅波动，下游排产平淡。")  # 仅「电池」级弱重合
    levels = {s["source_id"]: s["level"] for s in classify_sources(d)}
    assert levels["SRC2"] in ("low", "zero")


def test_zero_source_excluded_from_prompt_but_disclosed():
    # C-70：软闸开＝低相关仍进提示词（标降权），不再整源出局；
    # unadopted 只剩人工 exclude（本夹具无）⇒ 空。改前：SRC3 不进 block、进 unadopted。
    from app.agents.prompts import render_segments_block
    from app.core.relevance import set_relevance_soft_gate
    set_relevance_soft_gate(True)
    d = _mixed_dossier()
    block = render_segments_block(d)
    assert "SRC3" in block and "红烧肉" in block
    assert "低相关" in block
    assert "SRC1" in block
    unadopted = unadopted_sources(d)
    assert unadopted == []


def test_no_question_entities_means_no_judgment():
    d = Dossier(question="请分析。")
    _seg(d, "SRC1", "任意内容。")
    assert all(s["level"] == "high" for s in classify_sources(d))


# -- 报告披露 -------------------------------------------------------------------


def test_report_discloses_collisions_and_unadopted():
    d = _mixed_dossier()
    _seg(d, "SRC4", "客户B回款率40%。", meta={"published_at": "2025-06"})
    _seg(d, "SRC5", "客户B回款率45%。", meta={"published_at": "2026-03"})
    con = Conclusion.create("截至2025年报，客户B回款率40%", author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", "客户B回款率40%。",
                                       ["SRC4#s1"], author="a"))
    md = render_report_md(d, HashChain(), [])
    assert "资料内数字冲突" in md and "跨信源" in md
    # C-70：软闸开＝「未采信」改聚合披露（人工排除／零重合／低相关档），
    # 不再逐条列出 SRC3；改前断言 "SRC3" in md。
    assert "未采信信源" in md
    assert "低相关档" in md
    assert "人工排除" in md
    stale = [f for f in audit_temporal(d) if f["kind"] == "stale"]
    assert stale  # 时效闸也覆盖该场景


# -- C-4 报告章名三分支 ---------------------------------------------------------


def test_c4_chapter_with_collisions_keeps_conflict_title():
    """有对撞 → 章名保持「资料内数字冲突」。"""
    d = _two_source_collision_dossier()
    md = render_report_md(d, HashChain(), [])
    assert "## 资料内数字冲突（事实层对撞）" in md
    assert "跨信源" in md
    assert "未采信数字分类计数" in md


def test_c4_chapter_drops_only_uses_non_conflict_title():
    """零对撞但有未采信数字 → 章名改「台账未采信…」，不得出现冲突字样。"""
    d = Dossier(question="伤亡")
    src = Source.create("SRC1", SourceType.NEWS, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text="事故造成死亡", index=0))
    src.segments.append(Segment(
        id="SRC1#s2", source_id="SRC1", text="12人。", index=1))
    d.add_source(src)
    facts, stats = _scan(d)
    assert sum(stats["dropped"].values()) >= 1
    assert find_collisions(d, facts=facts) == []
    d.accounting["fact_ledger_stats"] = stats
    md = render_report_md(d, HashChain(), [])
    assert "## 台账未采信数字分类计数" in md
    assert "资料内数字冲突" not in md
    assert "冲突" not in md


def test_c4_chapter_absent_when_no_collision_no_drop():
    """零对撞且零未采信 → 整章不打。"""
    d = Dossier(question="回款")
    _seg(d, "SRC1", "客户B回款率40%。")
    _, stats = _scan(d)
    assert sum(stats["dropped"].values()) == 0
    assert find_collisions(d) == []
    d.accounting["fact_ledger_stats"] = stats
    md = render_report_md(d, HashChain(), [])
    assert "资料内数字冲突" not in md
    assert "台账未采信数字分类计数" not in md
