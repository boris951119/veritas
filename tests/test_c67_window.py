"""C-67 件②／R-C67-1：每模探窗＋编队取最小窗＋探不到分 A／B 两态。"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.panel import MAINSTREAM_PERSONA
from app.config import (
    MODEL_CTX_FALLBACK_DEFAULT,
    PROBE_ENDPOINT_UNPROBEABLE,
    PROBE_NO_NUM_CTX,
    Settings,
    choose_window_tokens,
    clear_model_ctx_probe_cache,
    lookup_declared_model_ctx,
    resolve_model_window,
    resolve_panel_min_window,
)
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.hashchain import HashChain
from app.core.material import align_budget_to_window
from app.pipeline import (
    RunDeps, RunSpec, pack_window_for_panel, render_report_md, run_case,
)

ROOT = Path(__file__).resolve().parents[1]

_MIN_JSON = """```json
{"conclusions": [
   {"statement": "测试结论",
   "evidence": [{"quote": "客户B回款率40%",
                 "segment_id": "SRC1#s1",
                 "relation": "correlation", "level": "A", "note": "测"}]}
]}
```"""


class _StubClient:
    def chat(self, model, messages, json_mode=False):
        return SimpleNamespace(content=_MIN_JSON)


def _many_sources(n: int = 40, seg_chars: int = 400) -> Dossier:
    d = Dossier(question="客户B的回款情况如何？")
    for i in range(n):
        src = Source.create(f"料{i}", SourceType.REPORT, id=f"SRC{i}")
        unit = f"编号{i}客户B回款率40%。材料填充。"
        text = (unit * ((seg_chars // len(unit)) + 2))[:seg_chars]
        src.segments.append(Segment(
            id=f"SRC{i}#s1", source_id=f"SRC{i}", text=text, index=0))
        d.add_source(src)
    return d


def _settings(**kw) -> Settings:
    s = Settings()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# 判据 c：固定比例机械腿
# ---------------------------------------------------------------------------
_RATIO_PAT = re.compile(
    r"(?:\*\s*0\.8\b|\*\s*0\.9\b|\b0\.8\s*\*|\b0\.9\s*\*)")


def test_c67_c_no_fixed_ratio_in_window_paths():
    """判据 c：config／material／探针不得出现窗×0.8／×0.9。"""
    paths = [
        ROOT / "app" / "config.py",
        ROOT / "app" / "core" / "material.py",
        ROOT / "scripts" / "probe_c67_window.py",
    ]
    offenders: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            # 注释／本测试说明里允许提及禁止项字面量
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith('"""') \
                    or stripped.startswith("'''"):
                continue
            if _RATIO_PAT.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{i}:{line.strip()}")
    assert not offenders, "固定比例腿红：" + "; ".join(offenders)


# ---------------------------------------------------------------------------
# 判据 d：反向腿＝换窗必须换 budget
# ---------------------------------------------------------------------------
def test_c67_d_smaller_window_strictly_smaller_budget():
    """同案卷同预算：窗 2048 vs 16384 ⇒ window_tokens 各相等且 budget 严格小于。"""
    d = _many_sources(50, seg_chars=500)
    s_small = _settings(
        material_char_budget=80_000, model_context_tokens=2048,
        zh_chars_per_token=1.45, pack_to_window=True)
    s_big = _settings(
        material_char_budget=80_000, model_context_tokens=16384,
        zh_chars_per_token=1.45, pack_to_window=True)
    # 直接传 window_tokens＝模拟「每模一值」已接进装箱
    pw_small = align_budget_to_window(
        d, s_small, persona=MAINSTREAM_PERSONA, profile_tier="standard",
        window_tokens=2048)
    pw_big = align_budget_to_window(
        d, s_big, persona=MAINSTREAM_PERSONA, profile_tier="standard",
        window_tokens=16384)
    assert pw_small["window_tokens"] == 2048, pw_small
    assert pw_big["window_tokens"] == 16384, pw_big
    assert pw_small["budget"] < pw_big["budget"], (
        f"2048 budget={pw_small['budget']} 应严格小于 "
        f"16384 budget={pw_big['budget']}")


