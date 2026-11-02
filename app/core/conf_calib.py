"""C-116：置信档校准闸（Q6）。

实验旗 ``VERITAS_CONF_CALIB`` 默认关＝旧行为（``band_of(score)`` 原样）。
开：交卷／台账落 predicted_band＋（可选）自标对错位；高档须过可解释门槛，
否则降为「中」并披露 demote 原因。不改精排分数、不改 conclude_confidence 合式。

门槛（后置、低耦合）：
- min_evidence：证据条数 ≥ 2
- anchor_incomplete：引文命中率 ＜ 1 或段定位缺失
- chain_incomplete：推理链分 ＜ 1
- panel_disagreement：编队一致度 ＜ 1
- conflict_undecided：结论落入未决／平局冲突对

禁：金标写进运行时提示；pack 多维系数；默认开。
"""

from __future__ import annotations

import os
from typing import Any

from app.core.confidence import band_of
from app.core.kg_submit_surface import FORBIDDEN_PACK_KEYS, audit_forbidden_keys

_ENV = "VERITAS_CONF_CALIB"
ACCOUNTING_KEY = "conf_calib"

MIN_EVIDENCE = 2
DEMOTE_TO = "中"

REASON_CODES = frozenset({
    "min_evidence",
    "anchor_incomplete",
    "chain_incomplete",
    "panel_disagreement",
    "conflict_undecided",
})


def conf_calib_enabled(settings: Any | None = None) -> bool:
    """默认关。``VERITAS_CONF_CALIB=1`` 开。"""
    if settings is not None and hasattr(settings, "conf_calib"):
        return bool(getattr(settings, "conf_calib"))
    v = (os.environ.get(_ENV) or "").strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    return False


