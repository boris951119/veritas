"""C-115：冲突三类覆盖＋处置留痕（Q5）。

实验旗 ``VERITAS_CONFLICT_TRACE`` 默认关＝旧行为。
开：事实对撞／结论冲突对强制落在树10 既有三档之一
（``same_window``／``cross_day``／``unknown_time``）；无法归类 →
``unclassified`` 披露，不静默丢。每条写清单条目＋处置
（保留／落败转少数／未决）＋理由码／短理由 → accounting，供回放。

禁：第四类当主路径；「无日期＝非冲突」回退；金标泄漏；pack 系数。
"""

from __future__ import annotations

import os
from typing import Any

from app.core.kg_submit_surface import FORBIDDEN_PACK_KEYS, audit_forbidden_keys

_ENV = "VERITAS_CONFLICT_TRACE"
ACCOUNTING_KEY = "conflict_trace"

# 树10／C-69 既有硬枚举（勿另发明第四类当主路径）
CONFLICT_CLASSES = frozenset({
    "same_window", "cross_day", "unknown_time",
})
CONFLICT_CLASS_CN = {
    "same_window": "同窗对撞",
    "cross_day": "跨日时序",
    "unknown_time": "时点不明",
    "unclassified": "未归类",
}

# 处置结果硬枚举
DISPOSITIONS = frozenset({"keep", "dissent", "undecided"})
DISPOSITION_CN = {
    "keep": "保留",
    "dissent": "落败转少数",
    "undecided": "未决",
}

# 留痕必填键（齐全率量尺）
TRACE_REQUIRED_KEYS = frozenset({
    "id", "source", "conflict_class", "conflict_class_cn",
    "entry", "disposition", "disposition_cn",
    "reason_code", "reason_short",
})


def conflict_trace_enabled(settings: Any | None = None) -> bool:
    """默认随出厂（C-145a 起 True）。``VERITAS_CONFLICT_TRACE=0`` 关。

    settings 为 None 时走 ``Settings.from_env()``（出厂默认＋env 叠加），
    不许在无参路径里绕开出厂默认——否则翻默认后仲裁／导出挂点静默不走。
    """
    if settings is None:
        from app.config import Settings
        settings = Settings.from_env()
    if hasattr(settings, "conflict_trace"):
        return bool(getattr(settings, "conflict_trace"))
    v = (os.environ.get(_ENV) or "").strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    return False


def normalize_conflict_class(raw: Any) -> str:
    """强制三档；其它 → unclassified（披露，不丢条目）。"""
    key = str(raw or "").strip()
    if key in CONFLICT_CLASSES:
        return key
    return "unclassified"


def _reason_for_ledger(conflict_class: str) -> tuple[str, str]:
    if conflict_class == "same_window":
        return "pick_side", "同窗对撞：待采信一方或声明资料不足"
    if conflict_class == "cross_day":
        return "timeline_keep", "跨日时序：两侧保留为演变，不判谁错"
    if conflict_class == "unknown_time":
        return "time_unknown", "时点不明：未据此排序，不强制采信"
    return "unclassified", "无法归入同窗／跨日／时点不明三档"


def _disposition_for_ledger(conflict_class: str) -> str:
    # 跨日＝程序侧两侧保留；同窗／时点不明／未归类＝未决（禁「无日期＝非冲突」）
    if conflict_class == "cross_day":
        return "keep"
    return "undecided"


def trace_ledger_collision(collision: Any, *, index: int) -> dict[str, Any]:
    """事实对撞台账一条 → 留痕记录。"""
    raw_tc = getattr(collision, "time_class", None)
    if callable(raw_tc):
        raw_tc = collision.time_class
    conflict_class = normalize_conflict_class(raw_tc)
    disposition = _disposition_for_ledger(conflict_class)
    reason_code, reason_short = _reason_for_ledger(conflict_class)
    facts = list(getattr(collision, "facts", None) or [])
    entry = {
        "entity": str(getattr(collision, "entity", "") or ""),
        "metric": str(getattr(collision, "metric", "") or ""),
        "n_facts": len(facts),
        "source_ids": sorted({
            str(getattr(f, "source_id", "") or "") for f in facts
        }),
        "seg_ids": [
            str(getattr(f, "seg_id", "") or "") for f in facts
        ],
        "cross_source": bool(getattr(collision, "cross_source", False)),
    }
    return {
        "id": f"LEDGER-{index:04d}",
        "source": "fact_ledger",
        "conflict_class": conflict_class,
        "conflict_class_cn": CONFLICT_CLASS_CN.get(
            conflict_class, CONFLICT_CLASS_CN["unclassified"]),
        "entry": entry,
        "disposition": disposition,
        "disposition_cn": DISPOSITION_CN[disposition],
        "reason_code": reason_code,
        "reason_short": reason_short,
    }