# ---------------------------------------------------------------------------
# 判据 e：同码同案卷两次三项相同
# ---------------------------------------------------------------------------
def test_c67_e_deterministic_three_fields(monkeypatch):
    """同码同案卷跑两次：rule／window_tokens／target_tokens 逐项相同。"""
    clear_model_ctx_probe_cache()

    def _boom(_model, **_kw):
        raise RuntimeError("probe disabled for determinism")

    monkeypatch.setattr("app.config.probe_model_num_ctx", _boom)
    s = _settings(
        material_char_budget=80_000, model_context_tokens=16384,
        model_context_tokens_by_model={"openai/m": 8192},
        model_ctx_tokens_env_set=False,
        pack_to_window=True, zh_chars_per_token=1.45,
        models=["openai/m"])
    d = _many_sources(20, seg_chars=300)
    r1 = resolve_panel_min_window(s, ["openai/m"], probe_fn=_boom)
    pw1 = align_budget_to_window(
        d, s, persona=MAINSTREAM_PERSONA, profile_tier="standard",
        window_tokens=int(r1["window_tokens"]))
    r2 = resolve_panel_min_window(s, ["openai/m"], probe_fn=_boom)
    pw2 = align_budget_to_window(
        d, s, persona=MAINSTREAM_PERSONA, profile_tier="standard",
        window_tokens=int(r2["window_tokens"]))
    for k in ("rule", "window_tokens", "target_tokens"):
        # resolve 后 stamp rule；这里比 align 三项（声明源 ⇒ align_to_window）
        assert pw1[k] == pw2[k], (k, pw1[k], pw2[k])
    assert r1["window_tokens"] == r2["window_tokens"] == 8192


# ---------------------------------------------------------------------------
# R-C67-1 件①A：端点不可探 → 沿用全局假定值（不是实测）
# ---------------------------------------------------------------------------
def test_c67_r1_a_endpoint_unprobeable_uses_global():
    """态 A：probe=endpoint_unprobeable＋无声明 ⇒ window=16384／unchecked_global。"""
    clear_model_ctx_probe_cache()
    s = _settings(
        model_context_tokens=16384,
        model_context_tokens_by_model={},
        model_ctx_tokens_env_set=False,
        model_context_fallback_tokens=MODEL_CTX_FALLBACK_DEFAULT,
        models=["openai/qwen3.8-max"])
    rec = resolve_model_window(
        s, "openai/qwen3.8-max",
        probe_fn=lambda *_a, **_k: PROBE_ENDPOINT_UNPROBEABLE)
    assert rec["window_tokens"] == 16384, rec
    assert rec["source"] == "unchecked_global", rec
    assert "未检查" in rec["rule"], rec
    assert "端点不可探" in rec["detail"], rec
    assert "假定值" in rec["detail"], rec
    assert "不是实测" in rec["detail"], rec
    assert MODEL_CTX_FALLBACK_DEFAULT != 16384  # 防误写成 fallback


# ---------------------------------------------------------------------------
# R-C67-1 件①B：端点可探但无 num_ctx → 保守常量 4096
# ---------------------------------------------------------------------------
def test_c67_r1_b_no_num_ctx_uses_fallback_and_discloses():
    """态 B：probe=no_num_ctx＋无声明 ⇒ 4096、rule 含未检查、披露在场。"""
    clear_model_ctx_probe_cache()
    s = _settings(
        model_context_tokens=16384,
        model_context_tokens_by_model={},
        model_ctx_tokens_env_set=False,
        model_context_fallback_tokens=MODEL_CTX_FALLBACK_DEFAULT,
        pack_to_window=True, material_char_budget=80_000,
        zh_chars_per_token=1.45, models=["qwen3:14b"])
    rec = resolve_model_window(
        s, "qwen3:14b",
        probe_fn=lambda *_a, **_k: PROBE_NO_NUM_CTX)
    assert rec["window_tokens"] == MODEL_CTX_FALLBACK_DEFAULT, rec
    assert rec["window_tokens"] != 16384
    assert "未检查" in rec["rule"], rec
    assert rec["source"] == "fallback"
    assert "num_ctx" in rec["detail"]

    d = _many_sources(10, seg_chars=200)
    pw = align_budget_to_window(
        d, s, persona=MAINSTREAM_PERSONA, profile_tier="standard",
        window_tokens=int(rec["window_tokens"]))
    pw["rule"] = rec["rule"]
    pw["window_source"] = "fallback"
    pw["window_detail"] = rec["detail"]
    d.accounting["pack_window"] = dict(pw)
    md = render_report_md(d, HashChain(), [])
    assert "未检查" in md, md
    assert str(MODEL_CTX_FALLBACK_DEFAULT) in md


