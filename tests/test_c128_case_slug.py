"""C-128 守护格：case_slug 实名接线（零 LLM、零网络、手造夹具）。

钉四件事：
  a. ``resolve_case_slug``：六案标记→slug 与建库脚本／探针同表；
     未命中回落 ``"case"``；
  b. 暖臂实名：title 含标记 → ``ensure_test_tree_submit`` 用实名
     （tmp vault 暖臂证 ``summary_missing=False``）＋ ``case_slug``／
     ``case_slug_fallback`` 披露在账、过禁键审计；
  c. 无标记／显式覆盖：无标记仍 ``"case"``（披露可读）；显式
     ``case_slug=`` 覆盖 title；
  d. 出厂默认关未动；pipeline 开旗调用零实参即可拿实名（经解析）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.kg_test_tree_line import (
    CASE_MARK_PAIRS,
    build_test_tree_surface,
    ensure_test_tree_submit,
    resolve_case_slug,
)

Q = "某市通报与网络说法对事故原因描述不一致，官方结论是什么？"


def _dossier(title: str = "") -> Dossier:
    d = Dossier(question=Q, title=title)
    for di, doc in enumerate(("doc_001", "doc_002", "doc_003"), 1):
        src = Source.create(f"信源{di}", SourceType.REPORT, id=doc)
        src.url = f"https://example.test/{doc}"
        for p in range(1, 11):
            src.segments.append(Segment(
                id=f"{doc}#p{p}", source_id=doc,
                text=(f"{doc}第{p}段：事故发生于2026年3月{p}日，"
                      f"涉事金额{p}0万元，处置进展持续更新。"),
                locator=f"{doc}#p{p}"))
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


def _on(monkeypatch) -> None:
    monkeypatch.setenv("VERITAS_TEST_TREE_LINE", "1")


# ------------------------------------------------------- a. 解析表

def test_a_resolve_marks_same_table():
    assert len(CASE_MARK_PAIRS) == 6
    table = dict(CASE_MARK_PAIRS)
    assert table == {
        "刘翔": "liuxiang", "王虹": "wanghong", "中美AI": "us_cn_ai",
        "印度航空": "ai171", "柬泰": "kh_th", "吉隆": "jilong",
    }
    for mark, slug in CASE_MARK_PAIRS:
        assert resolve_case_slug(_dossier(f"卷宗：{mark}事件")) == slug
    assert resolve_case_slug(_dossier("没有标记的卷名")) == "case"
    assert resolve_case_slug(_dossier("")) == "case"


# ------------------------------------------------------- b. 暖臂实名

def _write_warm_vault(tmp_path, slug: str = "liuxiang") -> None:
    from app.kg_lab.summarize import summary_path

    vault = tmp_path / "summaries"
    for di in (1, 2, 3):
        doc = f"doc_00{di}"
        for p in range(1, 11):
            path = summary_path(slug, doc, f"{doc}#p{p}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "ok": True, "summary_text": f"{doc} 第{p}段要点",
                "facts": [], "entities": [], "keywords": [],
            }, ensure_ascii=False), encoding="utf-8")


def test_b_warm_arm_uses_real_slug(monkeypatch, tmp_path):
    from app.kg_lab.layer_boundary import audit_forbidden_keys
    from app.kg_lab.summarize import SUMMARIES_DIR

    _on(monkeypatch)
    _fake_embeddings(monkeypatch)
    monkeypatch.setattr(
        "app.kg_lab.summarize.SUMMARIES_DIR", tmp_path / "summaries")
    _write_warm_vault(tmp_path)
    d = _dossier("刘翔编制“二选一”事件")
    ensure_test_tree_submit(d, force=True)
    kt = d.accounting["kg_test_tree"]
    assert kt["case_slug"] == "liuxiang"          # 实名在账
    assert kt["case_slug_fallback"] is False
    assert kt["cache"]["vault_dir_present"] is True
    assert kt["cache"]["summary_missing"] is False  # 暖臂不再误报缺席
    assert kt["cache"]["n_with_summary"] == kt["cache"]["n_rows"] == 30
    assert kt["cache"]["affected"] == []
    assert audit_forbidden_keys(kt) == []


# ------------------------------------------------- c. 回落与显式覆盖

def test_c_fallback_disclosed(monkeypatch, tmp_path):
    _on(monkeypatch)
    _fake_embeddings(monkeypatch)
    monkeypatch.setattr(
        "app.kg_lab.summarize.SUMMARIES_DIR", tmp_path / "nope")
    d = _dossier("没有标记的卷名")
    ensure_test_tree_submit(d, force=True)
    kt = d.accounting["kg_test_tree"]
    assert kt["case_slug"] == "case"
    assert kt["case_slug_fallback"] is True       # 回落可读
    assert kt["cache"]["summary_missing"] is True


def test_c2_explicit_kw_overrides_title(monkeypatch, tmp_path):
    _on(monkeypatch)
    _fake_embeddings(monkeypatch)
    monkeypatch.setattr(
        "app.kg_lab.summarize.SUMMARIES_DIR", tmp_path / "summaries")
    _write_warm_vault(tmp_path, slug="fixture")
    d = _dossier("刘翔编制“二选一”事件")  # title 有标记
    out = build_test_tree_surface(d, case_slug="fixture")  # 显式覆盖
    assert out["case_slug"] == "fixture"
    assert out["cache"]["summary_missing"] is False


# ------------------------------------------------------- d. 同表＋默认关

def test_d_builder_and_probe_share_table():
    root = Path(__file__).resolve().parents[1]
    batch = (root / "scripts" / "kg_lab" / "batch_summarize_case.py"
             ).read_text(encoding="utf-8")
    assert "CASE_MARK_PAIRS" in batch  # 建库脚本同源（禁第三套表）
    spec = importlib.util.spec_from_file_location(
        "batch_summarize_case", root / "scripts" / "kg_lab"
        / "batch_summarize_case.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._slug("刘翔编制“二选一”事件") == "liuxiang"
    assert mod._slug("没有标记") == "case"
    probe = (root / "scripts" / "probe_c125_six_case_gate.py"
             ).read_text(encoding="utf-8")
    assert "CASE_MARK_PAIRS" in probe  # 探针同源


def test_d2_pipeline_call_site_needs_no_slug_arg():
    root = Path(__file__).resolve().parents[1]
    pl = (root / "app" / "pipeline.py").read_text(encoding="utf-8")
    assert "ensure_test_tree_submit(dossier)" in pl  # 零实参即经解析拿实名


def test_d3_factory_default_off_untouched(monkeypatch):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    assert Settings().test_tree_line is False
    assert Settings.from_env().test_tree_line is False