def _pair_as_dict(pair: Any) -> dict:
    if isinstance(pair, dict):
        return pair
    if hasattr(pair, "to_dict"):
        return pair.to_dict()
    return {
        "id": str(getattr(pair, "id", "") or ""),
        "a_id": str(getattr(pair, "a_id", "") or ""),
        "b_id": str(getattr(pair, "b_id", "") or ""),
        "topic": str(getattr(pair, "topic", "") or ""),
        "description": str(getattr(pair, "description", "") or ""),
        "resolution": (
            pair.resolution.to_dict()
            if getattr(pair, "resolution", None) is not None
            and hasattr(pair.resolution, "to_dict")
            else getattr(pair, "resolution", None)
        ),
    }


def disposition_of_pair(pair: Any) -> tuple[str, str, str]:
    """结论冲突对 → (disposition, reason_code, reason_short)。

    有胜负：整对记 dissent（败方转少数；胜方保留体现在 entry.winner）。
    平局／无裁决：undecided。
    """
    raw = _pair_as_dict(pair)
    res = raw.get("resolution") if isinstance(raw.get("resolution"), dict) else None
    if not res:
        return "undecided", "no_resolution", "尚未裁决或仲裁失败"
    winner = str(res.get("winner_id") or "")
    a_id, b_id = str(raw.get("a_id") or ""), str(raw.get("b_id") or "")
    method = str(res.get("method") or res.get("decision_path") or "")
    if winner in (a_id, b_id) and a_id and b_id:
        return (
            "dissent",
            f"resolved:{method or 'arbitration'}",
            f"胜方 {winner}；败方转少数意见保留",
        )
    if winner == "tie" or method == "tie":
        return "undecided", "tie", "证据加权后无法裁决，双方保留 majority"
    return "undecided", "unresolved", "裁决未形成合法胜负"


def trace_conflict_pair(
    pair: Any,
    *,
    index: int,
    collisions: list[Any] | None = None,
    dossier: Any | None = None,
) -> dict[str, Any]:
    """结论级冲突对 → 留痕；class 能挂对撞则挂，否则 unclassified。"""
    raw = _pair_as_dict(pair)
    conflict_class = "unclassified"
    if dossier is not None and collisions:
        conflict_class = _classify_pair_via_dossier(raw, dossier, collisions)
    disposition, reason_code, reason_short = disposition_of_pair(raw)
    res = raw.get("resolution") if isinstance(raw.get("resolution"), dict) else {}
    entry = {
        "pair_id": str(raw.get("id") or f"PAIR-{index:04d}"),
        "a_id": str(raw.get("a_id") or ""),
        "b_id": str(raw.get("b_id") or ""),
        "topic": str(raw.get("topic") or ""),
        "winner_id": str((res or {}).get("winner_id") or ""),
        "method": str((res or {}).get("method") or ""),
        "decision_path": str((res or {}).get("decision_path") or ""),
    }
    return {
        "id": str(raw.get("id") or f"PAIR-{index:04d}"),
        "source": "conflict_pair",
        "conflict_class": conflict_class,
        "conflict_class_cn": CONFLICT_CLASS_CN.get(
            conflict_class, CONFLICT_CLASS_CN["unclassified"]),
        "entry": entry,
        "disposition": disposition,
        "disposition_cn": DISPOSITION_CN.get(
            disposition, DISPOSITION_CN["undecided"]),
        "reason_code": reason_code,
        "reason_short": reason_short,
    }