# ---------------------------------------------------------------------------
# R-C67-1 件① 改前行为等价腿：stock config → 16384（出现 4096＝红）
# ---------------------------------------------------------------------------
def test_c67_r1_stock_config_pack_window_stays_16384(monkeypatch):
    """仓库 config.json 原样（无每模表、无 env）⇒ 任选题 pack_window.window_tokens＝16384。"""
    monkeypatch.delenv("VERITAS_MODEL_CTX_TOKENS", raising=False)
    monkeypatch.delenv("VERITAS_MODEL_CTX_BY_MODEL", raising=False)
    monkeypatch.delenv("VERITAS_MODEL_CTX_FALLBACK", raising=False)
    clear_model_ctx_probe_cache()
    s = Settings.from_json(ROOT / "config.json")
    assert not s.model_context_tokens_by_model
    assert s.model_context_tokens == 16384
    # 云端名在本机 Ollama＝404／端点不可探；零模型用哨兵钉同态
    monkeypatch.setattr(
        "app.config.probe_model_num_ctx",
        lambda *_a, **_k: PROBE_ENDPOINT_UNPROBEABLE)
    rec = resolve_model_window(s, "openai/qwen3.8-max")
    assert rec["window_tokens"] == 16384, rec
    assert rec["source"] == "unchecked_global", rec
    d = _many_sources(15, seg_chars=300)
    pw = pack_window_for_panel(
        d, s,
        [SimpleNamespace(model="openai/qwen3.8-max")],
        persona=MAINSTREAM_PERSONA, profile_tier="standard")
    assert pw["window_tokens"] == 16384, pw
    assert pw["window_tokens"] != MODEL_CTX_FALLBACK_DEFAULT


# ---------------------------------------------------------------------------
# 真引用格（§5 第 26 条）
# ---------------------------------------------------------------------------
def test_c67_true_ref_imports_probe_pure_fn():
    """import scripts.probe_c67_window 并调用其纯函数 choose_window_tokens。"""
    import scripts.probe_c67_window as probe

    tokens, source = probe.choose_window_tokens(None, None, 4096)
    assert tokens == 4096 and source == "fallback"
    tokens2, source2 = probe.choose_window_tokens(16384, 2048, 4096)
    assert tokens2 == 16384 and source2 == "probed"
    tokens3, source3 = probe.choose_window_tokens(None, 8192, 4096)
    assert tokens3 == 8192 and source3 == "declared"
    # list_models_to_probe 也是纯清单（不发 HTTP）
    names = probe.list_models_to_probe(Settings(models=["openai/a", "openai/b"]))
    assert names == ["openai/a", "openai/b"]


def test_c67_choose_window_tokens_unit():
    """同仓内再钉一次顺序（与探针导出一致）。"""
    assert choose_window_tokens(100, 200, 4096) == (100, "probed")
    assert choose_window_tokens(None, 200, 4096) == (200, "declared")
    assert choose_window_tokens(None, None, 4096) == (4096, "fallback")


def test_c67_panel_min_takes_smaller():
    """编队两模声明 2048 与 16384 ⇒ 取最小 2048。"""
    clear_model_ctx_probe_cache()
    s = _settings(
        model_context_tokens=16384,
        model_context_tokens_by_model={
            "openai/small": 2048,
            "openai/big": 16384,
        },
        model_ctx_tokens_env_set=False,
        models=["openai/small", "openai/big"])
    rec = resolve_panel_min_window(
        s, ["openai/small", "openai/big"],
        do_probe=False)
    assert rec["window_tokens"] == 2048, rec


