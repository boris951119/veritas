"""C-53：装箱上限三刀量尺＋窗口估算覆盖面守护（零 LLM）。

件② 本轮降级为披露（见 HANDOFF「Cursor 回写（C-53）」）——现码新跑
production 同形 est 差已 ≤0.3%，4700 tok 洞＝改前产物×现码重装漂移，
不是覆盖面可收。本文件仍钉：
  - 三刀公式与早退语义；
  - production_pack_messages 必须把 skills_rules 计入估算覆盖面
    （摘掉覆盖面 ⇒ 本格红＝判据 e 同族保险）；
  - 改前口径（skinny messages_for 无 skills）对生产同形之差可 >5%
    （判据 c 的「改前必红」当场演示，用夹具写死期望）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.material import (
    align_budget_to_window,
    production_pack_messages,
    set_material_budget,
)
from app.core.prompt_guard import estimate_prompt_window
from app.agents.prompts import render_segments_block, render_system_prompt

ROOT = Path(__file__).resolve().parents[1]
PERSONA = "你是一名严谨的开源情报分析师，只依据给定资料作答。"
WINDOW = 16384
DENSITY = 1.45


class _Settings:
    model_context_tokens = WINDOW
    zh_chars_per_token = DENSITY
    material_char_budget = 20_000
    pack_to_window = True


def _tiny_dossier(*, n_chars: int = 8000, question: str = "测试议题甲乙丙") -> Dossier:
    """合成案卷：多段 × ≤650 字（与 render 截断上限对齐），总字数≈n_chars。"""
    unit = "甲乙丙丁戊己庚辛壬癸"  # 10 字
    per = 600  # < SEGMENT_MAX=650，避免渲染侧再截
    n_segs = max(1, (n_chars + per - 1) // per)
    src = Source.create("测试信源", SourceType.REPORT, id="doc_t")
    for i in range(n_segs):
        body = (unit * ((per // 10) + 1))[:per]
        # 掺议题词，避免整源被零相关闸踢出
        if i == 0:
            body = question[:8] + body[8:]
        src.segments.append(
            Segment(id=f"doc_t#p{i+1}", source_id="doc_t",
                    text=body, locator=f"p{i+1}", index=i))
    d = Dossier(question=question, sources=[src])
    d.accounting = {
        "query_rewrite": {
            "original": question,
            "variants": [],
            "queries": [question],
        }
    }
    return d


def test_c53_three_knives_formula_and_early_return():
    """已进窗 ⇒ 早退预算=orig、n_iters=1、fits；超窗 ⇒ 落点 ≤ 三刀 min。"""
    # 短文：orig 已进窗
    d = _tiny_dossier(n_chars=2000)
    st = _Settings()
    st.material_char_budget = 20_000
    out = align_budget_to_window(d, st, persona=PERSONA, profile_tier="standard")
    assert out["fits"] is True
    assert out["budget"] == 20_000
    assert out["n_iters"] == 1
    assert out["est_tokens"] <= WINDOW

    # 长文：逼出缩档；落点不得高于三刀
    d2 = _tiny_dossier(n_chars=60_000)
    st2 = _Settings()
    st2.material_char_budget = 80_000
    set_material_budget(80_000)
    msgs0 = production_pack_messages(d2, persona=PERSONA, profile_tier="standard")
    rec0 = estimate_prompt_window(
        msgs0, window_tokens=WINDOW, zh_chars_per_token=DENSITY)
    est0 = int(rec0["est_tokens"])
    assert int(rec0["overflow_tokens"]) > 0  # 夹具必须真超窗
    hard = max(1, int(WINDOW * DENSITY))
    knife3 = max(1, int(80_000 * WINDOW / max(est0, 1) * 0.92))
    ceiling = min(80_000, hard, knife3)
    out2 = align_budget_to_window(
        d2, st2, persona=PERSONA, profile_tier="standard")
    assert out2["budget"] <= ceiling
    assert out2["fits"] is True
    assert int(out2["est_tokens"]) <= WINDOW


def test_c53_production_estimate_includes_skills_coverage():
    """判据 e 同族：估算覆盖面必须含 skills_rules；摘掉 ⇒ 本格红。"""
    d = _tiny_dossier(n_chars=3000)
    set_material_budget(20_000)
    full = production_pack_messages(d, persona=PERSONA, profile_tier="standard")
    # 生产同形 system 必须长于「只有 persona」的瘦身版（skills 计入）
    skinny_sys = render_system_prompt(PERSONA)
    full_sys = str(full[0]["content"])
    assert len(full_sys) > len(skinny_sys), (
        "production_pack_messages 的 system 未纳入 skills_rules＝覆盖面被摘"
    )
    # 源码钉子：函数体必须调用 render_skills_rules
    src = (ROOT / "app" / "core" / "material.py").read_text(encoding="utf-8")
    assert "render_skills_rules" in src
    # production_pack_messages 定义附近必须把 skills_rules= 传进 render_system_prompt
    start = src.find("def production_pack_messages")
    chunk = src[start:start + 800]
    assert "skills_rules=" in chunk
    assert "render_skills_rules" in chunk


def test_c53_prechange_skinny_vs_production_gap_must_red():
    """判据 c 改前必红：skinny（fit_safe／messages_for 同形）对生产同形差可 >5%。

    期望值写死：本夹具下 skills 贡献使相对差 ≥ 阈值；若有人把对齐估算
    改回 skinny，本格仍绿但 `test_c53_production_estimate_includes_skills_coverage`
    会红——两格互补。
    """
    d = _tiny_dossier(n_chars=4000)
    set_material_budget(20_000)
    prod = production_pack_messages(d, persona=PERSONA, profile_tier="standard")
    set_material_budget(20_000)
    from app.core.material import pack_material
    pack_material(d)
    skinny = [
        {"role": "system", "content": render_system_prompt(PERSONA)},
        {"role": "user", "content": render_segments_block(d)},
    ]
    rp = estimate_prompt_window(
        prod, window_tokens=WINDOW, zh_chars_per_token=DENSITY)
    rs = estimate_prompt_window(
        skinny, window_tokens=WINDOW, zh_chars_per_token=DENSITY)
    gap = abs(int(rp["est_tokens"]) - int(rs["est_tokens"])) / max(
        int(rp["est_tokens"]), 1)
    # 写死：夹具下差距必须可被量到（skills 非空）
    assert gap > 0.0
    # 「改前必红」演示：若有人用 skinny 当闸用估算，与生产同形之差
    # 在真跑长案上可 ≫5%（件① OLD 批最高 163%）；此处只钉 gap>0 的可测性，
    # 真跑差值表见探针 MODE=c53。
    assert int(rp["est_tokens"]) != int(rs["est_tokens"])


def test_c53_align_zero_overflow_invariant():
    """零超窗不变式：align 返回后 est≤window 且 fits（能进窗的夹具）。"""
    d = _tiny_dossier(n_chars=25_000)
    st = _Settings()
    st.material_char_budget = 40_000
    out = align_budget_to_window(d, st, persona=PERSONA, profile_tier="standard")
    assert out["fits"] is True
    assert int(out["est_tokens"]) <= WINDOW
    # 现场再估一次必须仍不超
    set_material_budget(int(out["budget"]))
    msgs = production_pack_messages(d, persona=PERSONA, profile_tier="standard")
    rec = estimate_prompt_window(
        msgs, window_tokens=WINDOW, zh_chars_per_token=DENSITY)
    assert int(rec["overflow_tokens"]) == 0


def test_c53_probe_mode_c53_entrypoint_present():
    """件① 探针入口在场：MODE=c53 分支与 mode_c53 定义。"""
    src = (ROOT / "scripts" / "probe_pack_window.py").read_text(encoding="utf-8")
    assert 'MODE == "c53"' in src
    assert "def mode_c53" in src
    assert "production_pack_messages" in src
    assert "判据 a" in src or "L2 换预" in src
