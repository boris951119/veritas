"""R21：默认不改一筛系数（角色分布与 R20 对齐，避免刘翔回归掉点）。

可核验抬分走 portable_role／authority_band／二筛注入，不叠线性维。
"""

from __future__ import annotations

from typing import Any

R21_COEFF_TARGET: dict[str, float] = {}


def apply_r21_coeff_nudge(
    coeff: dict[str, float],
    *,
    cap: float = 0.08,
) -> dict[str, float]:
    del cap
    return dict(coeff)


def nudge_report(before: dict[str, float], after: dict[str, float]) -> list[dict[str, Any]]:
    del before, after
    return []
