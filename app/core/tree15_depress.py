"""C-117：树15 L2 满箱减压（实验旗默认关）。

主路径＝① 有界加窗：首箱 ``excluded`` 非空（满箱缺口披露）时，
只允许多开 **1 档**字预算后重装一次；超硬上限仍披露装不下。
可选同旗轻量：续盒 ``max_boxes`` 最多 +1（仍有硬顶）。

禁：无界开窗；R9／多维系数进 pack；并 C-113 点名；宣称红标已灭。
"""

from __future__ import annotations

import os
from typing import Any

from app.core.kg_submit_surface import FORBIDDEN_PACK_KEYS, audit_forbidden_keys
from app.core.material import pack_material

_ENV = "VERITAS_TREE15_DEPRESS"
ACCOUNTING_KEY = "tree15_depress"

# 主路径名（报告写死）
PATH_NAME = "bounded_budget_bump"

# 硬上限：一档字预算 + 可选 +1 续盒
BUMP_CHARS = 20_000
MAX_FACTOR = 1.5
ABS_CAP = 120_000
EXTRA_BOX = 1
HARD_MAX_BOXES = 4  # multi_box_max(3) + EXTRA_BOX


def tree15_depress_enabled(settings: Any | None = None) -> bool:
    """默认关。``VERITAS_TREE15_DEPRESS=1`` 开。"""
    if settings is not None and hasattr(settings, "tree15_depress"):
        return bool(getattr(settings, "tree15_depress"))
    v = (os.environ.get(_ENV) or "").strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    return False


def bumped_budget(budget: int) -> int:
    """一档加窗：+BUMP，且不超过 factor／绝对顶。"""
    b = max(1, int(budget))
    bumped = b + BUMP_CHARS
    capped = min(bumped, int(b * MAX_FACTOR), ABS_CAP)
    return max(b, capped)


def depress_max_boxes(base_max: int) -> int:
    """续盒硬顶：原 max + EXTRA_BOX，且 ≤ HARD_MAX_BOXES。"""
    return min(HARD_MAX_BOXES, max(1, int(base_max)) + EXTRA_BOX)


def apply_tree15_depress(
    dossier: Any,
    pack: dict[str, Any],
    *,
    enabled: bool | None = None,
    settings: Any | None = None,
    pack_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """满箱时有界加预算重装。返回 (pack, accounting_payload)。

    旗关／无 excluded → 原 pack，payload.triggered=False。
    """
    if enabled is None:
        enabled = tree15_depress_enabled(settings)
    budget_before = int(pack.get("budget") or 0)
    n_excl_before = len(pack.get("excluded") or [])
    base_boxes = 3
    if settings is not None:
        base_boxes = int(getattr(settings, "multi_box_max", 3) or 3)
    payload: dict[str, Any] = {
        "enabled": bool(enabled),
        "path": PATH_NAME,
        "triggered": False,
        "budget_before": budget_before,
        "budget_after": budget_before,
        "n_excluded_before": n_excl_before,
        "n_excluded_after": n_excl_before,
        "n_selected_before": len(pack.get("selected") or []),
        "n_selected_after": len(pack.get("selected") or []),
        "bump_chars": BUMP_CHARS,
        "abs_cap": ABS_CAP,
        "max_factor": MAX_FACTOR,
        "extra_box": EXTRA_BOX,
        "depress_max_boxes": base_boxes,
        "still_full": n_excl_before > 0,
    }
    if not enabled:
        _store(dossier, payload)
        return pack, payload
    if n_excl_before <= 0:
        payload["depress_max_boxes"] = base_boxes
        _store(dossier, payload)
        return pack, payload

    new_budget = bumped_budget(budget_before)
    payload["triggered"] = True
    payload["budget_after"] = new_budget
    payload["depress_max_boxes"] = depress_max_boxes(base_boxes)

    kw = dict(pack_kwargs or {})
    # 禁系数键
    bad = audit_forbidden_keys(kw)
    if bad:
        raise ValueError(f"tree15_depress pack_kwargs forbidden: {bad}")
    for k in FORBIDDEN_PACK_KEYS:
        if k in kw:
            raise ValueError(f"forbidden pack key: {k}")

    if new_budget > budget_before:
        new_pack = pack_material(dossier, budget_chars=new_budget, **kw)
        payload["n_excluded_after"] = len(new_pack.get("excluded") or [])
        payload["n_selected_after"] = len(new_pack.get("selected") or [])
        payload["still_full"] = payload["n_excluded_after"] > 0
        payload["gained_slots"] = (
            payload["n_selected_after"] - payload["n_selected_before"]
        )
        _store(dossier, payload)
        return new_pack, payload

    # 已顶格：不重装，只允许 +1 续盒
    payload["still_full"] = True
    payload["gained_slots"] = 0
    payload["note"] = "budget already at cap; only extra_box available"
    _store(dossier, payload)
    return pack, payload


def _store(dossier: Any, payload: dict[str, Any]) -> None:
    bad = audit_forbidden_keys(payload)
    if bad:
        raise ValueError(f"tree15_depress accounting forbidden: {bad}")
    for k in FORBIDDEN_PACK_KEYS:
        if k in payload:
            raise ValueError(f"forbidden pack key in accounting: {k}")
    acc = getattr(dossier, "accounting", None)
    if acc is None:
        dossier.accounting = {}
        acc = dossier.accounting
    acc[ACCOUNTING_KEY] = payload
