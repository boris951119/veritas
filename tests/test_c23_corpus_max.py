"""C-23：大库选料上限可配、默认 100（判据 a-in／b–h／k′）。

零 LLM。长期约束写成对源码／settings 的内容断言（k′ 禁瞬时状态串）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.base import Analyst
from app.config import Settings, _coerce_corpus_select_max
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.pipeline import RunDeps, RunSpec, _load_case_dossier, run_case
from tests.test_agents_pipeline import GOOD_BAD_JSON, FakeClient

ROOT = Path(__file__).resolve().parents[1]


def _sixty_case(tmp_path: Path, *, n: int = 60) -> Path:
    case = tmp_path / "biglib"
    case.mkdir(parents=True)
    (case / "manifest.yaml").write_text(
        "question: 中国银行净利润是多少\n"
        "title: 大库夹具\n",
        encoding="utf-8",
    )
    for i in range(n):
        (case / f"s{i:03d}.md").write_text(
            f"# 材料{i}\n\n中国银行净利润相关段落{i}。"
            f"补充句子保证切片非空。\n",
            encoding="utf-8",
        )
    return case


def _blank_json(monkeypatch) -> None:
    """避开仓库根 config.json，从代码默认再叠 env。"""

    def _blank(cls, path=None):
        return cls()

    monkeypatch.setattr(Settings, "from_json", classmethod(_blank))


def _settings(*, min_s: int = 50, max_s: int = 100,
              notes: list[str] | None = None) -> Settings:
    return Settings(
        corpus_select_min_sources=min_s,
        corpus_select_max_sources=max_s,
        corpus_select_max_disclosures=list(notes or []),
    )


# -- a-in ----------------------------------------------------------------


def test_a_in_injected_skips_select_dir_form_has_key(tmp_path, monkeypatch):
    """注入 RunSpec(dossier=...) 无 corpus_select；目录形态 60 份必须有该键。"""
    counts = {"from_index": 0, "narrow": 0}

    import app.core.corpus_store as store_mod
    import app.core.corpus_index as index_mod

    real_from = store_mod.dossier_from_case_index
    real_narrow = index_mod.narrow_dossier

    def counting_from(*a, **k):
        counts["from_index"] += 1
        return real_from(*a, **k)

    def counting_narrow(*a, **k):
        counts["narrow"] += 1
        return real_narrow(*a, **k)

    monkeypatch.setattr(store_mod, "dossier_from_case_index", counting_from)
    monkeypatch.setattr(index_mod, "narrow_dossier", counting_narrow)

    # 面一：官方卷同形＝注入 dossier，不进选料
    src = Source.create("T", SourceType.PAPER, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="全固态电芯的中试良率尚不足百分之四十。",
        locator="段 1"))
    injected = Dossier(question="注入议题", sources=[src])
    case_dir = tmp_path / "inj"
    case_dir.mkdir()
    (case_dir / "manifest.yaml").write_text(
        "question: 注入议题\n", encoding="utf-8")
    client = FakeClient(GOOD_BAD_JSON)
    single = [Analyst("mainstream", "测", client, "m")]
    result = run_case(
        RunSpec(case_dir=case_dir, out_dir=case_dir / "out",
                dossier=injected, probe=False),
        RunDeps(client=client, analysts=single),
    )
    assert "corpus_select" not in (result.dossier.accounting or {})
    assert counts["from_index"] == 0
    assert counts["narrow"] == 0

    # 面二：目录形态 60 份 → 必有 corpus_select
    big = _sixty_case(tmp_path / "dir60")
    out = _load_case_dossier(big, _settings(min_s=50, max_s=100))
    assert "corpus_select" in (out.accounting or {})
    assert counts["from_index"] >= 1


# -- a-out（只附报） -----------------------------------------------------


def test_a_out_s4runs_attach_only_no_assert_on_missing():
    """仓库外产物树缺席则跳过；有则只附报、零断言绑在跑产物上。"""
    root = Path("/tmp/s4runs/time-20261017-224837")
    if not root.is_dir():
        pytest.skip("a-out 产物树不在本机，只附报")
    # 有树也不建断言——架构师对照数见工单；此处仅证明路径可达
    assert root.is_dir()


# -- b -------------------------------------------------------------------


def test_b_sixty_sources_all_selected_at_default_max(tmp_path):
    big = _sixty_case(tmp_path)
    out = _load_case_dossier(big, _settings(min_s=50, max_s=100))
    disc = out.accounting["corpus_select"]
    assert disc["n_selected_sources"] == 60
    assert disc["omitted_sources"] == 0
    assert disc["max_sources"] == 100


# -- c -------------------------------------------------------------------


def test_c_env_max_20(tmp_path, monkeypatch):
    """默认 MIN=50 下只设 MAX=20 → 收窄到 20；max<min 专门披露在场。"""
    _blank_json(monkeypatch)
    monkeypatch.delenv("VERITAS_CORPUS_SELECT_MIN", raising=False)
    monkeypatch.setenv("VERITAS_CORPUS_SELECT_MAX", "20")
    s = Settings.from_env()
    assert s.corpus_select_max_sources == 20
    assert s.corpus_select_min_sources == 50
    blob = "｜".join(s.corpus_select_max_disclosures)
    assert "上限 20" in blob and "触发门槛 50" in blob
    assert "回落 100" not in blob
    big = _sixty_case(tmp_path)
    out = _load_case_dossier(big, s)
    disc = out.accounting["corpus_select"]
    assert disc["n_selected_sources"] == 20
    assert disc["omitted_sources"] == 40
    assert disc["max_sources"] == 20
    notes = out.accounting.get("corpus_select_max_disclosures") or []
    assert any("上限 20" in n and "50" in n for n in notes)


def test_c_config_json_max_20(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"corpus_select_max_sources": 20}),
                   encoding="utf-8")
    s = Settings.from_json(cfg).validate()
    assert s.corpus_select_max_sources == 20
    assert s.corpus_select_min_sources == 50
    blob = "｜".join(s.corpus_select_max_disclosures)
    assert "上限 20" in blob and "触发门槛 50" in blob
    big = _sixty_case(tmp_path / "lib")
    out = _load_case_dossier(big, s)
    disc = out.accounting["corpus_select"]
    assert disc["n_selected_sources"] == 20
    assert disc["omitted_sources"] == 40
    assert disc["max_sources"] == 20
    notes = out.accounting.get("corpus_select_max_disclosures") or []
    assert any("上限 20" in n and "50" in n for n in notes)


# -- d -------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["0", "abc", "-5"])
def test_d_env_invalid_falls_back_100_with_disclosure(raw, monkeypatch):
    _blank_json(monkeypatch)
    monkeypatch.delenv("VERITAS_CORPUS_SELECT_MIN", raising=False)
    monkeypatch.setenv("VERITAS_CORPUS_SELECT_MAX", raw)
    s = Settings.from_env()
    assert s.corpus_select_max_sources == 100
    assert s.corpus_select_max_disclosures
    blob = "｜".join(s.corpus_select_max_disclosures)
    assert "回落 100" in blob
    assert "env VERITAS_CORPUS_SELECT_MAX" in blob


@pytest.mark.parametrize("raw", [0, "100", -3])
def test_d_config_json_invalid_falls_back_100_with_disclosure(raw, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"corpus_select_max_sources": raw}),
                   encoding="utf-8")
    s = Settings.from_json(cfg)
    assert s.corpus_select_max_sources == 100
    assert s.corpus_select_max_disclosures
    blob = "｜".join(s.corpus_select_max_disclosures)
    assert "回落 100" in blob
    assert "config.json" in blob


# -- e -------------------------------------------------------------------


def test_e_max_lt_min_keeps_max_with_special_disclosure(tmp_path, monkeypatch):
    """R-C23-1：MIN=50 MAX=10 → 上限按 10 生效＋专门披露点名两数，不回落 100。"""
    _blank_json(monkeypatch)
    monkeypatch.setenv("VERITAS_CORPUS_SELECT_MIN", "50")
    monkeypatch.setenv("VERITAS_CORPUS_SELECT_MAX", "10")
    s = Settings.from_env()
    assert s.corpus_select_max_sources == 10
    assert s.corpus_select_min_sources == 50
    blob = "｜".join(s.corpus_select_max_disclosures)
    assert "上限 10" in blob and "触发门槛 50" in blob
    assert "回落 100" not in blob
    assert "100" not in blob.replace("触发门槛 50", "")
    big = _sixty_case(tmp_path)
    out = _load_case_dossier(big, s)
    disc = out.accounting["corpus_select"]
    assert disc["n_selected_sources"] == 10
    assert disc["omitted_sources"] == 50
    assert disc["max_sources"] == 10
    notes = out.accounting.get("corpus_select_max_disclosures") or []
    assert any("上限 10" in n and "50" in n for n in notes)
    assert all("回落 100" not in n for n in notes)


# -- f -------------------------------------------------------------------


def test_f_default_max_is_100_without_env(monkeypatch):
    monkeypatch.delenv("VERITAS_CORPUS_SELECT_MAX", raising=False)
    monkeypatch.delenv("VERITAS_CORPUS_SELECT_MIN", raising=False)
    _blank_json(monkeypatch)
    s = Settings.from_env()
    assert s.corpus_select_max_sources == 100
    assert s.corpus_select_min_sources == 50
    # 调用侧显式传参（内容断言，非瞬时状态）
    src = (ROOT / "app/pipeline.py").read_text(encoding="utf-8")
    assert "max_sources=settings.corpus_select_max_sources" in src
    assert src.count("max_sources=settings.corpus_select_max_sources") == 2


def test_f_recall_gold_still_green():
    from tests.test_recall_gold import test_recall_gold_keeps_labeled_sources

    test_recall_gold_keeps_labeled_sources()


# -- h -------------------------------------------------------------------


def test_h_huge_max_still_selects_all_sixty(tmp_path):
    big = _sixty_case(tmp_path)
    out_huge = _load_case_dossier(big, _settings(max_s=10**9))
    d_huge = out_huge.accounting["corpus_select"]
    assert d_huge["n_selected_sources"] == 60
    assert d_huge["omitted_sources"] == 0

    out_100 = _load_case_dossier(
        _sixty_case(tmp_path / "a"), _settings(max_s=100))
    out_1000 = _load_case_dossier(
        _sixty_case(tmp_path / "b"), _settings(max_s=1000))
    d100 = out_100.accounting["corpus_select"]
    d1000 = out_1000.accounting["corpus_select"]
    assert d100["n_selected_sources"] == d1000["n_selected_sources"] == 60
    assert d100["omitted_sources"] == d1000["omitted_sources"] == 0


# -- k′ ------------------------------------------------------------------


def test_k_prime_no_instant_vcs_stat_in_this_file():
    needle = "git" + " diff"
    text = Path(__file__).read_text(encoding="utf-8")
    assert text.count(needle) == 0


def test_l_max_sources_key_named_in_disclosure_modules():
    """披露面点名 max_sources 字段（corpus_index／corpus_store），非「本文件」。"""
    for rel in ("app/core/corpus_index.py", "app/core/corpus_store.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert '"max_sources": max_sources' in text


def test_coerce_rejects_zero_and_bool():
    n, note = _coerce_corpus_select_max(0)
    assert n == 100 and note is not None and "回落 100" in note
    n2, note2 = _coerce_corpus_select_max(True)
    assert n2 == 100 and note2 is not None
