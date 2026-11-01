"""C-79：演变链只认数值确有变化；默认关；同值多时点＝重复报道＋黄灯。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.config import Settings
from app.core.audit import KIND_LABEL, audit_all
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.fact_ledger import Fact
from app.core.precedent import (
    REPEAT_REPORT_KIND,
    REPEAT_REPORT_LINE,
    _EVOLVE_FORBIDDEN_IN_SAME_VALUE,
    _diff_kind,
    audit_repeat_report,
    build_precedent_ledger,
    evolve_value_change_enabled,
    set_evolve_value_change,
)

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_flag():
    # 测完复位到生产默认（开）
    set_evolve_value_change(True)
    yield
    set_evolve_value_change(True)


def _load_mutated(name: str, old: str, new: str, tmp_path: Path):
    raw = (_ROOT / name).read_text(encoding="utf-8")
    assert old in raw, f"变异针漂移：{name!r}"
    dest = tmp_path / name.replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(raw.replace(old, new, 1), encoding="utf-8")
    mod_name = f"c79_mut_{dest.stem}_{abs(hash(new)) & 0xFFFF:x}"
    spec = importlib.util.spec_from_file_location(mod_name, dest)
    mod = types.ModuleType(mod_name)
    sys.modules[mod_name] = mod
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _fact(entity: str, metric: str, value: float, *, sid: str, seg: str,
          date: str, raw: str | None = None) -> Fact:
    return Fact(
        entity=entity, metric=metric, value=float(value),
        raw=raw if raw is not None else str(value),
        source_id=sid, seg_id=seg, date=date,
        metric_canon=metric, canon_reason="ok",
    )


def _same_value_two_dates() -> Dossier:
    """两时点同数值＝重复报道型夹具。"""
    d = Dossier(question="客户B的回款情况如何？")
    for sid, day, text in [
        ("SRC1", "2024-01-15", "2024年1月客户B回款率40%。项目进展正常。"),
        ("SRC2", "2025-06-01", "2025年6月客户B回款率40%。多家转述同一数字。"),
    ]:
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.meta["published_at"] = day
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid, text=text, index=0))
        d.add_source(src)
    d.accounting["material_pack_selected"] = ["SRC1#s1", "SRC2#s1"]
    return d


def _value_change_two_dates() -> Dossier:
    """两时点数值确有变化＝真演变对照。"""
    d = Dossier(question="客户B的回款情况如何？")
    for sid, day, rate, text in [
        ("SRC1", "2024-01-15", 40, "2024年1月客户B回款率40%。项目进展正常。"),
        ("SRC2", "2025-06-01", 25, "2025年6月客户B回款率25%。回款明显恶化。"),
    ]:
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.meta["published_at"] = day
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid, text=text, index=0))
        d.add_source(src)
    d.accounting["material_pack_selected"] = ["SRC1#s1", "SRC2#s1"]
    return d


def _mixed_three() -> Dossier:
    """三条：两同值＋一异值（夹具规格）。"""
    d = Dossier(question="客户B的回款情况如何？")
    rows = [
        ("SRC1", "2024-01-15", "2024年1月客户B回款率40%。材料甲。"),
        ("SRC2", "2024-06-01", "2024年6月客户B回款率40%。材料乙转载。"),
        ("SRC3", "2025-06-01", "2025年6月客户B回款率25%。材料丙恶化。"),
    ]
    for sid, day, text in rows:
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.meta["published_at"] = day
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid, text=text, index=0))
        d.add_source(src)
    d.accounting["material_pack_selected"] = [f"{s}#s1" for s, _, _ in rows]
    return d


# ---- 默认／开关 ----
def test_c79_defaults_evolve_value_change_on():
    """刀：Settings.evolve_value_change 默认翻 False ⇒ 本格红（Boyu 拍开）。"""
    s = Settings()
    assert s.evolve_value_change is True
    assert evolve_value_change_enabled() is True


def test_c79_a_same_value_no_evolve_words_when_on():
    """判据 a：开闸后数值全同组不许出演变／上升／下降。"""
    set_evolve_value_change(True)
    a = _fact("客户B", "回款率", 0.4, sid="A", seg="A#s1",
              date="20240115", raw="40%")
    b = _fact("客户B", "回款率", 0.4, sid="B", seg="B#s1",
              date="20250601", raw="40%")
    kind, desc = _diff_kind(a, b)
    blob = f"{kind}：{desc}"
    assert kind == "重复报道"
    for bad in _EVOLVE_FORBIDDEN_IN_SAME_VALUE:
        assert bad not in blob, bad
    assert "数值未变" in desc

    ledger = build_precedent_ledger(_same_value_two_dates())
    assert ledger.rows, "同值跨日仍应有对照行（标重复报道）"
    for r in ledger.rows:
        blob = f"{r.diff_kind}：{r.diff_desc}"
        for bad in _EVOLVE_FORBIDDEN_IN_SAME_VALUE:
            assert bad not in blob, blob


def test_c79_b_value_change_still_数字():
    """判据 b：数值确有变化的组照常出「数字」。"""
    set_evolve_value_change(True)
    ledger = build_precedent_ledger(_value_change_two_dates())
    assert ledger.rows
    kinds = {r.diff_kind for r in ledger.rows}
    assert "数字" in kinds
    assert "重复报道" not in kinds


def test_c79_flag_off_keeps_时点_label():
    """关闸：同值跨日仍标「时点」（与改前一致）。"""
    set_evolve_value_change(False)
    a = _fact("客户B", "回款率", 0.4, sid="A", seg="A#s1",
              date="20240115", raw="40%")
    b = _fact("客户B", "回款率", 0.4, sid="B", seg="B#s1",
              date="20250601", raw="40%")
    kind, desc = _diff_kind(a, b)
    assert kind == "时点"
    assert "同值" in desc
    assert "重复报道" not in kind


def test_c79_audit_flag_when_on():
    """开闸 ⇒ audit 出 repeat_report_time 黄灯；关闸 ⇒ 无。"""
    assert REPEAT_REPORT_KIND in KIND_LABEL
    d = _same_value_two_dates()
    set_evolve_value_change(False)
    assert audit_repeat_report(d) == []
    set_evolve_value_change(True)
    flags = audit_repeat_report(d)
    assert flags
    assert all(f["kind"] == REPEAT_REPORT_KIND for f in flags)
    assert all(REPEAT_REPORT_LINE in f["detail"] for f in flags)
    assert flags[0]["severity"] == "medium"
    # 进 audit_all
    kinds = {f["kind"] for f in audit_all(d)}
    assert REPEAT_REPORT_KIND in kinds


def test_c79_mixed_fixture_both_kinds():
    """夹具三事实：同值对→重复报道；异值对→数字。"""
    set_evolve_value_change(True)
    ledger = build_precedent_ledger(_mixed_three())
    kinds = {r.diff_kind for r in ledger.rows}
    assert "重复报道" in kinds
    assert "数字" in kinds


def test_c79_d_reverse_timepoints_as_evolve_must_red(tmp_path):
    """判据 d：把同值路径改回「时点数≥2 就算演变」⇒ 禁词复现。"""
    old = (
        '        return (\n'
        '            "重复报道",\n'
        '            f"同值 {a.raw}，时点 {a.date or \'（缺）\'} ↔ {b.date or \'（缺）\'}"\n'
        '            f"（重复报道，数值未变）",\n'
        '        )'
    )
    new = (
        '        return (\n'
        '            "演变",\n'
        '            f"同值 {a.raw} 跨时点演变 {a.date or \'\'} ↔ {b.date or \'\'}",\n'
        '        )'
    )
    mod = _load_mutated("app/core/precedent.py", old, new, tmp_path)
    mod.set_evolve_value_change(True)
    a = Fact("客户B", "回款率", 0.4, "40%", "A", "A#s1", "20240115")
    b = Fact("客户B", "回款率", 0.4, "40%", "B", "B#s1", "20250601")
    kind, desc = mod._diff_kind(a, b)
    blob = f"{kind}：{desc}"
    # 变异后必含禁词 —— 本格钉的是「改回去会红」
    assert any(bad in blob for bad in _EVOLVE_FORBIDDEN_IN_SAME_VALUE)
    # 真码仍干净
    set_evolve_value_change(True)
    kind_r, desc_r = _diff_kind(a, b)
    for bad in _EVOLVE_FORBIDDEN_IN_SAME_VALUE:
        assert bad not in f"{kind_r}：{desc_r}"


def test_c79_e_deterministic_cross_process(tmp_path):
    """判据 e：同一夹具跨进程两遍逐字相同。"""
    script = tmp_path / "run_c79.py"
    script.write_text(
        "import json, sys\n"
        "sys.path.insert(0, %r)\n"
        "from app.core.fact_ledger import Fact\n"
        "from app.core.precedent import _diff_kind, set_evolve_value_change\n"
        "set_evolve_value_change(True)\n"
        "a = Fact('客户B','回款率',0.4,'40%%','A','A#s1','20240115')\n"
        "b = Fact('客户B','回款率',0.4,'40%%','B','B#s1','20250601')\n"
        "c = Fact('客户B','回款率',0.25,'25%%','C','C#s1','20250601')\n"
        "out = {\n"
        "  'same': _diff_kind(a, b),\n"
        "  'chg': _diff_kind(a, c),\n"
        "}\n"
        "print(json.dumps(out, ensure_ascii=False, sort_keys=True))\n"
        % str(_ROOT),
        encoding="utf-8",
    )
    py = _ROOT / ".venv" / "bin" / "python"
    cmd = [str(py) if py.is_file() else sys.executable, str(script)]
    out1 = subprocess.check_output(cmd, text=True)
    out2 = subprocess.check_output(cmd, text=True)
    assert out1 == out2
    data = json.loads(out1)
    assert data["same"][0] == "重复报道"
    assert data["chg"][0] == "数字"


def test_c79_forbidden_judgment_files_untouched():
    """判据 c 形：六判定文件关键符号仍在（不许 git diff 常驻格）。"""
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
