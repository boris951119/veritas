"""C-54：装箱计费＝渲染后长度（SEGMENT_MAX 同形）；零超窗＋反向腿。

零 LLM。不许改 SEGMENT_MAX／窗口默认／0.92。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.material import (
    align_budget_to_window,
    pack_material,
    production_pack_messages,
    set_material_budget,
)
from app.core.prompt_guard import estimate_prompt_window
from app.ingest.segment import SEGMENT_MAX

ROOT = Path(__file__).resolve().parents[1]
PERSONA = "你是一名严谨的开源情报分析师，只依据给定资料作答。"
WINDOW = 16_384
DENSITY = 1.45


def _seg(sid: str, text: str, src_id: str = "S1") -> Segment:
    return Segment(id=sid, source_id=src_id, text=text, locator="段1", index=0)


def _dossier_long_plus_shorts() -> Dossier:
    """一长段（>SEGMENT_MAX）＋两短段；议题命中三词以便 BM25>0。"""
    long = "固态电池能量密度研究。" + ("长" * (SEGMENT_MAX + 200))
    short_a = "固态电池能量密度补充句甲。" + ("甲" * 40)
    short_b = "固态电池能量密度补充句乙。" + ("乙" * 40)
    src = Source.create("资料", SourceType.PAPER, id="S1")
    src.segments = [
        _seg("S1#long", long),
        _seg("S1#a", short_a),
        _seg("S1#b", short_b),
    ]
    return Dossier(question="固态电池能量密度如何？", sources=[src])


def test_a_billing_len_matches_render_cap():
    """生产字数核算＝min(len, SEGMENT_MAX)；源码钉死，不许只打印。"""
    src = (ROOT / "app" / "core" / "material.py").read_text(encoding="utf-8")
    assert "_billing_len" in src
    assert "SEGMENT_MAX" in src
    assert "min(len(text or \"\"), int(_SEGMENT_MAX))" in src
    # 行为：长段计费不超过 SEGMENT_MAX
    d = _dossier_long_plus_shorts()
    set_material_budget(80_000)
    pack = pack_material(d)
    assert "S1#long" in pack["selected"]
    # used_chars 按计费长度累加；长段只记 ≤SEGMENT_MAX
    long_raw = len(d.sources[0].segments[0].text)
    assert long_raw > SEGMENT_MAX
    # 全选时 used ≤ Σ min(len, MAX)
    cap_sum = sum(
        min(len(s.text), SEGMENT_MAX)
        for src in d.sources for s in src.segments
    )
    assert pack["used_chars"] <= cap_sum


def _pack_n_with_raw_billing(d: Dossier, budget: int) -> int:
    """本地 fork：计费改回 len(seg.text)（案卷文本不动）。"""
    import inspect
    import math
    import textwrap
    import app.core.material as mat
    from app.core.answer_slots import priority_segment_ids
    from app.core.bm25 import rank_segments
    from app.core.dup_check import duplicate_map
    from app.core.relevance import classify_sources

    src = textwrap.dedent(inspect.getsource(mat.pack_material))
    src = src.replace(
        "lengths[seg.id] = _billing_len(seg.text)",
        "lengths[seg.id] = len(seg.text)",
    )
    ns = {
        "Dossier": Dossier,
        "duplicate_map": duplicate_map,
        "classify_sources": classify_sources,
        "rank_segments": rank_segments,
        "priority_segment_ids": priority_segment_ids,
        "math": math,
        "pack_search_queries": mat.pack_search_queries,
        "_MATERIAL_BUDGET": budget,
        "_EXCLUDE_BUDGET_REASON": "预算截断",
        "_billing_len": lambda t: len(t or ""),
    }
    exec(compile(src, "<c54_raw_fork>", "exec"), ns)
    set_material_budget(budget)
    return int(ns["pack_material"](d, budget_chars=budget)["n_selected"])


def test_b_render_billing_packs_more_peers_than_raw():
    """同预算：渲染计费应比原始计费更能装进短同伴段。

    budget＝900：原始计费时长段(~850)入箱后几乎塞满；渲染计费时长段只记 650，
    还能再装两短段。
    """
    d = _dossier_long_plus_shorts()
    budget = SEGMENT_MAX + 250
    set_material_budget(budget)
    n_render = int(pack_material(d)["n_selected"])
    n_raw = _pack_n_with_raw_billing(d, budget)
    assert n_render > n_raw, (
        f"渲染计费应多装：render={n_render} raw={n_raw} budget={budget}"
    )


def test_d_zero_overflow_after_align():
    """判据 d：改后 align 仍 fits 且 overflow=0。"""
    d = _dossier_long_plus_shorts()
    st = Settings()
    st.model_context_tokens = WINDOW
    st.zh_chars_per_token = DENSITY
    st.material_char_budget = 40_000
    st.pack_to_window = True
    out = align_budget_to_window(
        d, st, persona=PERSONA, profile_tier="standard")
    assert out.get("fits") is True
    set_material_budget(int(out["budget"]))
    msgs = production_pack_messages(
        d, persona=PERSONA, profile_tier="standard")
    rec = estimate_prompt_window(
        msgs, window_tokens=WINDOW, zh_chars_per_token=DENSITY)
    assert int(rec.get("overflow_tokens") or 0) == 0


def test_d_reverse_raw_billing_must_red():
    """判据 d 反向腿：把计费改回原始字数 ⇒ 正向「多装」断言必红。

    自证形状＝生产若被改回 raw，则 n_prod == n_raw ⇒ 下面的 > 断言红。
    """
    d = _dossier_long_plus_shorts()
    budget = SEGMENT_MAX + 250
    set_material_budget(budget)
    n_prod = int(pack_material(d)["n_selected"])
    n_raw = _pack_n_with_raw_billing(d, budget)
    assert n_prod > n_raw, (
        f"生产须仍为渲染计费：prod={n_prod} raw={n_raw}"
    )


def test_seg_text_untouched_by_billing():
    """禁止项⑥：计费不改写 seg.text。"""
    d = _dossier_long_plus_shorts()
    before = d.sources[0].segments[0].text
    set_material_budget(5_000)
    pack_material(d)
    assert d.sources[0].segments[0].text == before
    assert len(before) > SEGMENT_MAX
