"""C-70 双轴相关性软闸：资格一根轴；分数只出标签／文案／披露。

R-C70-1：四颗行为型守护格（K3／K9／K10／K11）；变异只落 tmp 副本（#199）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, Segment, Source, SourceType,
)
from app.core.material import pack_material, rank_segments
from app.core.relevance import (
    W_MATCH, W_REL, classify_sources, match_score_source, match_vocab,
    relevance_aggregate, relevance_soft_gate_enabled, set_relevance_soft_gate,
)

_ROOT = Path(__file__).resolve().parents[1]


def _load_mutated_copy(name: str, old: str, new: str, tmp_path: Path) -> types.ModuleType:
    """源文件字节复制进 tmp_path → replace → 独立加载；真树零写。"""
    raw = (_ROOT / name).read_text(encoding="utf-8")
    assert old in raw, f"变异针漂移：{name!r} 找不到 old 字面"
    dest = tmp_path / name.replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(raw.replace(old, new, 1), encoding="utf-8")
    mod_name = f"c70r1_mut_{dest.stem}_{abs(hash(new)) & 0xFFFF:x}"
    spec = importlib.util.spec_from_file_location(mod_name, dest)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _reset_soft_gate():
    set_relevance_soft_gate(True)
    yield
    set_relevance_soft_gate(True)


def _src(sid: str, text: str, **meta) -> Source:
    s = Source.create(sid, SourceType.REPORT, id=sid)
    s.meta.update(meta)
    s.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text, index=0))
    return s


def _src_multi(sid: str, texts: list[str]) -> Source:
    s = Source.create(sid, SourceType.REPORT, id=sid)
    for i, t in enumerate(texts):
        s.segments.append(Segment(id=f"{sid}#s{i+1}", source_id=sid, text=t, index=i))
    return s


# ---- 判据 b：低分不得变相出局 ----
def test_c70_b_zero_scores_still_eligible():
    """s_rel=0 且 s_match=0 的信源，软闸开时其段必须仍进 eligible。

    刀：eligible 过滤里加 `score==0 or s_match==0 ⇒ skip` ⇒ 本格红。
    """
    d = Dossier(question="固态电池2030年前能否规模上车？")
    d.add_source(_src("HOT", "固态电池规模上车进展顺利，2030年前产能爬坡。"))
    d.add_source(_src("COLD", "红烧肉焯水后加冰糖炒糖色，小火慢炖四十分钟。"))
    set_relevance_soft_gate(True)
    rows = {r["source_id"]: r for r in classify_sources(d)}
    assert rows["COLD"]["level"] == "low"
    assert float(rows["COLD"].get("s_rel") or 0) == 0.0
    assert float(rows["COLD"].get("s_match") or 0) == 0.0
    pack = pack_material(d, budget_chars=100_000)
    cold_segs = {seg.id for seg in d.sources[1].segments}
    assert cold_segs & set(pack["selected"]), (
        f"低分源应进 eligible/装箱，selected={pack['selected']}")


# ---- 判据 c：篇分＝各段 max ----
def test_c70_c_match_score_is_segment_max_not_mean():
    """同一篇一段命中 3/4、另一段 0/4 ⇒ s_match=0.75；篇平均≈0.375 必须红。"""
    # 词集人为构造：四个实体词
    d = Dossier(question="甲乙丙丁各方进展如何？")
    vocab = match_vocab(d.question)
    # 确保词集至少 4；若抽不够则用显式夹具词
    if len(vocab) < 4:
        vocab = ["甲", "乙", "丙", "丁"]
    src = _src_multi("S1", [
        "这里同时出现甲、乙、丙三个主体的进展。",  # 3/4
        "完全无关的天气与食谱文字。",            # 0/4
    ])
    # 直接测 match_score_source
    score = match_score_source(src, vocab[:4] if len(vocab) >= 4 else vocab)
    # 若词集不是甲乙丙丁，用强制词集
    score = match_score_source(src, ["甲", "乙", "丙", "丁"])
    assert score == 0.75, score
    mean = (0.75 + 0.0) / 2
    assert score != pytest.approx(mean)


# ---- 判据 d：排序没动 ----
def test_c70_d_rank_segments_unaffected_by_soft_gate():
    """开关开／关：rank_segments 输出序列逐位相同（只允许 eligible 变）。

    刀：把 score 乘进 BM25 ⇒ 本格红。
    """
    d = Dossier(question="客户B的回款率是多少？")
    d.add_source(_src("A", "客户B回款率40%，回款正常。"))
    d.add_source(_src("B", "客户B回款率被审计修正为45%。"))
    d.add_source(_src("C", "今天天气晴朗，适合晾晒衣物。"))
    set_relevance_soft_gate(False)
    rank_off = rank_segments(d)
    set_relevance_soft_gate(True)
    rank_on = rank_segments(d)
    assert rank_off == rank_on


# ---- 判据 g／默认值 ----
def test_c70_d_defaults_soft_gate_on():
    """刀：把 Settings.relevance_soft_gate 默认翻成 False ⇒ 本格红。"""
    s = Settings()
    assert s.relevance_soft_gate is True
    # C-69 两开关仍必须 False（本单不许顺手改）
    assert s.source_time_unified is False
    assert s.ledger_time_class is False


def test_c70_g_soft_gate_off_matches_legacy_levels():
    """开关关：classify_sources level／reason 与改前路径一致（合成夹具）。"""
    d = Dossier(question="固态电池2030年前能否规模上车？")
    d.add_source(_src("S1", "固态电池的中试良率尚不足百分之四十。"))
    d.add_source(_src("S2", "红烧肉焯水后加冰糖炒糖色。"))
    set_relevance_soft_gate(False)
    rows = classify_sources(d)
    by = {r["source_id"]: r for r in rows}
    assert by["S1"]["level"] == "high"
    assert by["S2"]["level"] == "zero"
    assert "零重合" in by["S2"]["reason"]
    assert "s_rel" not in by["S2"]  # 关闸不附新键


def test_c70_no_entity_still_all_high():
    """件①：议题抽不出实体 ⇒ 全 high（软闸开／关都守住）。"""
    d = Dossier(question="请分析。")
    d.add_source(_src("A", "今日晴转多云。"))
    d.add_source(_src("B", "红烧肉小火慢炖。"))
    for on in (True, False):
        set_relevance_soft_gate(on)
        rows = classify_sources(d)
        assert all(r["level"] == "high" for r in rows)


def test_c70_human_exclude_still_zero():
    """zero 只留人工 exclude；include 恒 high。"""
    d = Dossier(question="客户B的回款情况如何？")
    hot = _src("HOT", "客户B回款率40%。")
    cold = _src("COLD", "今天天气晴朗。")
    hot.relevance_override = "exclude"
    cold.relevance_override = "include"
    d.add_source(hot)
    d.add_source(cold)
    set_relevance_soft_gate(True)
    by = {r["source_id"]: r for r in classify_sources(d)}
    assert by["HOT"]["level"] == "zero"
    assert "人工强制排除" in by["HOT"]["reason"]
    assert by["COLD"]["level"] == "high"
    assert "人工强制纳入" in by["COLD"]["reason"]


def test_c70_aggregate_line_no_ratio_words():
    """聚合披露一行在场；禁用漏检率／召回率／覆盖率。"""
    d = Dossier(question="固态电池2030年前能否规模上车？")
    d.add_source(_src("S1", "固态电池规模上车。"))
    d.add_source(_src("S2", "红烧肉焯水。"))
    set_relevance_soft_gate(True)
    agg = relevance_aggregate(d)
    line = agg["line"]
    assert "人工排除" in line and "低相关档" in line
    for banned in ("漏检率", "召回率", "覆盖率"):
        assert banned not in line


def test_c70_empty_box_fallback_branch_intact():
    """material.py 全案 zero⇒空箱回退分支语义仍在（人工全 exclude 时触发）。"""
    d = Dossier(question="客户B的回款情况如何？")
    a = _src("A", "客户B回款率40%。")
    b = _src("B", "客户B回款率50%。")
    a.relevance_override = "exclude"
    b.relevance_override = "exclude"
    d.add_source(a)
    d.add_source(b)
    set_relevance_soft_gate(True)
    pack = pack_material(d, budget_chars=100_000)
    # 回退分支应让段重新进箱（否则 selected 空）
    assert pack["n_selected"] >= 1


def test_c70_weights_are_half():
    assert W_REL == 0.5 and W_MATCH == 0.5


def test_c70_true_ref_probe_stem():
    """§5 第 26 条：探针被本文件真引用（只写 stem）。"""
    import scripts.probe_c70_relevance_soft as probe

    assert callable(probe._measure_arm)
    assert callable(probe.main)


# ---- R-C70-1 四颗行为型守护格（K3／K9／K10／K11）---------------------------


def _r1_pack_dossier() -> tuple[Dossier, int]:
    """低分源 BM25 略高、高分源 BM25 略低；预算只装一段。

    score 由 monkeypatch classify 钉死（0.05 vs 0.95），与正文 BM25 脱钩，
    专测「装箱消费面不看 score」。
    """
    q = "甲乙丙丁各方进展如何？"
    lo_text = "甲乙丙丁各方进展如何？甲乙丙丁甲乙丙丁。"
    hi_text = "甲乙" + ("红烧肉炖煮。" * 4)
    while len(hi_text) < len(lo_text):
        hi_text += "。"
    while len(lo_text) < len(hi_text):
        lo_text += "。"
    d = Dossier(question=q)
    d.add_source(_src("LO", lo_text))
    d.add_source(_src("HI", hi_text))
    return d, max(len(lo_text), len(hi_text))


def _r1_fake_classify(_dossier: Dossier) -> list[dict]:
    return [
        {"source_id": "LO", "title": "LO", "level": "low", "score": 0.05,
         "s_rel": 0.0, "s_match": 0.0, "reason": "low"},
        {"source_id": "HI", "title": "HI", "level": "high", "score": 0.95,
         "s_rel": 0.9, "s_match": 0.9, "reason": ""},
    ]


def test_c70_r1_pack_ignores_relevance_score(monkeypatch, tmp_path):
    """件①／K3：装箱取舍不看 relevance score。

    正向＝软闸开时选中 BM25 高的 LO#s1。
    刀＝tmp 副本把 score 加进 pack 消费的分数 ⇒ 选段翻成 HI#s1。
    """
    import app.core.material as mat
    from app.core.relevance import classify_sources as real_cls

    set_relevance_soft_gate(True)
    d, budget = _r1_pack_dossier()
    monkeypatch.setattr(mat, "classify_sources", _r1_fake_classify)
    pack = pack_material(d, budget_chars=budget)
    assert pack["selected"] == {"LO#s1"}, pack["selected"]

    old = (
        "    scores = dict(rank_segments(dossier, queries=queries)\n"
        "                  if queries else rank_segments(dossier))\n"
    )
    new = (
        "    scores = dict(rank_segments(dossier, queries=queries)\n"
        "                  if queries else rank_segments(dossier))\n"
        "    for _sid, _seg in eligible:\n"
        "        _sc = float((relevance.get(_sid) or {}).get('score') or 0.0)\n"
        "        scores[_seg] = scores.get(_seg, 0.0) + 100.0 * _sc"
        "  # R-C70-1 K3\n"
    )
    poisoned = _load_mutated_copy("app/core/material.py", old, new, tmp_path)
    poisoned.classify_sources = _r1_fake_classify
    flipped = poisoned.pack_material(d, budget_chars=budget)
    assert flipped["selected"] == {"HI#s1"}, flipped["selected"]
    # 真树未动
    monkeypatch.setattr(mat, "classify_sources", _r1_fake_classify)
    assert pack_material(d, budget_chars=budget)["selected"] == {"LO#s1"}
    monkeypatch.setattr(mat, "classify_sources", real_cls)


def test_c70_r1_match_vocab_includes_question_nums(tmp_path):
    """件②／K9：s_match 词集必须含议题数字原串。

    议题含「45%」、正文只有该数字 ⇒ s_match>0；
    刀＝`for num in []` ⇒ s_match==0。
    """
    set_relevance_soft_gate(True)
    q = "客户B回款率是否达到45%？"
    src = _src("S", "最新报表写明 45%。")
    vocab = match_vocab(q)
    assert "45%" in vocab
    assert match_score_source(src, vocab) > 0

    old = "    for num in extract_nums(question or \"\"):\n"
    new = "    for num in []:  # R-C70-1 K9\n"
    poisoned = _load_mutated_copy("app/core/relevance.py", old, new, tmp_path)
    broken_vocab = poisoned.match_vocab(q)
    assert "45%" not in broken_vocab
    assert poisoned.match_score_source(src, broken_vocab) == 0.0
    # 真树未动
    assert match_score_source(src, match_vocab(q)) > 0


def test_c70_r1_soft_off_render_lists_zero_sources(tmp_path):
    """件③／K10：关闸臂「未采信信源」必须逐条列举 zero，不得走聚合行。

    刀＝把 soft_on 写死 True ⇒ SRC3 名消失、聚合行出现。
    """
    from app.pipeline import _render_excluded_sources

    set_relevance_soft_gate(False)
    d = Dossier(question="固态电池2030年前能否规模上车？")
    d.add_source(_src("SRC1", "固态电池规模上车进展顺利。"))
    d.add_source(_src("SRC3", "红烧肉焯水后加冰糖炒糖色。"))
    assert classify_sources(d)[1]["level"] == "zero"

    lines: list[str] = []
    _render_excluded_sources(lines, d)
    md = "\n".join(lines)
    assert "SRC3" in md
    assert "低相关档" not in md

    old = "    soft_on = relevance_soft_gate_enabled()\n"
    new = "    soft_on = True  # R-C70-1 K10\n"
    poisoned = _load_mutated_copy("app/pipeline.py", old, new, tmp_path)
    broken_lines: list[str] = []
    poisoned._render_excluded_sources(broken_lines, d)
    broken = "\n".join(broken_lines)
    assert "SRC3" not in broken
    assert "低相关档" in broken
    # 真树未动
    again: list[str] = []
    _render_excluded_sources(again, d)
    assert "SRC3" in "\n".join(again)


def test_c70_r1_aggregate_counts_are_numeric(tmp_path):
    """件④／K11：聚合行 N／M／K 数值断言（人工 1／零重合 1／低相关 2）。

    刀＝n_low 条件扩成 low|high ⇒ n_low 涨、整行字面红。
    """
    set_relevance_soft_gate(True)
    d = Dossier(question="客户B的回款率是多少？")
    ex = _src("EX", "客户B回款率40%。")
    ex.relevance_override = "exclude"
    d.add_source(ex)
    d.add_source(_src("COLD", "今天天气晴朗适合晾晒。"))
    d.add_source(_src("WEAK", "回款。"))
    d.add_source(_src("HOT", "客户B的回款率是四成。"))

    expected = (
        "人工排除 1 份；议题零重合且无共同数字/专名 1 份；"
        "低相关档 2 份（进候选但标降权）"
    )
    agg = relevance_aggregate(d)
    assert agg["n_human_exclude"] == 1
    assert agg["n_zero_overlap_no_match"] == 1
    assert agg["n_low"] == 2
    assert agg["line"] == expected
    for banned in ("漏检率", "召回率", "覆盖率"):
        assert banned not in agg["line"]

    old = "        if r[\"level\"] == \"low\":\n"
    new = (
        "        if r[\"level\"] == \"low\" or r[\"level\"] == \"high\":"
        "  # R-C70-1 K11\n"
    )
    poisoned = _load_mutated_copy("app/core/relevance.py", old, new, tmp_path)
    broken = poisoned.relevance_aggregate(d)
    assert broken["n_low"] != 2
    assert broken["line"] != expected
    # 真树未动
    assert relevance_aggregate(d)["line"] == expected
