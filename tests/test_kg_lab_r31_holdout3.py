"""R31：holdout 名单与门槛①逻辑（不调参、不连样例）。"""

from __future__ import annotations

from scripts.kg_lab.run_r31_holdout3 import (
    FITTED,
    GATE_DENS,
    HOLDOUT,
    LIUXIANG_AT7_MIN,
)


def test_holdout_excludes_fitted_three():
    slugs = {h["slug"] for h in HOLDOUT}
    assert slugs.isdisjoint(set(FITTED))
    assert len(HOLDOUT) == 3
    titles = " ".join(h["title"] for h in HOLDOUT)
    assert "王虹" in titles
    assert "柬泰" in titles
    assert "AI171" in titles or "印度航空" in titles
    for fitted in ("刘翔", "吉隆", "中美AI"):
        assert fitted not in titles


def test_gate_threshold_is_two_thirds():
    assert abs(GATE_DENS - 2 / 3) < 1e-9
    assert LIUXIANG_AT7_MIN == 11


def test_gate_logic_all_or_nothing():
    """门槛①＝三案各自案均≥2/3 且刘翔过线；差一案即不过。"""
    dens = [0.67, 0.67, 0.50]
    n_pass = sum(1 for d in dens if d + 1e-12 >= GATE_DENS)
    assert n_pass == 2
    holdout_all = n_pass == 3
    lx_ok = 12 >= LIUXIANG_AT7_MIN
    assert (holdout_all and lx_ok) is False
