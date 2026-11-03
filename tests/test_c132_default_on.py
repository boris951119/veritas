"""C-132 守护格：测试树主线出厂开＋旧密度桥主路径已删。

Boyu 2026-11-03 硬令：删旧路、测试树作唯一主线、总旗出厂默认开。钉五件事
（全部零 LLM、零网络、手造夹具；嵌入一律打桩成常量向量）：
  a. 无 env／config.json 缺键 → Settings.test_tree_line 三处读点全 True；
     显式 0/false/off/no → False（紧急停用开关保留）；
  b. 主路径不回密度桥：pipeline.py 源码不含 ``ensure_kg_submit_from_density``
     调用（静态），且把密度桥入口打成炸点后默认跑选料块不炸（动态）；
  c. 默认跑选料块：kg_submit_active／kg_submit（layer=submit）／kg_test_tree
     三键入账、case_slug 回落 "case" 有披露、禁键审计 0；
  d. 显式关＝跳过交卷面：无 kg_submit_active、accounting['kg_submit_skipped']
     披露在场、装箱零 KG kwargs、白名单登记（report 面可见）；
  e. 旁路刀仍出厂关：C-113/121/122/123/124 相关旗一个都没被本单顺手打开。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SRC = (ROOT / "app" / "pipeline.py").read_text(encoding="utf-8")

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


# ---------------------------------------------------------------- a. 默认开

def test_a_default_true_all_sites(monkeypatch, tmp_path):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    assert Settings().test_tree_line is True
    assert Settings.from_env().test_tree_line is True
    p = tmp_path / "no_key.json"
    p.write_text("{}", encoding="utf-8")
    assert Settings.from_json(path=p).test_tree_line is True


def test_a2_explicit_off_values(monkeypatch):
    for val in ("0", "false", "off", "no"):
        monkeypatch.setenv("VERITAS_TEST_TREE_LINE", val)
        assert Settings.from_env().test_tree_line is False, val


# ------------------------------------------------- b. 主路径不回密度桥

def test_b_no_density_bridge_on_main_path():
    assert "ensure_kg_submit_from_density" not in PIPELINE_SRC


def test_b2_dynamic_no_bridge_call(monkeypatch):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    _fake_embeddings(monkeypatch)
    import app.core.kg_density_bridge as bridge

    def _boom(*a, **k):  # 打成炸点：被调即红
        raise AssertionError("旧密度桥在主路径被调用（C-132 禁）")

    monkeypatch.setattr(bridge, "ensure_kg_submit_from_density", _boom)
    d = _dossier()
    kw = _run_selection_block(d, Settings())
    acc = d.accounting
    assert acc["kg_submit"]["layer"] == "submit"
    assert acc["kg_test_tree"]["case_slug"] == "case"
    assert acc["kg_test_tree"]["case_slug_fallback"] is True
    assert isinstance(kw, dict)


# ------------------------------------------------------------- c. 账面＋禁键

def test_c_accounting_and_no_leak(monkeypatch):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    _fake_embeddings(monkeypatch)
    from app.kg_lab.layer_boundary import audit_forbidden_keys

    d = _dossier()
    _run_selection_block(d, Settings())
    acc = d.accounting
    assert acc["kg_submit_active"] is True
    assert acc["kg_density"]["line"] == "test_tree"
    assert audit_forbidden_keys(acc) == []


# ------------------------------------------------- d. 显式关＝跳过＋披露

def test_d_explicit_off_skips_surface(monkeypatch):
    monkeypatch.setenv("VERITAS_TEST_TREE_LINE", "0")
    _fake_embeddings(monkeypatch)
    from app.kg_lab.layer_boundary import audit_forbidden_keys

    d = _dossier()
    kw = _run_selection_block(d, Settings.from_env())
    acc = d.accounting
    assert "kg_submit_active" not in acc
    assert acc["kg_submit_skipped"]["reason"] == "test_tree_line_off"
    assert kw == {}
    assert audit_forbidden_keys(acc) == []
    # 白名单登记＝report 面可见（C-123 教训：不登记＝下轮被整片剥掉）
    assert '"kg_submit_skipped"' in PIPELINE_SRC


def test_d2_off_env_via_settings_object(monkeypatch):
    monkeypatch.setenv("VERITAS_TEST_TREE_LINE", "0")
    s = Settings.from_env()
    assert s.test_tree_line is False
    _fake_embeddings(monkeypatch)
    d = _dossier()
    kw = _run_selection_block(d, s)
    assert "kg_submit_active" not in d.accounting
    assert kw == {}


# ------------------------------------------------------------- e. 旁路刀仍关

def test_e_side_knives_still_off_by_factory():
    s = Settings()
    assert getattr(s, "anchor_stable", None) is False
    assert getattr(s, "conflict_trace", None) is False
    assert getattr(s, "conf_calib", None) is False
    assert getattr(s, "tree15_depress", None) is False
    assert getattr(s, "claim_slots", None) is False
