"""C-135 守护格：环2 扩写披露进 accounting（``kg_test_tree.expand``）。

C-134 环2 缺口：扩写（``keyword_expand_query``＋规则改写）在 ``fuse_r19``
经典臂内部无条件在跑，但 accounting 零披露键。本单补一组只记计数、
不记词原文的披露键（enabled／terms_n／paraphrase_n），钉四件事
（全部零 LLM、零网络、手造夹具；嵌入打桩成常量向量）：
  a. 无 env 默认跑选料块 → accounting['kg_test_tree']['expand'] 三键
     在场、键集精确相等（少一键＝红）、enabled is True；
  b. 计数与独立复算一致：terms_n＝对同一 sub.rows 重跑
     ``keyword_expand_query`` 的词数；paraphrase_n＝
     ``rule_paraphrase_questions(question, n=1)`` 的条数（与生产
     fuse_r19 既有键 n_classic_paraphrase 同式）；
  c. 行为刀：打桩改扩写返回值 → terms_n 跟着变（披露跟踪机制输出，
     不是写死的常量）；
  d. 无泄漏：surface／hints 零 expand 键、expand dict 键集 ⊆ 三键、
     整 accounting 过禁键审计（扩写词原文不许进窄面／pack）。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType

Q = "某市通报与网络说法对事故原因描述不一致，官方结论是什么？"


def _dossier() -> Dossier:
    d = Dossier(question=Q)
    d.title = "测试夹具案（无案名标记）"  # → resolve_case_slug 回落 "case"
    for di in ("doc_001", "doc_002", "doc_003"):
        src = Source.create(f"信源{di}", SourceType.REPORT, id=di)
        src.url = f"https://example.test/{di}"
        for p in range(1, 11):
            text = (
                f"{di}第{p}段：事故发生于2026年3月{p}日，涉事金额{p}0万元，"
                f"通报口径与现场记录{'一致' if p % 2 else '存在差异'}，"
                f"处置进展持续更新，相关责任认定仍在进行中。"
            )
            src.segments.append(Segment(
                id=f"{di}#p{p}", source_id=di, text=text,
                locator=f"{di}#p{p}"))
        d.add_source(src)
    return d


def _fake_embeddings(monkeypatch) -> None:
    from app.kg_lab.index_build import KgIndex

    def _ensure(self, *, force: bool = False, refresh_ids=None):
        self.embeddings = {
            str(r["para_id"]): [0.1, 0.2, 0.3] for r in self.rows
        }
        return {"stubbed": True}

    monkeypatch.setattr(KgIndex, "ensure_embeddings", _ensure)


def _run_selection_block(dossier: Dossier, settings: Settings) -> dict:
    """逐行镜像 pipeline 选料块（C-132 后形状），零 LLM。"""
    kw: dict = {}
    if bool(getattr(settings, "kg_submit_surface", True)):
        if bool(getattr(settings, "test_tree_line", True)):
            from app.core.kg_submit_surface import (
                apply_kg_submit_surface, assert_clean_pack_kwargs,
                pack_kwargs_for_kg,
            )
            from app.core.kg_test_tree_line import ensure_test_tree_submit
            ensure_test_tree_submit(dossier)
            apply_kg_submit_surface(dossier, enabled=True)
            kw = pack_kwargs_for_kg(dossier)
            assert_clean_pack_kwargs(kw)
        else:
            acc = getattr(dossier, "accounting", None)
            if acc is None:
                dossier.accounting = {}
                acc = dossier.accounting
            acc["kg_submit_skipped"] = {
                "reason": "test_tree_line_off",
                "note": "C-132 主线＝测试树；旧密度桥主路径已删，"
                        "显式关＝跳过交卷面（回退无 KG 面装箱）",
            }
    return kw


def _expand_acc(dossier: Dossier) -> dict:
    return ((dossier.accounting or {}).get("kg_test_tree") or {}).get(
        "expand") or {}


# ------------------------------------------- a. 三键在场（缺＝红）

def test_a_expand_keys_present_no_env(monkeypatch):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    _fake_embeddings(monkeypatch)
    d = _dossier()
    _run_selection_block(d, Settings())
    exp = _expand_acc(d)
    assert sorted(exp.keys()) == ["enabled", "paraphrase_n", "terms_n"], exp
    assert exp["enabled"] is True
    assert isinstance(exp["terms_n"], int) and exp["terms_n"] >= 0
    assert isinstance(exp["paraphrase_n"], int) and exp["paraphrase_n"] >= 0
    # 记进白名单键 kg_test_tree 内层＝过 kept 透传（整键已登记，零 pipeline 改动）
    assert "kg_test_tree" in d.accounting


# ------------------------------------------- b. 计数与独立复算一致

def test_b_counts_match_independent(monkeypatch):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    _fake_embeddings(monkeypatch)
    from app.kg_lab.index_build import build_corpus_rows, keyword_expand_query
    from app.kg_lab.query_expand import rule_paraphrase_questions
    from app.kg_lab.slices import pack_selected_for_question

    d = _dossier()
    _run_selection_block(d, Settings())
    exp = _expand_acc(d)
    slug = d.accounting["kg_test_tree"]["case_slug"]
    seg_ids = {
        str(seg.id) for src in d.sources for seg in src.segments
    }
    rows = build_corpus_rows(d, case_slug=slug, para_ids=seg_ids)
    universe = set(pack_selected_for_question(d, d.question) or [])
    sub_rows = [r for r in rows if r["para_id"] in universe]
    q_exp = keyword_expand_query(d.question, sub_rows)
    assert exp["terms_n"] == len(str(q_exp).split()), (exp, q_exp)
    assert exp["paraphrase_n"] == len(
        rule_paraphrase_questions(d.question, n=1)), exp


# ------------------------------------------- c. 行为刀（披露跟踪机制输出）

def test_c_terms_n_tracks_expand_output(monkeypatch):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    _fake_embeddings(monkeypatch)
    import app.kg_lab.index_build as ib

    d = _dossier()
    monkeypatch.setattr(
        ib, "keyword_expand_query",
        lambda *a, **k: "甲 乙 丙 丁", raising=True)
    _run_selection_block(d, Settings())
    assert _expand_acc(d)["terms_n"] == 4

    d2 = _dossier()
    monkeypatch.setattr(
        ib, "keyword_expand_query", lambda *a, **k: "", raising=True)
    _run_selection_block(d2, Settings())
    assert _expand_acc(d2)["terms_n"] == 0
    assert _expand_acc(d2)["enabled"] is True  # 键仍在场（缺键＝红）


# ------------------------------------------- d. 无泄漏（原文不进窄面／pack）

def test_d_no_expand_in_narrow_faces(monkeypatch):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    _fake_embeddings(monkeypatch)
    from app.kg_lab.layer_boundary import audit_forbidden_keys

    d = _dossier()
    kw = _run_selection_block(d, Settings())
    acc = d.accounting
    exp = _expand_acc(d)
    assert set(exp.keys()) <= {"enabled", "terms_n", "paraphrase_n"}
    # 窄面两处零 expand 键
    assert "expand" not in (acc.get("kg_submit") or {})
    assert "expand" not in (acc.get("kg_pack_hints") or {})
    assert all("expand" not in str(k) for k in (kw or {}).keys())
    # 整 accounting 过禁键审计
    assert audit_forbidden_keys(acc) == []