# ---------------------------------------------------------------------------
# R-C67-1 件②：端到端接线牙（删 window_tokens 实参必须红在本格）
# ---------------------------------------------------------------------------
def test_c67_r1_pipeline_wiring_window_reaches_align(monkeypatch):
    """monkeypatch resolve→2048，走 pack_window_for_panel／run_case ⇒ window=2048 且 budget 变小。"""
    clear_model_ctx_probe_cache()
    s = _settings(
        material_char_budget=80_000, model_context_tokens=16384,
        zh_chars_per_token=1.45, pack_to_window=True,
        models=["openai/m"])
    d = _many_sources(50, seg_chars=500)
    # 基线：全局 16384 装箱
    base_pw = align_budget_to_window(
        d, s, persona=MAINSTREAM_PERSONA, profile_tier="standard",
        window_tokens=16384)
    monkeypatch.setattr(
        "app.config.resolve_panel_min_window",
        lambda *_a, **_k: {
            "window_tokens": 2048,
            "source": "declared",
            "rule": "align_to_window",
            "detail": "source=declared",
            "per_model": [],
            "used_fallback": False,
        })
    # 真接线路径①：抽出的 pack_window_for_panel
    pw = pack_window_for_panel(
        d, s, [SimpleNamespace(model="openai/m")],
        persona=MAINSTREAM_PERSONA, profile_tier="standard")
    assert pw["window_tokens"] == 2048, pw
    assert pw["budget"] < base_pw["budget"], (
        f"2048 budget={pw['budget']} 应小于 16384 budget={base_pw['budget']}")
    # 真接线路径②：run_case 最小驱动（同 monkeypatch）
    d2 = _many_sources(50, seg_chars=500)
    result = run_case(
        RunSpec(dossier=d2, settings=s, probe=False),
        RunDeps(client=_StubClient()),
    )
    pw2 = (result.dossier.accounting or {}).get("pack_window") or {}
    assert pw2.get("window_tokens") == 2048, pw2
    assert int(pw2.get("budget") or 0) < base_pw["budget"]


# ---------------------------------------------------------------------------
# R-C67-1 件③①：env 显式全局当声明（摘掉 env 层 ⇒ 本格红）
# ---------------------------------------------------------------------------
def test_c67_r1_env_global_acts_as_declaration(monkeypatch):
    """无 num_ctx 时，env 显式 VERITAS_MODEL_CTX_TOKENS 必须当声明压住 4096。"""
    clear_model_ctx_probe_cache()
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "8192")
    # 避免 from_json 干扰：直接造 Settings 并钉 env 旗
    s = _settings(
        model_context_tokens=8192,
        model_ctx_tokens_env_set=True,  # ← 摘掉这层（改 False）必须红
        model_context_tokens_by_model={},
        model_context_fallback_tokens=MODEL_CTX_FALLBACK_DEFAULT,
        models=["qwen3:14b"])
    rec = resolve_model_window(
        s, "qwen3:14b",
        probe_fn=lambda *_a, **_k: PROBE_NO_NUM_CTX)
    assert rec["window_tokens"] == 8192, rec
    assert rec["source"] == "env_global", rec
    assert rec["window_tokens"] != MODEL_CTX_FALLBACK_DEFAULT


# ---------------------------------------------------------------------------
# R-C67-1 件③②：每模表按裸名查得到（忽略裸名分支 ⇒ 本格红）
# ---------------------------------------------------------------------------
def test_c67_r1_by_model_bare_name_lookup():
    """表键写 qwen3:14b，查询 openai/qwen3:14b 必须命中 2048。"""
    clear_model_ctx_probe_cache()
    s = _settings(
        model_context_tokens=16384,
        model_context_tokens_by_model={"qwen3:14b": 2048},
        model_ctx_tokens_env_set=False,
        models=["openai/qwen3:14b"])
    # 行为断言：lookup 与 resolve 都必须吃到裸名
    assert lookup_declared_model_ctx(s, "openai/qwen3:14b") == 2048
    rec = resolve_model_window(s, "openai/qwen3:14b", do_probe=False)
    assert rec["window_tokens"] == 2048, rec
    assert rec["source"] == "declared"
