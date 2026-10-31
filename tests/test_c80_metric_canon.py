"""C-80：抽取侧规范量名（rule:v1）；默认开；原 metric 保留；分组键优先 canon。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.fact_ledger import (
    CANON_VOCAB_SOURCE,
    Fact,
    _collisions_from_facts,
    _scan,
    assign_metric_canon,
    build_dispersion_tag_map,
    fact_group_metric,
    format_canon_disclosure,
    metric_canon_enabled,
    set_metric_canon,
)

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_flag():
    # 测完复位到生产默认（开）
    set_metric_canon(True)
    yield
    set_metric_canon(True)


def _load_mutated(name: str, old: str, new: str, tmp_path: Path):
    raw = (_ROOT / name).read_text(encoding="utf-8")
    assert old in raw, f"变异针漂移：{name!r}"
    dest = tmp_path / name.replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(raw.replace(old, new, 1), encoding="utf-8")
    mod_name = f"c80_mut_{dest.stem}_{abs(hash(new)) & 0xFFFF:x}"
    spec = importlib.util.spec_from_file_location(mod_name, dest)
    mod = types.ModuleType(mod_name)
    sys.modules[mod_name] = mod
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _fact(entity: str, metric: str, value: float, *, sid: str, seg: str,
          raw: str | None = None, metric_canon: str = "",
          canon_reason: str = "") -> Fact:
    return Fact(
        entity=entity, metric=metric, value=float(value),
        raw=raw if raw is not None else str(value),
        source_id=sid, seg_id=seg, date="",
        metric_canon=metric_canon, canon_reason=canon_reason,
    )


def _dossier_with(*pairs: tuple[str, str]) -> Dossier:
    """pairs = (sid, text)。"""
    d = Dossier(question="客户B回款如何？")
    for sid, text in pairs:
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid, text=text, index=0))
        d.add_source(src)
    return d


# ---- 默认／开关 ----
def test_c80_defaults_metric_canon_on():
    """刀：Settings.metric_canon 默认翻 False ⇒ 本格红（Boyu 10-28 拍现在开）。"""
    s = Settings()
    assert s.metric_canon is True
    assert metric_canon_enabled() is True


def test_c80_c69_defaults_still_on():
    """不许顺手改 C-69 默认。"""
    s = Settings()
    assert s.source_time_unified is True
    assert s.ledger_time_class is True


def test_c80_flag_off_leaves_fields_empty_and_groups_by_metric():
    """关闸：_scan 不填 canon；分组键仍走原文 metric。"""
    set_metric_canon(False)
    d = _dossier_with(
        ("S1", "客户B回款率40%。"),
        ("S2", "客户B回款率50%。"),
    )
    facts, stats = _scan(d)
    assert "metric_canon" not in stats
    assert facts
    assert all(f.metric_canon == "" and f.canon_reason == "" for f in facts)
    assert all(fact_group_metric(f) == f.metric for f in facts)


# ---- 判据 a／b：覆盖账＋值域来源 ----
def test_c80_assign_ok_junk_hint_empty_whitespace():
    """rule:v1：量名 ok；垃圾拒填；无量词提示拒填；空；只压空白。"""
    assert assign_metric_canon("回款率") == ("回款率", "ok")
    assert assign_metric_canon("联系电话") == ("", "not_quantity")
    assert assign_metric_canon("风闻社区") == ("", "not_quantity")
    assert assign_metric_canon("某某栏目") == ("", "no_quantity_hint")
    assert assign_metric_canon("") == ("", "empty")
    assert assign_metric_canon(" 回 款 率 ") == ("回款率", "ok")
    # 禁止别名合并（C-76 路已关）
    a, _ = assign_metric_canon("回款率")
    b, _ = assign_metric_canon("收款率")
    assert a == "回款率" and b == "收款率" and a != b


def test_c80_a_coverage_and_disclosure_from_data():
    """判据 a：覆盖数字当场算；披露含有／缺／原因／rule:v1。"""
    set_metric_canon(True)
    facts = [
        _fact("客户B", "回款率", 0.4, sid="S1", seg="S1#s1",
              metric_canon="回款率", canon_reason="ok"),
        _fact("客户B", "联系电话", 12345, sid="S2", seg="S2#s1",
              metric_canon="", canon_reason="not_quantity"),
        _fact("客户B", "某某栏目", 1, sid="S3", seg="S3#s1",
              metric_canon="", canon_reason="no_quantity_hint"),
    ]
    # 走 _canon_coverage 路径：塞进假 stats
    from app.core.fact_ledger import _canon_coverage
    block = _canon_coverage(facts)
    assert block["n_ok"] == 1
    assert block["n_missing"] == 2
    assert block["missing_by_reason"]["not_quantity"] == 1
    assert block["missing_by_reason"]["no_quantity_hint"] == 1
    assert block["vocab_source"] == CANON_VOCAB_SOURCE == "rule:v1"
    line = format_canon_disclosure({"metric_canon": block})
    assert "规范量名覆盖：有 1／缺 2" in line
    assert "not_quantity 1" in line
    assert "no_quantity_hint 1" in line
    assert "值域来源 rule:v1" in line
    assert "model" not in line.lower()


def test_c80_a_knife_constant_disclosure_must_differ(tmp_path):
    """把 format_canon_disclosure 改成常量 ⇒ 真数消失（钉牙）。"""
    old = (
        '    return f"规范量名覆盖：有 {n_ok}／缺 {n_miss}{why}；值域来源 {src}"'
    )
    new = '    return "规范量名覆盖：常量披露"  # c80-knife'
    mod = _load_mutated("app/core/fact_ledger.py", old, new, tmp_path)
    block = {
        "n_ok": 7, "n_missing": 3,
        "missing_by_reason": {"not_quantity": 3},
        "vocab_source": "rule:v1",
    }
    broken = mod.format_canon_disclosure({"metric_canon": block})
    assert "有 7" not in broken
    assert "常量披露" in broken
    real = format_canon_disclosure({"metric_canon": block})
    assert "有 7／缺 3" in real


def test_c80_b_vocab_source_is_rule_v1_not_alias_table():
    """判据 b：值域来源可追＝rule:v1；源码无别名合并表话术。"""
    assert CANON_VOCAB_SOURCE == "rule:v1"
    src = (_ROOT / "app/core/fact_ledger.py").read_text(encoding="utf-8")
    assert 'CANON_VOCAB_SOURCE = "rule:v1"' in src
    assert "不许在这里做「回款率≈收款率」别名合并" in src
    # 不许把 C-76 别名路重新开进来
    assert "ALIAS" not in src
    assert "alias_map" not in src


# ---- 分组键／原 metric 保留 ----
def test_c80_group_key_uses_canon_when_on():
    """开闸且有规范名 → 分组键＝canon；原文 metric 仍在。"""
    set_metric_canon(True)
    f = _fact("客户B", "回 款 率", 0.4, sid="S1", seg="S1#s1",
              metric_canon="回款率", canon_reason="ok")
    assert f.metric == "回 款 率"
    assert fact_group_metric(f) == "回款率"


def test_c80_whitespace_identity_groups_together():
    """只压空白的身份归一：两行不同空白同量 → 同组对撞。"""
    set_metric_canon(True)
    facts = [
        _fact("客户B", "回款率", 0.4, sid="S1", seg="S1#s1",
              metric_canon="回款率", canon_reason="ok"),
        _fact("客户B", "回 款 率", 0.5, sid="S2", seg="S2#s1",
              metric_canon="回款率", canon_reason="ok"),
    ]
    cols = _collisions_from_facts(facts)
    assert len(cols) == 1
    assert cols[0].metric == "回款率"
    # 逐字引用仍用原文 metric
    cited = {f.metric for f in cols[0].facts}
    assert "回款率" in cited and "回 款 率" in cited


def test_c80_no_alias_merge_reverse():
    """反向：回款率≠收款率 —— 不许因「像」就并组（C-76 关账不重开）。"""
    set_metric_canon(True)
    facts = [
        _fact("客户B", "回款率", 0.4, sid="S1", seg="S1#s1",
              metric_canon="回款率", canon_reason="ok"),
        _fact("客户B", "收款率", 0.5, sid="S2", seg="S2#s1",
              metric_canon="收款率", canon_reason="ok"),
    ]
    cols = _collisions_from_facts(facts)
    assert cols == []


def test_c80_scan_fills_canon_and_stats():
    """开闸 _scan：量名得 canon；垃圾类原因入账。"""
    set_metric_canon(True)
    d = _dossier_with(
        ("S1", "客户B回款率40%。"),
        ("S2", "联系电话12345。"),
    )
    facts, stats = _scan(d)
    assert "metric_canon" in stats
    cov = stats["metric_canon"]
    assert cov["vocab_source"] == "rule:v1"
    ok = [f for f in facts if f.canon_reason == "ok"]
    assert ok and all(f.metric_canon for f in ok)
    # 原文 metric 未丢
    assert all(f.metric for f in facts)


def test_c80_dispersion_groups_by_canon():
    """离群分组也走 fact_group_metric。"""
    set_metric_canon(True)
    facts = [
        _fact("客户B", "回款率", 10, sid="S1", seg="S1#s1",
              metric_canon="回款率", canon_reason="ok"),
        _fact("客户B", "回 款 率", 20, sid="S2", seg="S2#s1",
              metric_canon="回款率", canon_reason="ok"),
        _fact("客户B", "回款率", 30, sid="S3", seg="S3#s1",
              metric_canon="回款率", canon_reason="ok"),
        _fact("客户B", "回款率", 100, sid="S4", seg="S4#s1",
              metric_canon="回款率", canon_reason="ok"),
    ]
    tags = build_dispersion_tag_map(facts, k=3)
    assert tags, "同 canon 四值应成组"


def test_c80_report_renders_canon_disclosure_when_on():
    """开关开 ⇒ 报告台账章含规范量名覆盖行；关 ⇒ 不含。"""
    from app.pipeline import _render_fact_collisions

    d = _dossier_with(
        ("S1", "客户B回款率40%。"),
        ("S2", "客户B回款率50%。"),
    )
    set_metric_canon(True)
    # 预落 accounting，避免二次语义分叉
    facts, stats = _scan(d)
    d.accounting = {"fact_ledger_stats": stats}

    lines_on: list[str] = []
    _render_fact_collisions(lines_on, d)
    text_on = "\n".join(lines_on)
    assert "规范量名覆盖：" in text_on
    assert "值域来源 rule:v1" in text_on

    set_metric_canon(False)
    lines_off: list[str] = []
    # 关闸时若 stats 仍带旧 metric_canon 键，仍以旗为准不披露
    d.accounting = {"fact_ledger_stats": stats}
    _render_fact_collisions(lines_off, d)
    text_off = "\n".join(lines_off)
    assert "规范量名覆盖：" not in text_off


def test_c80_precedent_groups_by_canon():
    """precedent._candidate_pairs 分组键走 fact_group_metric（夹具对齐 C-29）。"""
    from app.core import precedent as prec

    set_metric_canon(True)
    d = Dossier(question="客户B的回款情况如何？")
    for sid, text, day in [
        ("SRC1", "2024年1月客户B回款率40%。项目进展正常。", "2024-01-15"),
        ("SRC2", "2025年6月客户B回款率25%。回款明显恶化。", "2025-06-01"),
    ]:
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.meta["published_at"] = day
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid, text=text, index=0))
        d.add_source(src)
    pairs = prec._candidate_pairs(d)
    assert pairs, "同规范量名跨波次应出对照候选"
    # 分组键为规范名时仍能配对；关闸也应能配对（回退 metric）
    set_metric_canon(False)
    pairs_off = prec._candidate_pairs(d)
    assert pairs_off, "关闸回退原文 metric 仍应出对"


def test_c80_e_deterministic_cross_process(tmp_path):
    """判据 f 形：同一夹具跨进程两遍逐字相同。"""
    script = tmp_path / "run_canon.py"
    script.write_text(
        "import json, sys\n"
        "sys.path.insert(0, %r)\n"
        "from app.core.fact_ledger import (\n"
        "  assign_metric_canon, format_canon_disclosure, set_metric_canon,\n"
        "  _canon_coverage, Fact)\n"
        "set_metric_canon(True)\n"
        "facts = [\n"
        " Fact('B','回款率',0.4,'40','S1','S1#s1','',\n"
        "      *assign_metric_canon('回款率')),\n"
        " Fact('B','联系电话',1.,'1','S2','S2#s1','',\n"
        "      *assign_metric_canon('联系电话')),\n"
        "]\n"
        "block = _canon_coverage(facts)\n"
        "line = format_canon_disclosure({'metric_canon': block})\n"
        "print(json.dumps({'line': line, 'block': block}, "
        "ensure_ascii=False, sort_keys=True))\n"
        % str(_ROOT),
        encoding="utf-8",
    )
    py = _ROOT / ".venv" / "bin" / "python"
    cmd = [str(py) if py.is_file() else sys.executable, str(script)]
    out1 = subprocess.check_output(cmd, text=True)
    out2 = subprocess.check_output(cmd, text=True)
    assert out1 == out2
    assert "rule:v1" in out1
    assert "有 1" in out1


def test_c80_knife_drop_junk_gate_must_red(tmp_path):
    """反向刀：废掉垃圾拒填 ⇒ 联系电话拿到规范名（钉牙）。"""
    old = "    if m in _JUNK_METRICS:\n        return \"\", \"not_quantity\""
    new = "    if False:  # c80-knife\n        return \"\", \"not_quantity\""
    mod = _load_mutated("app/core/fact_ledger.py", old, new, tmp_path)
    broken_canon, broken_reason = mod.assign_metric_canon("联系电话")
    assert broken_canon == "联系电话" or broken_reason != "not_quantity"
    real_canon, real_reason = assign_metric_canon("联系电话")
    assert real_canon == "" and real_reason == "not_quantity"


def test_c80_forbidden_judgment_files_untouched():
    """六判定文件关键符号仍在（不许用 git diff 常驻格）。"""
    needles = {
        "app/core/confidence.py": "_CAUSATION_BONUS",
        "app/core/evidence.py": "class Dossier",
        "app/core/conflicts.py": "def apply_resolution",
        "app/core/material.py": "def pack_material",
        "app/core/bm25.py": "def rank_segments",
        "app/core/relevance.py": "def classify_sources",
    }
    for path, needle in needles.items():
        src = (_ROOT / path).read_text(encoding="utf-8")
        assert needle in src, path
