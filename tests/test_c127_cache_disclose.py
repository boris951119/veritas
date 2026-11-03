"""C-127 守护格：缓存缺席披露＋摘要建库端口（零 LLM、零网络、手造夹具）。

钉五件事：
  a. 冷臂披露：摘要／vault 缺席时 ``kg_test_tree.cache`` 键在账且为真
     （summary_missing／vault_dir_present=False／affected 含 summary+vault／
     degraded_continue=True）；账面过禁键审计；
  b. 暖臂不误报：全段有 ok 摘要 → summary_missing=False、affected=[]、
     degraded_continue=False；
  c. 热路径零自动建库：``summarize_paras`` 被打成炸雷后整链照常跑
     （开旗路径不调建库）；``batch_summarize_case`` 不被生产面 import；
  d. 出厂默认关未动（dataclass／from_env）；
  e. 建库脚本在场且 ``--dry-run`` 可空跑（samples 缺失则 skip）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.kg_test_tree_line import build_test_tree_surface

Q = "某市通报与网络说法对事故原因描述不一致，官方结论是什么？"


def _dossier() -> Dossier:
    d = Dossier(question=Q)
    for di, doc in enumerate(("doc_001", "doc_002", "doc_003"), 1):
        src = Source.create(f"信源{di}", SourceType.REPORT, id=doc)
        src.url = f"https://example.test/{doc}"
        for p in range(1, 11):
            text = (
                f"{doc}第{p}段：事故发生于2026年3月{p}日，涉事金额{p}0万元，"
                f"通报口径与现场记录{'一致' if p % 2 else '存在差异'}，"
                f"处置进展持续更新，相关责任认定仍在进行中。"
            )
            src.segments.append(Segment(
                id=f"{doc}#p{p}", source_id=doc, text=text,
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


def _surface(monkeypatch) -> dict:
    _on(monkeypatch)
    _fake_embeddings(monkeypatch)
    return build_test_tree_surface(_dossier(), case_slug="fixture")


# ------------------------------------------------------- a. 冷臂披露

def test_a_cold_arm_discloses(monkeypatch, tmp_path):
    from app.kg_lab.layer_boundary import audit_forbidden_keys
    from app.core.kg_test_tree_line import ensure_test_tree_submit

    _on(monkeypatch)
    _fake_embeddings(monkeypatch)
    # vault 指到不存在的目录＝C-127 冷场景（摘要缓存缺席）
    monkeypatch.setattr(
        "app.kg_lab.summarize.SUMMARIES_DIR", tmp_path / "nope")
    d = _dossier()
    out = build_test_tree_surface(d, case_slug="fixture")
    cache = out["cache"]
    assert cache["summary_missing"] is True
    assert cache["vault_dir_present"] is False
    assert cache["n_rows"] == 30 and cache["n_with_summary"] == 0
    assert "summary" in cache["affected"] and "vault" in cache["affected"]
    assert "embed" not in cache["affected"]  # 嵌入打桩＝ok，不掺入
    assert cache["degraded_continue"] is True
    assert out["box"]  # 缺席只降读数质量，线继续跑
    # 账面同披露且过禁键审计（嵌在既有 kg_test_tree 键内，无新顶层键）
    d2 = _dossier()
    ensure_test_tree_submit(d2)
    kt = d2.accounting["kg_test_tree"]
    assert kt["cache"]["summary_missing"] is True
    assert audit_forbidden_keys(kt) == []


# ------------------------------------------------------- b. 暖臂不误报

def test_b_warm_arm_no_false_positive(monkeypatch, tmp_path):
    from app.kg_lab.summarize import SUMMARIES_DIR, summary_path

    _on(monkeypatch)
    _fake_embeddings(monkeypatch)
    vault = tmp_path / "summaries"
    monkeypatch.setattr(
        "app.kg_lab.summarize.SUMMARIES_DIR", vault)  # 先钉再写
    (vault / "fixture").mkdir(parents=True)
    for di in (1, 2, 3):
        doc = f"doc_00{di}"
        for p in range(1, 11):
            path = summary_path("fixture", doc, f"{doc}#p{p}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "ok": True, "summary_text": f"{doc} 第{p}段要点",
                "facts": [], "entities": [], "keywords": [],
            }, ensure_ascii=False), encoding="utf-8")
    out = build_test_tree_surface(_dossier(), case_slug="fixture")
    cache = out["cache"]
    assert cache["summary_missing"] is False
    assert cache["vault_dir_present"] is True
    assert cache["n_with_summary"] == cache["n_rows"] == 30
    assert cache["affected"] == []
    assert cache["degraded_continue"] is False


# ------------------------------------------------- c. 热路径零自动建库

def test_c_hot_path_never_builds_summaries(monkeypatch):
    import app.kg_lab.summarize as summarize_mod

    _on(monkeypatch)
    _fake_embeddings(monkeypatch)

    def _boom(*a, **k):  # 热路径一旦调建库立刻炸
        raise AssertionError("hot path must not call summarize_paras")

    monkeypatch.setattr(summarize_mod, "summarize_paras", _boom)
    out = build_test_tree_surface(_dossier(), case_slug="fixture")
    assert out["box"] and out["k"] >= 1  # 建库零调用、整链照常出盒
    # 生产面不 import 建库脚本
    root = Path(__file__).resolve().parents[1]
    for prod in ("app/pipeline.py", "app/core/kg_test_tree_line.py"):
        assert "batch_summarize_case" not in (root / prod).read_text(
            encoding="utf-8")


# ------------------------------------- d. 出厂默认开（C-132 翻转）

def test_d_factory_default_on_c132(monkeypatch):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    assert Settings().test_tree_line is True
    assert Settings.from_env().test_tree_line is True


# ------------------------------------------------- e. 建库脚本空跑

def _samples_root() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    for cand in (root / "data" / "trs-samples",
                 Path("/Users/liuboyu/Desktop/veritas-testcases"
                      "/样例集-拓尔思-20261012")):
        if cand.is_dir() and any(
            p.is_dir() and "刘翔" in p.name
            and (p / "raw_documents.json").is_file()
            for p in cand.iterdir()
        ):
            return cand
    return None


def test_e_builder_dry_run_zero_llm():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "kg_lab" / "batch_summarize_case.py"
    assert script.is_file()  # 建库脚本已端口入库
    samples = _samples_root()
    if samples is None:
        pytest.skip("trs-samples 不在本机（六案样本目录缺失）")
    r = subprocess.run(
        [sys.executable, str(script), "--dry-run",
         "--case-filter", "刘翔", "--samples", str(samples)],
        capture_output=True, text=True, timeout=180,
        env={**os.environ, "VERITAS_TEST_TREE_LINE": "0"},
    )
    assert r.returncode == 0, r.stderr[-400:]
    assert "DRY_RUN" in r.stdout and "pending=" in r.stdout
    assert "universe=" in r.stdout  # 并集规模可读（零 LLM）
