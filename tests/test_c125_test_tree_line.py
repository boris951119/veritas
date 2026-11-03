"""C-125 守护格：测试树整线（总旗 ``VERITAS_TEST_TREE_LINE``，默认关）。

钉七件事（全部零 LLM、零网络、手造夹具；嵌入一律打桩成常量向量）：
  a. 三处读点出厂默认开（C-132 翻转：dataclass／from_env／from_json）
     ＋ enabled 三态；
  b. 开旗整链可跑：surface 窄面契约齐全、hints 四键、k∈[3,7]、
     box⊆universe、focus⊆box、层闸零泄漏（禁键审计）；
  c. 确定性：同夹具两次 build 的 surface JSON 逐位相同；
  d. 嵌入降级：ensure_embeddings 炸 → fallback_lexical 披露、仍出 surface；
  e. 零金标：生产链返回面无 gold／l2 字段（金标只准活在量尺侧）；
  f. ensure_test_tree_submit 写账：kg_submit／kg_density(line=test_tree)／
     kg_test_tree 三键在账、账面过禁键审计、pipeline 白名单登记；
  g. 层边界：一筛系数文件存在且只被本模块读（r9_coeff.json 在仓）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.kg_test_tree_line import (
    build_test_tree_surface,
    ensure_test_tree_submit,
    test_tree_coeff as _tree_coeff,
    test_tree_line_enabled as _line_enabled,
)

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
    """嵌入打桩：常量三维向量（链路跑通但不依赖 ollama）。"""
    from app.kg_lab.index_build import KgIndex

    def _ensure(self, *, force: bool = False, refresh_ids=None):
        self.embeddings = {
            str(r["para_id"]): [0.1, 0.2, 0.3] for r in self.rows
        }
        return {"stubbed": True}

    monkeypatch.setattr(KgIndex, "ensure_embeddings", _ensure)


def _on(monkeypatch) -> None:
    monkeypatch.setenv("VERITAS_TEST_TREE_LINE", "1")


# ------------------------------------------------- a. 默认开（C-132 翻转）

def test_a_factory_default_on_three_sites(monkeypatch):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    assert Settings().test_tree_line is True  # C-132 dataclass 出厂开
    assert Settings.from_env().test_tree_line is True  # env 未设＝开
    monkeypatch.setenv("VERITAS_TEST_TREE_LINE", "0")
    assert Settings.from_env().test_tree_line is False
    monkeypatch.setenv("VERITAS_TEST_TREE_LINE", "false")
    assert Settings.from_env().test_tree_line is False
    monkeypatch.setenv("VERITAS_TEST_TREE_LINE", "1")
    assert Settings.from_env().test_tree_line is True
    monkeypatch.setenv("VERITAS_TEST_TREE_LINE", "true")
    assert Settings.from_env().test_tree_line is True


def test_a2_json_site(tmp_path):
    def _cfg(val) -> Settings:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"test_tree_line": val}), encoding="utf-8")
        return Settings.from_json(path=p)

    assert _cfg(True).test_tree_line is True
    assert _cfg(False).test_tree_line is False
    assert _cfg("1").test_tree_line is True
    assert _cfg("0").test_tree_line is False
    p2 = tmp_path / "no_key.json"
    p2.write_text("{}", encoding="utf-8")
    assert Settings.from_json(path=p2).test_tree_line is True  # 缺键＝C-132 出厂开


def test_a3_enabled_tri_state(monkeypatch):
    monkeypatch.delenv("VERITAS_TEST_TREE_LINE", raising=False)
    assert _line_enabled() is True  # C-132：无 env＝开
    assert _line_enabled(Settings()) is True
    s = Settings()
    s.test_tree_line = False
    assert _line_enabled(s) is False
    monkeypatch.setenv("VERITAS_TEST_TREE_LINE", "0")
    assert _line_enabled() is False


# ---------------------------------------------------------------- b. 整链形状

def _surface(monkeypatch) -> dict:
    _on(monkeypatch)
    _fake_embeddings(monkeypatch)
    return build_test_tree_surface(_dossier(), case_slug="fixture")


def test_b_full_chain_contract(monkeypatch):
    out = _surface(monkeypatch)
    surface = out["surface"]
    assert surface["layer"] == "submit"
    for key in ("schema_version", "rank_order", "k", "conflict_pairs",
                "tree17", "density_public", "route"):
        assert key in surface
    hints = out["hints"]
    assert set(hints) == {"priority_segment_ids", "focus_segment_ids",
                          "max_segments", "conflict_pairs"}
    assert 3 <= out["k"] <= 7
    assert hints["max_segments"] == out["k"]
    assert set(out["box"]) <= {  # box⊆universe（夹具全集＝30 段）
        f"doc_00{di}#p{p}" for di in (1, 2, 3) for p in range(1, 11)}
    assert set(out["close_read"]) <= set(out["box"])  # focus⊆box
    assert hints["focus_segment_ids"] == out["close_read"]
    assert surface["k"] == out["k"]


def test_b2_layer_gates_zero_leak(monkeypatch):
    from app.kg_lab.layer_boundary import (
        assert_submit_no_coeff, audit_forbidden_keys,
    )

    out = _surface(monkeypatch)
    assert audit_forbidden_keys(out["surface"]) == []
    assert audit_forbidden_keys(out["hints"]) == []
    assert_submit_no_coeff(out["surface"])  # 顶键＝窄面允许集
    assert "coeff" not in json.dumps(out["hints"])
    assert "weights" not in json.dumps(out["hints"])


# ---------------------------------------------------------------- c. 确定性

def test_c_deterministic_surface(monkeypatch):
    a = _surface(monkeypatch)
    b = build_test_tree_surface(_dossier(), case_slug="fixture")
    ka = json.dumps({k: v for k, v in a["surface"].items()},
                    ensure_ascii=False, sort_keys=True)
    kb = json.dumps({k: v for k, v in b["surface"].items()},
                    ensure_ascii=False, sort_keys=True)
    assert ka == kb  # 同夹具两次＝逐位同（嵌入打桩后链路确定性）


# ---------------------------------------------------------------- d. 嵌入降级

def test_d_embed_fallback_disclosed(monkeypatch):
    _on(monkeypatch)
    from app.kg_lab.index_build import KgIndex

    def _boom(self, *, force: bool = False, refresh_ids=None):
        raise RuntimeError("Ollama 不可达（测试桩）")

    monkeypatch.setattr(KgIndex, "ensure_embeddings", _boom)
    out = build_test_tree_surface(_dossier(), case_slug="fixture")
    assert out["embed"]["status"] == "fallback_lexical"
    assert out["embed"]["error_type"] == "RuntimeError"
    assert out["surface"]["k"] >= 1  # 词面链仍出盒
    assert out["box"]


# ---------------------------------------------------------------- e. 零金标

def test_e_no_gold_on_production_face(monkeypatch):
    out = _surface(monkeypatch)
    blob = json.dumps(out, ensure_ascii=False, sort_keys=True)
    assert "l2" not in blob and "gold" not in blob.lower()
    src = (Path(__file__).resolve().parents[1] / "app" / "core"
           / "kg_test_tree_line.py").read_text(encoding="utf-8")
    # 两个 gold 消费点的调用位都显式传 None（authority_rerank／tree17）
    calls = re.findall(r"gold_ids=(\w+)", src)
    assert calls.count("None") == len(calls) and calls  # 生产链零金标


# ---------------------------------------------------------------- f. 写账

def test_f_ensure_writes_accounting(monkeypatch):
    _on(monkeypatch)
    _fake_embeddings(monkeypatch)
    d = _dossier()
    out = ensure_test_tree_submit(d)
    assert out is not None
    acc = d.accounting
    assert isinstance(acc["kg_submit"], dict)
    assert acc["kg_submit"]["layer"] == "submit"
    assert acc["kg_density"]["line"] == "test_tree"
    assert acc["kg_test_tree"]["line"] == "test_tree_full"
    from app.kg_lab.layer_boundary import audit_forbidden_keys

    assert audit_forbidden_keys(acc["kg_test_tree"]) == []
    # 二次调用＝不覆盖（沿旧桥语义；桥本体已删＝C-133）
    acc["kg_submit"]["k"] = 999
    assert ensure_test_tree_submit(d) is None
    assert acc["kg_submit"]["k"] == 999
    # pipeline kept 白名单登记（内容断言）
    pl = (Path(__file__).resolve().parents[1] / "app" / "pipeline.py"
          ).read_text(encoding="utf-8")
    assert '"kg_test_tree"' in pl


# ---------------------------------------------------------------- g. 系数文件

def test_g_coeff_file_internal_only():
    coeff, names = _tree_coeff()
    assert coeff and len(names) >= 30  # R9+portable 全名集
    assert all(isinstance(v, float) for v in coeff.values())
    p = (Path(__file__).resolve().parents[1] / "app" / "kg_lab"
         / "r9_coeff.json").is_file()
    assert p  # 系数随仓数据文件（只进一筛打分）
    # 系数键集合与窄面禁键无关（不在 FORBIDDEN_PACK_KEYS 语境出现）
    from app.kg_lab.layer_boundary import FORBIDDEN_PACK_KEYS

    assert not (set(names) & FORBIDDEN_PACK_KEYS)
