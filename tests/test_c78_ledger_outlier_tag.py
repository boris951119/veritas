"""C-78：对撞行「组内相对偏差（中位数±k×MAD）」派生标签；默认开；零判定。"""
from __future__ import annotations

import hashlib
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
    DISPERSION_LABEL,
    Fact,
    build_dispersion_tag_map,
    dispersion_accounting,
    ledger_outlier_tag_enabled,
    normalize_entity,
    set_ledger_outlier_tag,
)
from app.pipeline import _render_fact_collisions

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_flag():
    # 测完复位到生产默认（开）
    set_ledger_outlier_tag(True)
    yield
    set_ledger_outlier_tag(True)


def _load_mutated(name: str, old: str, new: str, tmp_path: Path):
    raw = (_ROOT / name).read_text(encoding="utf-8")
    assert old in raw, f"变异针漂移：{name!r}"
    dest = tmp_path / name.replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(raw.replace(old, new, 1), encoding="utf-8")
    mod_name = f"c78_mut_{dest.stem}_{abs(hash(new)) & 0xFFFF:x}"
    spec = importlib.util.spec_from_file_location(mod_name, dest)
    mod = types.ModuleType(mod_name)
    sys.modules[mod_name] = mod
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _fact(entity: str, metric: str, value: float, *, sid: str, seg: str,
          raw: str | None = None) -> Fact:
    return Fact(
        entity=entity, metric=metric, value=float(value),
        raw=raw if raw is not None else str(value),
        source_id=sid, seg_id=seg, date="",
    )


def _mad0_facts() -> list[Fact]:
    """R-C78-1：≥3 不同数值且 MAD=0（5,5,5,9,10 → med=5，偏差中位=0）。

    ⚠ 旧夹具「三同一异」只有 2 个不同值，会被 n<3 先挡掉＝MAD=0 门槛假牙。
    """
    return [
        _fact("乙司", "利润", 5, sid="U1", seg="U1#s1"),
        _fact("乙司", "利润", 5, sid="U2", seg="U2#s1"),
        _fact("乙司", "利润", 5, sid="U3", seg="U3#s1"),
        _fact("乙司", "利润", 9, sid="U4", seg="U4#s1"),
        _fact("乙司", "利润", 10, sid="U5", seg="U5#s1"),
    ]


def _fixture_facts() -> list[Fact]:
    """夹具：① n≥3 MAD>0 真组（含离群）② n=2 组 ③ MAD=0 且 n_distinct≥3。"""
    # 组 A：客户回款率＝10／20／30／100 ⇒ med=25，MAD=10；100 超 25+30
    a = [
        _fact("客户B", "回款率", 10, sid="S1", seg="S1#s1"),
        _fact("客户B", "回款率", 20, sid="S2", seg="S2#s1"),
        _fact("客户B", "回款率", 30, sid="S3", seg="S3#s1"),
        _fact("客户B", "回款率", 100, sid="S4", seg="S4#s1"),
    ]
    # 组 B：n=2 —— 不许标
    b = [
        _fact("甲公司", "营收", 1, sid="T1", seg="T1#s1"),
        _fact("甲公司", "营收", 9, sid="T2", seg="T2#s1"),
    ]
    return a + b + _mad0_facts()


# ---- 暗开关默认 ----
def test_c78_defaults_ledger_outlier_tag_on():
    """刀：Settings.ledger_outlier_tag 默认翻 False ⇒ 本格红（Boyu 拍开）。"""
    s = Settings()
    assert s.ledger_outlier_tag is True
    assert ledger_outlier_tag_enabled() is True


def test_c78_a_tag_numbers_from_data_not_constant():
    """判据 a：标签数字＝当场算出；改成常量文案 ⇒ 真数不在（本格钉牙）。"""
    facts = _fixture_facts()
    tags = build_dispersion_tag_map(facts, k=3)
    assert tags, "n≥3 MAD>0 组必须至少一条标签"
    joined = "\n".join(sorted(tags.values()))
    assert DISPERSION_LABEL in joined
    assert "中位 25" in joined
    assert "MAD 10" in joined
    assert "此值 100" in joined
    assert "偏离 3×MAD" in joined
    assert "正态" not in joined
    assert "异常检测" not in joined
    # 自证：常量文案不含真数
    fake = "组内相对偏差（中位数±k×MAD）：标为可疑"
    assert "中位 25" not in fake


