"""C-117：树15 满箱减压；默认关；禁系数；有界上限。"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.kg_submit_surface import FORBIDDEN_PACK_KEYS, audit_forbidden_keys
from app.core.material import pack_material
from app.core.tree15_depress import (
    ABS_CAP,
    BUMP_CHARS,
    HARD_MAX_BOXES,
    PATH_NAME,
    apply_tree15_depress,
    bumped_budget,
    depress_max_boxes,
    tree15_depress_enabled,
)


def _fat_dossier(n_seg: int = 40, seg_len: int = 800) -> Dossier:
    """人为造满箱：多段长文挤爆小预算。"""
    d = Dossier(question="测试满箱减压议题主体")
    src = Source.create("DOC", SourceType.REPORT, id="DOC")
    for i in range(n_seg):
        text = f"段落{i:02d}：" + ("甲乙丙丁戊己庚辛" * (seg_len // 8 + 1))
        text = text[:seg_len]
        src.segments.append(Segment(
            id=f"DOC#p{i+1}", source_id="DOC", text=text, index=i,
        ))
    d.add_source(src)
    return d


def test_c117_flag_default_off(monkeypatch):
    monkeypatch.delenv("VERITAS_TREE15_DEPRESS", raising=False)
    assert Settings().tree15_depress is False
    assert tree15_depress_enabled() is False
    monkeypatch.setenv("VERITAS_TREE15_DEPRESS", "1")
    assert Settings.from_env().tree15_depress is True
    assert tree15_depress_enabled() is True


def test_c117_flag_off_no_repack(monkeypatch):
    monkeypatch.setenv("VERITAS_TREE15_DEPRESS", "0")
    d = _fat_dossier()
    pack = pack_material(d, budget_chars=3_000)
    assert pack["excluded"]
    new, acc = apply_tree15_depress(d, pack, enabled=False)
    assert new is pack or set(new["selected"]) == set(pack["selected"])
    assert acc["triggered"] is False
    assert acc["budget_after"] == acc["budget_before"]


def test_c117_bump_when_excluded(monkeypatch):
    monkeypatch.setenv("VERITAS_TREE15_DEPRESS", "1")
    d = _fat_dossier()
    pack = pack_material(d, budget_chars=3_000)
    assert len(pack["excluded"]) > 0
    new, acc = apply_tree15_depress(d, pack, enabled=True)
    assert acc["path"] == PATH_NAME
    assert acc["triggered"] is True
    assert acc["budget_after"] == bumped_budget(3_000)
    assert acc["budget_after"] <= ABS_CAP
    assert len(new["selected"]) >= len(pack["selected"])
    assert audit_forbidden_keys(acc) == []
    for bad in FORBIDDEN_PACK_KEYS:
        assert bad not in acc


def test_c117_hard_caps():
    assert bumped_budget(80_000) == min(80_000 + BUMP_CHARS, int(80_000 * 1.5), ABS_CAP)
    assert bumped_budget(100_000) <= ABS_CAP
    assert depress_max_boxes(3) == 4
    assert depress_max_boxes(3) <= HARD_MAX_BOXES
    assert depress_max_boxes(10) == HARD_MAX_BOXES


def test_c117_no_trigger_when_fits(monkeypatch):
    monkeypatch.setenv("VERITAS_TREE15_DEPRESS", "1")
    d = _fat_dossier(n_seg=2, seg_len=100)
    pack = pack_material(d, budget_chars=50_000)
    assert not pack["excluded"]
    _, acc = apply_tree15_depress(d, pack, enabled=True)
    assert acc["triggered"] is False


def test_c117_rejects_coeff_kwargs(monkeypatch):
    monkeypatch.setenv("VERITAS_TREE15_DEPRESS", "1")
    d = _fat_dossier()
    pack = pack_material(d, budget_chars=3_000)
    with pytest.raises(ValueError, match="forbidden"):
        apply_tree15_depress(
            d, pack, enabled=True, pack_kwargs={"r9_coeff": [1.0]},
        )
