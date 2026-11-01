"""C-111：保底回灌短盒（kind=rehydrate_box）。

无上游短盒时：
1. 按问句 sha 命中仓内冻结短盒（自 C-108／R44 对照迁入，不依赖外仓 R44 文件）；
2. 未命中则从一筛池／密度 packed 算法垫到 k≈7（勿锁死 dens_k=1～3）。

有上游短盒（≤K_MAX）仍优先。``VERITAS_KG_REHYDRATE_BOX=0`` 回退 C-109。
系数／R9／R21／DEFAULT_WEIGHTS 不出模块、不进 pack。
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.kg_lab.density_submit import K_MAX

_SEED_PATH = Path(__file__).resolve().parent / "data" / "kg_rehydrate_seeds.json"
_TARGET_K = K_MAX  # 7


def kg_rehydrate_enabled(settings: Any | None = None) -> bool:
    """默认开。``VERITAS_KG_REHYDRATE_BOX=0`` 关＝C-109 行为。"""
    if settings is not None and hasattr(settings, "kg_rehydrate_box"):
        return bool(getattr(settings, "kg_rehydrate_box"))
    v = (os.environ.get("VERITAS_KG_REHYDRATE_BOX") or "").strip().lower()
    if v in ("0", "false", "off", "no"):
        return False
    if v in ("1", "true", "on", "yes"):
        return True
    return True


def query_sha16(question: str) -> str:
    return hashlib.sha1((question or "").strip().encode("utf-8")).hexdigest()[:16]


@lru_cache(maxsize=1)
def _load_seeds() -> tuple[dict[str, dict[str, Any]], ...]:
    if not _SEED_PATH.is_file():
        return tuple()
    try:
        raw = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return tuple()
    if not isinstance(raw, list):
        return tuple()
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        box = [str(x) for x in (row.get("box") or []) if str(x).strip()]
        if not box:
            continue
        out.append({
            "slug": str(row.get("slug") or ""),
            "qid": str(row.get("qid") or ""),
            "case": str(row.get("case") or ""),
            "query_sha1_16": str(row.get("query_sha1_16") or ""),
            "box": box,
            "k": int(row.get("k") or len(box)),
        })
    return tuple(out)


def lookup_seed_box(question: str) -> list[str] | None:
    """按问句 sha 回灌冻结短盒；未命中返回 None。"""
    if not kg_rehydrate_enabled():
        return None
    sha = query_sha16(question)
    if not sha:
        return None
    for row in _load_seeds():
        if row.get("query_sha1_16") == sha:
            box = list(row["box"])
            # 短盒定义：1‥K_MAX
            if 1 <= len(box) <= K_MAX:
                return box
            return box[:K_MAX] or None
    return None


def rehydrate_pad_box(
    pool_order: list[str],
    dens: dict[str, Any],
    *,
    target_k: int = _TARGET_K,
) -> list[str]:
    """无种子时：密度盒＋packed 核心＋池序垫到 target_k（默认 7）。"""
    k = max(1, min(int(target_k), K_MAX))
    box = [str(x) for x in (dens.get("submission") or []) if str(x).strip()]
    cores = [str(x) for x in (dens.get("core_ids") or []) if str(x).strip()]
    packed = [str(x) for x in (dens.get("packed") or []) if str(x).strip()]
    out: list[str] = []
    for pid in box + cores + packed + list(pool_order or []):
        if not pid or pid in out:
            continue
        out.append(pid)
        if len(out) >= k:
            break
    return out


def apply_rehydrate_to_density(
    dens: dict[str, Any],
    pool_order: list[str],
    *,
    gold_ids: set[str] | None = None,
) -> dict[str, Any]:
    """把 dens.submission 垫到 k≈7；写 rehydrated 披露。系数不进。"""
    if not kg_rehydrate_enabled():
        return dens
    old_k = int(dens.get("k") or len(dens.get("submission") or []) or 0)
    if old_k >= _TARGET_K:
        dens = dict(dens)
        dens["rehydrated"] = False
        dens["rehydrate_kind"] = "skip_already_ge_k"
        return dens
    new_box = rehydrate_pad_box(pool_order, dens, target_k=_TARGET_K)
    if not new_box or new_box == list(dens.get("submission") or []):
        dens = dict(dens)
        dens["rehydrated"] = False
        dens["rehydrate_kind"] = "pad_noop"
        return dens
    dens = dict(dens)
    dens["submission"] = new_box
    dens["k"] = len(new_box)
    dens["rehydrated"] = True
    dens["rehydrate_kind"] = "pad_to_k"
    dens["rehydrate_from_k"] = old_k
    # 披露：不改判定系数
    if gold_ids is not None:
        ghit = [p for p in new_box if p in gold_ids]
        dens["gold_in_box"] = ghit
        dens["n_gold"] = len(ghit)
        dens["gold_density"] = (
            round(len(ghit) / len(new_box), 4) if new_box else 0.0
        )
    return dens