def test_c78_a_knife_constant_note_must_differ(tmp_path):
    """把 format_dispersion_note 改成常量 ⇒ 真数消失（正向格会红的红名位）。"""
    old = (
        '    return (\n'
        '        f"{DISPERSION_LABEL}：中位 {_fmt_num(med)}，MAD {_fmt_num(mad)}，"\n'
        '        f"此值 {_fmt_num(value)} 偏离 {int(k)}×MAD ⇒ 标为可疑"\n'
        '    )'
    )
    new = (
        '    return (\n'
        '        f"{DISPERSION_LABEL}：常量标签"  # c78-knife\n'
        '    )'
    )
    mod = _load_mutated("app/core/fact_ledger.py", old, new, tmp_path)
    tags = mod.build_dispersion_tag_map(_fixture_facts(), k=3)
    joined = "\n".join(tags.values())
    assert "中位 25" not in joined
    assert "常量标签" in joined
    # 真树仍有真数
    real = build_dispersion_tag_map(_fixture_facts(), k=3)
    assert any("中位 25" in v for v in real.values())


def test_c78_c_fixture_has_three_group_shapes():
    """判据 c：夹具含 n≥3 MAD>0／n=2／MAD=0。"""
    facts = _fixture_facts()
    tags = build_dispersion_tag_map(facts, k=3)
    # 真组：100 被标
    assert any("此值 100" in v for v in tags.values())
    # n=2 组键
    n2 = [f for f in facts if f.metric == "营收"]
    assert len({f.value for f in n2}) == 2
    assert not any(f.metric == "营收" and _fact_key_in(tags, f) for f in n2)
    # MAD=0 组
    mad0 = [f for f in facts if f.metric == "利润"]
    assert len({f.value for f in mad0}) >= 2
    assert not any(_fact_key_in(tags, f) for f in mad0)


def _fact_key_in(tags, f: Fact) -> bool:
    return (f.source_id, f.seg_id, float(f.value)) in tags


def test_c78_d_n2_and_mad0_must_not_tag():
    """判据 d：n=2 与 MAD=0（且 n_distinct≥3）反向腿——单独断言不许出标签。"""
    n2 = [
        _fact("甲公司", "营收", 1, sid="T1", seg="T1#s1"),
        _fact("甲公司", "营收", 9, sid="T2", seg="T2#s1"),
    ]
    assert build_dispersion_tag_map(n2, k=3) == {}

    mad0 = _mad0_facts()
    import statistics
    vals = [f.value for f in mad0]
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals])
    assert mad == 0
    assert len(set(vals)) >= 3, "R-C78-1：MAD=0 夹具必须先过 n_distinct≥3，否则门槛假牙"
    assert build_dispersion_tag_map(mad0, k=3) == {}


def test_c78_d_knife_force_tag_n2_must_red(tmp_path):
    """反向刀：废掉 n≥3 门槛且组内全标 ⇒ n=2 出标签（钉 d 反向腿有牙）。"""
    raw = (_ROOT / "app/core/fact_ledger.py").read_text(encoding="utf-8")
    old1 = "        if len(distinct) < 3:\n            continue"
    old2 = "            if v < lo or v > hi:"
    assert old1 in raw and old2 in raw
    poisoned = (raw.replace(old1, "        if len(distinct) < 2:  # c78-knife\n            continue", 1)
                    .replace(old2, "            if True:  # c78-knife force tag", 1))
    dest = tmp_path / "fact_ledger_mut.py"
    dest.write_text(poisoned, encoding="utf-8")
    mod_name = f"c78_mut_n2_{abs(hash(poisoned)) & 0xFFFF:x}"
    spec = importlib.util.spec_from_file_location(mod_name, dest)
    mod = types.ModuleType(mod_name)
    sys.modules[mod_name] = mod
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    n2 = [
        _fact("甲公司", "营收", 1, sid="T1", seg="T1#s1"),
        _fact("甲公司", "营收", 9, sid="T2", seg="T2#s1"),
    ]
    broken = mod.build_dispersion_tag_map(n2, k=3)
    assert broken, "变异后 n=2 应出标签"
    assert build_dispersion_tag_map(n2, k=3) == {}


def test_c78_r1_knife_drop_mad0_gate_must_red(tmp_path):
    """R-C78-1：摘掉 `mad <= 0` 门槛 ⇒ MAD=0 真组出标签（钉牙；复位后绿）。"""
    raw = (_ROOT / "app/core/fact_ledger.py").read_text(encoding="utf-8")
    old = "        if mad <= 0:\n            continue"
    assert old in raw, "变异针漂移：mad<=0 门槛"
    poisoned = raw.replace(old, "        if False:  # c78-r1-knife\n            continue", 1)
    dest = tmp_path / "fact_ledger_mad0.py"
    dest.write_text(poisoned, encoding="utf-8")
    mod_name = f"c78_mut_mad0_{abs(hash(poisoned)) & 0xFFFF:x}"
    spec = importlib.util.spec_from_file_location(mod_name, dest)
    mod = types.ModuleType(mod_name)
    sys.modules[mod_name] = mod
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    mad0 = _mad0_facts()
    broken = mod.build_dispersion_tag_map(mad0, k=3)
    assert broken, "摘 MAD=0 门槛后应标出 9／10"
    assert any("此值 9" in v or "此值 10" in v for v in broken.values())
    assert build_dispersion_tag_map(mad0, k=3) == {}