def _uniq(xs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in xs:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def high_band_demote_reasons(
    dossier: Any,
    conclusion: Any,
    *,
    parts: dict | None = None,
) -> list[str]:
    """高档可解释门槛；返回 demote 理由码列表（空＝过闸）。"""
    reasons: list[str] = []
    cid = str(getattr(conclusion, "id", "") or "")
    p = dict(parts if parts is not None else (
        getattr(conclusion, "confidence_parts", None) or {}
    ))

    n_ev = p.get("n_evidence")
    if n_ev is None and dossier is not None and cid:
        try:
            n_ev = len(dossier.evidences_of(cid))
        except Exception:  # noqa: BLE001
            n_ev = 0
    if int(n_ev or 0) < MIN_EVIDENCE:
        reasons.append("min_evidence")

    # 锚定：引文命中率 + 段是否可定位
    hr = None
    gates = p.get("gates") if isinstance(p.get("gates"), dict) else {}
    g1 = gates.get("G1_citation") if isinstance(gates, dict) else None
    if isinstance(g1, dict) and g1.get("hit_rate") is not None:
        hr = float(g1["hit_rate"])
    elif dossier is not None and cid:
        try:
            from app.core.citation_check import citation_hit_rate
            hr = citation_hit_rate(dossier, cid)
        except Exception:  # noqa: BLE001
            hr = None
    if hr is not None and float(hr) < 1.0:
        reasons.append("anchor_incomplete")
    if dossier is not None and cid:
        try:
            for ev in dossier.evidences_of(cid):
                for sid in getattr(ev, "segment_ids", None) or []:
                    if dossier.segment(str(sid)) is None:
                        reasons.append("anchor_incomplete")
                        break
        except Exception:  # noqa: BLE001
            pass

    ch = p.get("chain")
    if ch is not None:
        try:
            if float(ch) < 1.0:
                reasons.append("chain_incomplete")
        except (TypeError, ValueError):
            reasons.append("chain_incomplete")

    ag = p.get("agreement")
    if ag is not None:
        try:
            if float(ag) < 1.0:
                reasons.append("panel_disagreement")
        except (TypeError, ValueError):
            reasons.append("panel_disagreement")

    if dossier is not None and cid:
        for raw in getattr(dossier, "conflicts", None) or []:
            if isinstance(raw, dict):
                a_id = str(raw.get("a_id") or "")
                b_id = str(raw.get("b_id") or "")
                res = raw.get("resolution") if isinstance(
                    raw.get("resolution"), dict) else None
            else:
                a_id = str(getattr(raw, "a_id", "") or "")
                b_id = str(getattr(raw, "b_id", "") or "")
                res_obj = getattr(raw, "resolution", None)
                res = res_obj.to_dict() if res_obj is not None and hasattr(
                    res_obj, "to_dict") else None
            if cid not in (a_id, b_id):
                continue
            if not res or str(res.get("winner_id") or "") in ("", "tie"):
                reasons.append("conflict_undecided")

    return _uniq(reasons)


def demote_reasons_from_parts(parts: dict | None) -> list[str]:
    """离线快照／无 dossier 时的同口径门槛（parts 子集）。"""
    p = dict(parts or {})

    class _Stub:
        id = ""
        confidence_parts = p

    return high_band_demote_reasons(None, _Stub(), parts=p)


def gated_band(
    score: float,
    *,
    dossier: Any | None = None,
    conclusion: Any | None = None,
    parts: dict | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """返回 {predicted_band, band, demoted, demote_reasons, score}。

    ``predicted_band``＝合式原档；``band``＝开旗后交卷档（可降）。
    分数原样返回，不改。
    """
    if enabled is None:
        enabled = conf_calib_enabled()
    predicted = band_of(float(score))
    out = {
        "score": float(score),
        "predicted_band": predicted,
        "band": predicted,
        "demoted": False,
        "demote_reasons": [],
    }
    if not enabled or predicted != "高":
        return out
    reasons = high_band_demote_reasons(
        dossier, conclusion, parts=parts,
    ) if conclusion is not None or parts is not None else demote_reasons_from_parts(parts)
    if reasons:
        out["band"] = DEMOTE_TO
        out["demoted"] = True
        out["demote_reasons"] = reasons
    return out


def label_hit(label: str | None, *, strict: bool = True) -> bool | None:
    """自标对错位：strict＝仅「对」命中；非 strict＝对／部分。空 label→None。"""
    if label is None or not str(label).strip():
        return None
    lab = str(label).strip()
    if strict:
        return lab == "对"
    return lab in ("对", "部分")


def build_calib_row(
    *,
    conclusion_id: str,
    score: float,
    gated: dict[str, Any],
    label: str | None = None,
    case: str = "",
) -> dict[str, Any]:
    """题目／结论级校准对照行（禁金标原文）。"""
    hit = label_hit(label, strict=True)
    return {
        "case": case,
        "conclusion_id": str(conclusion_id or ""),
        "score": float(gated.get("score", score)),
        "predicted_band": gated.get("predicted_band"),
        "band": gated.get("band"),
        "demoted": bool(gated.get("demoted")),
        "demote_reasons": list(gated.get("demote_reasons") or []),
        "label": (str(label).strip() if label else None),
        "label_hit": hit,
    }


def apply_conf_calib(
    dossier: Any,
    *,
    enabled: bool | None = None,
    settings: Any | None = None,
    labels_by_id: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """旗开：写 accounting[conf_calib]；对 majority 结论算 gated band。旗关＝None。"""
    if enabled is None:
        enabled = conf_calib_enabled(settings)
    if not enabled:
        return None
    rows: list[dict] = []
    n_high_raw = 0
    n_high_kept = 0
    n_demoted = 0
    for con in getattr(dossier, "conclusions", None) or []:
        if getattr(con, "status", "") != "majority":
            continue
        score = float(getattr(con, "confidence", 0.0) or 0.0)
        # 优先 parts 重算呈现分？交卷用 confidence；与 export row_score 可能略差
        gated = gated_band(
            score, dossier=dossier, conclusion=con, enabled=True,
        )
        if gated["predicted_band"] == "高":
            n_high_raw += 1
            if gated["demoted"]:
                n_demoted += 1
            else:
                n_high_kept += 1
        lab = None
        if labels_by_id:
            lab = labels_by_id.get(str(con.id))
        rows.append(build_calib_row(
            conclusion_id=str(con.id),
            score=score,
            gated=gated,
            label=lab,
        ))
        # 披露挂到 confidence_parts（不改 score）
        parts = dict(getattr(con, "confidence_parts", None) or {})
        parts["band_raw"] = gated["predicted_band"]
        parts["band_gated"] = gated["band"]
        if gated["demoted"]:
            parts["band_demote_reasons"] = list(gated["demote_reasons"])
        con.confidence_parts = parts

    payload = {
        "enabled": True,
        "rows": rows,
        "n_majority": len(rows),
        "n_high_raw": n_high_raw,
        "n_high_kept": n_high_kept,
        "n_demoted": n_demoted,
        "min_evidence": MIN_EVIDENCE,
        "demote_to": DEMOTE_TO,
    }
    bad = audit_forbidden_keys(payload)
    if bad:
        raise ValueError(f"conf_calib hits forbidden: {bad}")
    for k in FORBIDDEN_PACK_KEYS:
        if k in payload:
            raise ValueError(f"forbidden pack key in conf_calib: {k}")
    acc = getattr(dossier, "accounting", None)
    if acc is None:
        dossier.accounting = {}
        acc = dossier.accounting
    acc[ACCOUNTING_KEY] = payload
    return payload


def high_band_precision(
    rows: list[dict[str, Any]],
    *,
    band_key: str = "band",
    strict: bool = True,
) -> dict[str, Any]:
    """高档精确度：band==高 子集上 label 命中率。"""
    high = [r for r in rows if str(r.get(band_key) or "") == "高"]
    n = len(high)
    if n == 0:
        return {
            "n_high": 0, "n_hit": 0, "precision": None,
            "accuracy": None, "strict": strict,
        }
    hits = 0
    acc_sum = 0.0
    _acc = {"对": 1.0, "部分": 0.5, "错": 0.0}
    for r in high:
        lab = str(r.get("label") or "")
        if label_hit(lab, strict=strict):
            hits += 1
        if lab in _acc:
            acc_sum += _acc[lab]
    return {
        "n_high": n,
        "n_hit": hits,
        "precision": hits / n,
        "accuracy": acc_sum / n,
        "strict": strict,
    }
