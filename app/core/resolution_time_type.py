"""C-155：tie／轻裁「双方均保留」时的时效性回填（只补官方类型标签，不改胜负）。

为什么长在这里：评分锚点 3.3.2 要「明确给出消解类型（多数投票／来源优先级／
时效性／语义可信度／其他）并说明该类型为何适用」。现主线同一批产物里
「其他」占 90/175＝51.43%，而这个桶整桶是 `decision_path=tie`（机械无胜负，
85 条）＋轻裁口语误读（5 条）。tie 里有一条**从未被写进类型**的可核事实：
两侧信源时点不同——两条说法各自成立于不同日期，正因如此才谁都没被排除。
这条正是官方的「时效性」，把它接上＝用现场数据补标签，不是把判定改松。

规则（写死，判不到就不动，留在「其他」）：
1. 只对「双方均保留」的记录生效（winner 为 tie／空，且 decision_path=tie）；
   有胜方的记录一律不碰——胜方是谁由原机械与仲裁决定，本模块无权改。
2. 双侧信源时点都要**可解**（走仓内唯一实现 `temporal_check.source_date`），
   且两侧集合不完全相同；任一解不出 ⇒ 不回填。
3. 回填＝`resolution_type` 落「时效性」＋`basis["sides_dates"]` 记两侧日键
   （各留前两个）＋`basis["type_applies"]` 追加一句短判据；`loser_excluded`
   不动（原「双方均未排除」本就读得通）。**winner／method／rationale／证据强度／
   仲裁公式一行不动**（冲突数值线 STOP 不变）。
   足迹刻意压小：导出侧单条有 ≤800 字硬闸，回填文案过长会把同一条的
   「冲突清单／rationale」挤掉＝为 3.3.2 的标签牺牲 3.3.1 的分面，不允许。
4. 有胜方但判据只支持「胜方时点更新」这类情形，本模块一律不接管（现主线无该
   机械破平档；要开得另出单，不许在这里顺手加）。

回退：`set_enabled(False)`（env `VERITAS_RESOLUTION_TYPE_TIME=0`／config.json
`resolution_type_time`）⇒ 一行都不改，与改前逐字同形。
"""

from __future__ import annotations

from typing import Any

RESOLUTION_TYPE_TIME = "时效性"

_ENABLED = True


def set_enabled(on: bool) -> None:
    """由管线从 Settings 置入（与 temporal_check.set_source_time_unified 同法）。"""
    global _ENABLED
    _ENABLED = bool(on)


def enabled() -> bool:
    return _ENABLED


def side_day_keys(dossier: Any, con_id: str) -> list[str]:
    """结论所引信源的时点集合（去重、排序）；解不出的信源跳过。"""
    from app.core.temporal_check import source_date

    by_id = {str(getattr(s, "id", "")): s for s in (dossier.sources or [])}
    keys: list[str] = []
    for ev in dossier.evidences_of(str(con_id)) or []:
        for seg_id in (getattr(ev, "segment_ids", None) or []):
            seg = dossier.segment(str(seg_id))
            src = by_id.get(str(getattr(seg, "source_id", "") or ""))
            if src is None:
                continue
            day = str(source_date(src) or "").strip()
            if day and day not in keys:
                keys.append(day)
    return sorted(keys)


def tie_time_signature(dossier: Any, a_id: str, b_id: str) -> tuple[list[str], list[str]] | None:
    """双方时点都可解且集合不同 ⇒ (a_keys, b_keys)；否则 None（不回填）。"""
    if not enabled():
        return None
    ka = side_day_keys(dossier, a_id)
    kb = side_day_keys(dossier, b_id)
    if ka and kb and set(ka) != set(kb):
        return ka, kb
    return None


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Resolution 对象与案卷里的 resolution dict 同一条规则（离线复放走 dict）。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _set(obj: Any, key: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[key] = value
    else:
        setattr(obj, key, value)


def apply_tie_time_rule(resolution: Any, pair: Any, dossier: Any) -> bool:
    """就地回填类型；返回是否改动。幂等：已回填过再调一次结果相同。"""
    if not enabled() or resolution is None or dossier is None:
        return False
    if str(_get(resolution, "decision_path", "") or "") != "tie":
        return False
    winner = str(_get(resolution, "winner_id", "") or "")
    a_id = str(_get(pair, "a_id", "") or "")
    b_id = str(_get(pair, "b_id", "") or "")
    if winner in (a_id, b_id):
        # 有胜方＝不是「双方均保留」，本条规则不接管（见模块 docstring 第 1／4 条）
        return False
    if winner not in ("", "tie"):
        return False
    sig = tie_time_signature(dossier, a_id, b_id)
    if sig is None:
        return False
    ka, kb = sig
    basis = _get(resolution, "basis")
    if not isinstance(basis, dict):
        basis = {}
        _set(resolution, "basis", basis)
    # 足迹压到最小：导出侧单条有 ≤800 字硬闸（`_c46_enforce_record_size`），
    # 回填文案太长会把同一条的「冲突清单／rationale」挤掉——那是 3.3.1 的分面，
    # 不能为了 3.3.2 的标签把 3.3.1 的字段裁没。所以：判据写成一句短尾＋
    # 两侧各留首个日键；loser_excluded 不动（原「双方均未排除」本就读得通）。
    brief = f"；判据＝两侧信源时点不同 {ka[0]}↔{kb[0]}"
    base_applies = str(basis.get("type_applies") or "")
    if "判据＝两侧信源时点不同" not in base_applies:
        basis["type_applies"] = (base_applies + brief) if base_applies else brief
    basis["sides_dates"] = {a_id: ka[:1], b_id: kb[:1]}
    _set(resolution, "resolution_type", RESOLUTION_TYPE_TIME)
    return True