def _classify_pair_via_dossier(
    raw: dict, dossier: Any, collisions: list[Any],
) -> str:
    seg_class: dict[str, str] = {}
    for c in collisions:
        tc = normalize_conflict_class(
            c.time_class if not callable(getattr(c, "time_class", None))
            else c.time_class
        )
        for f in getattr(c, "facts", None) or []:
            sid = str(getattr(f, "seg_id", "") or "")
            if sid and tc in CONFLICT_CLASSES:
                seg_class[sid] = tc
    hit: set[str] = set()
    for cid in (raw.get("a_id"), raw.get("b_id")):
        con = dossier.conclusion(str(cid or "")) if hasattr(dossier, "conclusion") else None
        if con is None:
            continue
        ev_ids = list(getattr(con, "evidence_ids", None) or [])
        for eid in ev_ids:
            ev = None
            if hasattr(dossier, "evidence"):
                ev = dossier.evidence(eid)
            if ev is None:
                for e in getattr(dossier, "evidences", None) or []:
                    if str(getattr(e, "id", "")) == str(eid):
                        ev = e
                        break
            if ev is None:
                continue
            for sid in getattr(ev, "segment_ids", None) or []:
                tc = seg_class.get(str(sid))
                if tc:
                    hit.add(tc)
    if len(hit) == 1:
        return next(iter(hit))
    # 0 或多档冲突 → 不发明第四类
    return "unclassified"


def trace_fields_complete(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    if not TRACE_REQUIRED_KEYS <= set(row.keys()):
        return False
    if row.get("conflict_class") not in CONFLICT_CLASSES | {"unclassified"}:
        return False
    if row.get("disposition") not in DISPOSITIONS:
        return False
    if not str(row.get("reason_code") or "").strip():
        return False
    if not str(row.get("reason_short") or "").strip():
        return False
    if not isinstance(row.get("entry"), dict):
        return False
    return True


def summarize_trace(records: list[dict]) -> dict[str, Any]:
    n = len(records)
    by_class = {k: 0 for k in list(CONFLICT_CLASSES) + ["unclassified"]}
    by_disp = {k: 0 for k in DISPOSITIONS}
    complete = 0
    for r in records:
        cc = str(r.get("conflict_class") or "unclassified")
        by_class[cc] = by_class.get(cc, 0) + 1
        dd = str(r.get("disposition") or "")
        if dd in by_disp:
            by_disp[dd] += 1
        if trace_fields_complete(r):
            complete += 1
    classified = n - by_class.get("unclassified", 0)
    return {
        "n": n,
        "classified": classified,
        "unclassified": by_class.get("unclassified", 0),
        "coverage_rate": (classified / n) if n else 0.0,
        "trace_complete": complete,
        "trace_complete_rate": (complete / n) if n else 0.0,
        "by_class": by_class,
        "by_disposition": by_disp,
    }


def build_conflict_trace(
    dossier: Any,
    *,
    collisions: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """汇编事实对撞＋结论冲突对留痕（不去重丢弃；unclassified 保留）。"""
    records: list[dict[str, Any]] = []
    cols = list(collisions) if collisions is not None else []
    if collisions is None:
        try:
            from app.core.fact_ledger import find_collisions
            cols = list(find_collisions(dossier))
        except Exception:  # noqa: BLE001 — 留痕失败不吞冲突本体
            cols = []
    for i, c in enumerate(cols, 1):
        records.append(trace_ledger_collision(c, index=i))
    pairs = list(getattr(dossier, "conflicts", None) or [])
    for i, p in enumerate(pairs, 1):
        records.append(
            trace_conflict_pair(
                p, index=i, collisions=cols, dossier=dossier,
            )
        )
    return records


def apply_conflict_trace(
    dossier: Any,
    *,
    collisions: list[Any] | None = None,
    enabled: bool | None = None,
    settings: Any | None = None,
) -> dict[str, Any] | None:
    """旗开写入 accounting[conflict_trace]；旗关＝None、不写键。"""
    if enabled is None:
        enabled = conflict_trace_enabled(settings)
    if not enabled:
        return None
    records = build_conflict_trace(dossier, collisions=collisions)
    summary = summarize_trace(records)
    payload = {
        "enabled": True,
        "records": records,
        "summary": summary,
        "classes": sorted(CONFLICT_CLASSES),
        "dispositions": sorted(DISPOSITIONS),
    }
    # C-145：归并硬约束闸否决事件随面走（独立节，不冒充第四类冲突）
    from app.core.merge_gate import fold_into_trace_payload
    fold_into_trace_payload(
        payload, getattr(dossier, "accounting", None))
    bad = audit_forbidden_keys(payload)
    if bad:
        raise ValueError(f"conflict_trace hits forbidden: {bad}")
    for k in FORBIDDEN_PACK_KEYS:
        if k in payload:
            raise ValueError(f"forbidden pack key in conflict_trace: {k}")
    acc = getattr(dossier, "accounting", None)
    if acc is None:
        dossier.accounting = {}
        acc = dossier.accounting
    acc[ACCOUNTING_KEY] = payload
    return payload