def test_c78_r2_facts_block_never_gets_dispersion_label():
    """R-C78-2：开／关旗下 facts_block 都不含派生标签短语（不进提示词）。"""
    from app.core.evidence import Dossier, Segment, Source, SourceType
    from app.core.fact_ledger import facts_block

    d = Dossier(question="客户B回款如何？")
    for sid, text in [
        ("S1", "客户B回款率10%。"),
        ("S2", "客户B回款率20%。"),
        ("S3", "客户B回款率30%。"),
        ("S4", "客户B回款率100%。"),
    ]:
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid, text=text, index=0))
        d.add_source(src)

    set_ledger_outlier_tag(False)
    off = facts_block(d)
    set_ledger_outlier_tag(True)
    on = facts_block(d)
    assert off == on, "facts_block 不得因开旗改写"
    assert DISPERSION_LABEL not in off
    assert DISPERSION_LABEL not in on


def test_c78_e_deterministic_cross_process(tmp_path):
    """判据 e：同一夹具跨进程两遍逐字相同。"""
    script = tmp_path / "run_tags.py"
    script.write_text(
        "import json, sys\n"
        "sys.path.insert(0, %r)\n"
        "from app.core.fact_ledger import Fact, build_dispersion_tag_map\n"
        "facts = [\n"
        " Fact('客户B','回款率',10.,'10','S1','S1#s1',''),\n"
        " Fact('客户B','回款率',20.,'20','S2','S2#s1',''),\n"
        " Fact('客户B','回款率',30.,'30','S3','S3#s1',''),\n"
        " Fact('客户B','回款率',100.,'100','S4','S4#s1',''),\n"
        " Fact('甲公司','营收',1.,'1','T1','T1#s1',''),\n"
        " Fact('甲公司','营收',9.,'9','T2','T2#s1',''),\n"
        "]\n"
        "tags = build_dispersion_tag_map(facts, k=3)\n"
        "items = sorted((list(k), v) for k, v in tags.items())\n"
        "print(json.dumps(items, ensure_ascii=False, sort_keys=True))\n"
        % str(_ROOT),
        encoding="utf-8",
    )
    py = _ROOT / ".venv" / "bin" / "python"
    cmd = [str(py) if py.is_file() else sys.executable, str(script)]
    out1 = subprocess.check_output(cmd, text=True)
    out2 = subprocess.check_output(cmd, text=True)
    assert out1 == out2
    assert "中位 25" in out1


def test_c78_report_render_appends_when_flag_on():
    """开关开 ⇒ 报告对撞行含派生标签；关 ⇒ 不含标签短语。"""
    d = Dossier(question="客户B回款如何？")
    for i, (sid, val, text) in enumerate([
        ("S1", 10, "客户B回款率10%。"),
        ("S2", 20, "客户B回款率20%。"),
        ("S3", 30, "客户B回款率30%。"),
        ("S4", 100, "客户B回款率100%。"),
    ], start=1):
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid, text=text, index=0))
        d.add_source(src)

    set_ledger_outlier_tag(False)
    lines_off: list[str] = []
    _render_fact_collisions(lines_off, d)
    text_off = "\n".join(lines_off)
    assert DISPERSION_LABEL not in text_off

    set_ledger_outlier_tag(True)
    lines_on: list[str] = []
    _render_fact_collisions(lines_on, d)
    text_on = "\n".join(lines_on)
    assert DISPERSION_LABEL in text_on
    # extract_nums 把「100%」缩放到 1.0 —— 标签数字必须跟缩放后真值走
    assert "此值 1" in text_on
    assert "中位 0.25" in text_on
    assert "正态" not in text_on


def test_c78_accounting_keeps_k5_for_compare_only():
    """k=5 进 accounting；报告文案只用 k=3。"""
    facts = _fixture_facts()
    acc = dispersion_accounting(facts)
    assert acc["k_report"] == 3
    assert acc["label"] == DISPERSION_LABEL
    assert acc["k3_n_tagged"] >= 1
    assert "k5_n_tagged" in acc
    # 报告标签只有 k=3
    tags = build_dispersion_tag_map(facts, k=3)
    assert all("偏离 3×MAD" in v for v in tags.values())


def test_c78_normalize_entity_strips_noise():
    """去数字／标点／空白；汉字年月按定义保留（不是日期语义剥离）。"""
    assert normalize_entity("客户-B") == normalize_entity("客户B")
    assert normalize_entity("客户 B") == "客户b"
    assert normalize_entity("2024年1月客户B") == "年月客户b"


def test_c78_b_forbidden_paths_constants_untouched():
    """判据 b 内容钉：六判定文件关键符号仍在（不许用 git diff 常驻格）。"""
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
