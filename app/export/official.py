"""四份官方提交 JSON＋字段说明。

fact_des／argument／entities 本版本留空，不编造。
conflict 记录只读 Resolution.to_dict() 已有键；basis、重启条件读不到就留空。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.confidence import _AGREEMENT_FLOOR, chain_factor_of
from app.core.conflicts import METHOD_TO_RESOLUTION_TYPE
from app.core.evidence import Dossier

_ARGUMENT_KEYS = ("时间", "主体", "地点", "内容", "影响", "数值口径")
_EMPTY_ARGUMENT = {key: "" for key in _ARGUMENT_KEYS}

_FIELD_NOTES = """\
# 官方提交物字段说明

## evidence.json
键与附录 A.2 一致：doc_id、para_id、quote、fact_des、argument、entities。
argument 六槽为：时间、主体、地点、内容、影响、数值口径。
fact_des、argument 各槽、entities：本版本未实现，值为 null 或空串。不编造。

## conclusions.json
键与附录 A.3 一致：question_id、question、conclusion、supporting_facts、conflicting_facts。
supporting_facts / conflicting_facts 的元素只有 doc_id、para_id。
supporting_facts 来自本案已采纳证据的段落。
conflicting_facts：Resolution.to_dict() 里没有官方段落对，本版本留空数组，不编造。

## confidence.json
schema 自定（附录 A 未规定）。每条结论含：
信源可信度、证据数量与一致性、推理链完整性，
以及公式 `min(1, strength × coverage × agreement_factor × chain_factor)`、
各分项数值与代入演算。

## conflict_resolution.json
schema 自定。resolution_type 取官方五级之一，由 method 经模块级映射表得到
（C-14 会把该表移进 conflicts.py）。
basis、重启条件：Resolution.to_dict() 当前没有这两键，留空并在 omissions 里披露。
导出层不另算证据强度，也不另数独立信源。
"""


def _empty_argument() -> dict:
    return dict(_EMPTY_ARGUMENT)


def _segment_locator(dossier: Dossier, segment_id: str) -> tuple[str, str] | None:
    seg = dossier.segment(segment_id)
    if seg is None:
        return None
    src = dossier.source_of_segment(segment_id)
    doc_id = str((src.meta or {}).get("doc_id") or (src.id if src else ""))
    return doc_id, seg.id


def _evidence_rows(dossier: Dossier,
                   seen: set[tuple[str, str, str]]) -> tuple[list[dict], int]:
    """seen 由 export_official 持有，跨题共用。返回 (新行, 被去重掉的行数)。"""
    rows: list[dict] = []
    dropped = 0
    for ev in dossier.evidences:
        for sid in ev.segment_ids:
            loc = _segment_locator(dossier, sid)
            if loc is None:
                continue
            doc_id, para_id = loc
            key = (doc_id, para_id, ev.quote)
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            rows.append({
                "doc_id": doc_id,
                "para_id": para_id,
                "quote": ev.quote,
                "fact_des": None,
                "argument": _empty_argument(),
                "entities": None,
            })
    return rows, dropped


def _bare_gate_line(n_questions: int, dropped_ids: list[str],
                    kept_bare_ids: list[str] | None = None) -> str:
    ids = "、".join(dropped_ids) if dropped_ids else "（无）"
    if n_questions >= 3:
        return (
            f"裸结论闸：本次题数 {n_questions} ≥3，"
            f"未写入结论提交的 question_id：{ids}。"
        )
    kept = "、".join(kept_bare_ids) if kept_bare_ids else "（无）"
    return (
        f"裸结论闸：本次题数 {n_questions} ≤2，"
        f"裸结论照旧提交，保留的 question_id：{kept}。"
    )


def _supporting_facts(dossier: Dossier) -> list[dict]:
    facts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ev in dossier.evidences:
        for sid in ev.segment_ids:
            loc = _segment_locator(dossier, sid)
            if loc is None or loc in seen:
                continue
            seen.add(loc)
            facts.append({"doc_id": loc[0], "para_id": loc[1]})
    return facts


def _conclusion_text(dossier: Dossier) -> str:
    headline = str((dossier.synthesis or {}).get("headline") or "").strip()
    if headline:
        return headline
    for con in dossier.conclusions:
        if con.status == "majority" and con.statement.strip():
            return con.statement.strip()
    return ""


def _confidence_rows(question_id: str, dossier: Dossier) -> list[dict]:
    rows = []
    for con in dossier.conclusions:
        if con.status != "majority":
            continue
        parts = dict(con.confidence_parts or {})
        strength = float(parts.get("strength") or 0.0)
        coverage = float(parts.get("coverage") or 0.0)
        agreement = float(parts.get("agreement") or 0.0)
        chain = parts.get("chain")
        chain_num = None if chain is None else float(chain)
        agreement_factor = _AGREEMENT_FLOOR + (1 - _AGREEMENT_FLOOR) * agreement
        chain_factor = chain_factor_of(chain_num)
        product = min(1.0, strength * coverage * agreement_factor * chain_factor)
        score = round(product, 4)
        rows.append({
            "question_id": question_id,
            "conclusion_id": con.id,
            "信源可信度": strength,
            "证据数量与一致性": {
                "coverage": coverage,
                "agreement": agreement,
                "agreement_factor": round(agreement_factor, 4),
            },
            "推理链完整性": chain_num,
            "formula": "min(1, strength * coverage * agreement_factor * chain_factor)",
            "terms": {
                "strength": strength,
                "coverage": coverage,
                "agreement": agreement,
                "agreement_factor": round(agreement_factor, 4),
                "chain": chain_num,
                "chain_factor": round(chain_factor, 4),
            },
            "substitution": (
                f"min(1, {strength} * {coverage} * {round(agreement_factor, 4)}"
                f" * {round(chain_factor, 4)}) = {score}"
            ),
            "score": score,
            "dossier_confidence": con.confidence,
        })
    return rows


def _conflict_rows(question_id: str, dossier: Dossier) -> tuple[list[dict], list[str]]:
    rows = []
    omitted_any: list[str] = []
    for pair in dossier.conflicts or []:
        if not isinstance(pair, dict):
            continue
        res = pair.get("resolution") if isinstance(pair.get("resolution"), dict) else {}
        method = str(res.get("method") or "")
        basis = res.get("basis")
        rtype = res.get("resolution_type")
        restart = res.get("restart_condition")
        if restart is None:
            restart = res.get("重启条件")
        omissions = []
        if basis is None or basis == "" or basis == {}:
            omissions.append("basis")
            basis = ""
        if rtype in (None, ""):
            omissions.append("resolution_type")
            rtype = METHOD_TO_RESOLUTION_TYPE.get(method, "其他")
        if restart in (None, ""):
            omissions.append("重启条件")
            restart = ""
        omitted_any.extend(omissions)
        rows.append({
            "question_id": question_id,
            "conflict_id": str(pair.get("id") or ""),
            "resolution_type": rtype,
            "basis": basis if basis is not None else "",
            "重启条件": restart if restart is not None else "",
            "method": method,
            "rationale": str(res.get("rationale") or ""),
            "omissions": omissions,
        })
    return rows, sorted(set(omitted_any))


def export_official(runs: list[tuple[dict, Dossier]], out_dir: Path) -> dict[str, Path]:
    """按 question_id 汇总四份 JSON 与字段说明。runs 元素是 (问题, 案卷)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence: list[dict] = []
    conclusions: list[dict] = []
    confidence: list[dict] = []
    conflicts: list[dict] = []
    omission_notes: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    deduped = 0
    dropped_ids: list[str] = []
    kept_bare_ids: list[str] = []
    n_questions = len(runs)
    for question, dossier in runs:
        qid = str(question["question_id"])
        rows, dropped = _evidence_rows(dossier, seen)
        evidence.extend(rows)
        deduped += dropped
        supporting = _supporting_facts(dossier)
        # 题数 ≥3 才丢裸结论：2.3 是 15/N，N=2 时丢一题比 2.4.1 归零更亏。
        if n_questions >= 3 and not supporting:
            dropped_ids.append(qid)
        else:
            if not supporting:
                kept_bare_ids.append(qid)
            conclusions.append({
                "question_id": qid,
                "question": str(question["question"]),
                "conclusion": _conclusion_text(dossier),
                "supporting_facts": supporting,
                "conflicting_facts": [],
            })
        confidence.extend(_confidence_rows(qid, dossier))
        conflict_rows, omitted = _conflict_rows(qid, dossier)
        conflicts.extend(conflict_rows)
        omission_notes.extend(omitted)
    gate_line = _bare_gate_line(n_questions, dropped_ids, kept_bare_ids)
    dedup_line = f"evidence.json 去重 {deduped} 行（键 doc_id, para_id, quote）。"
    print(gate_line)
    print(dedup_line)

    paths = {
        "evidence": out_dir / "evidence.json",
        "conclusions": out_dir / "conclusions.json",
        "confidence": out_dir / "confidence.json",
        "conflict_resolution": out_dir / "conflict_resolution.json",
        "notes": out_dir / "字段说明.md",
    }
    paths["evidence"].write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["conclusions"].write_text(
        json.dumps(conclusions, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["confidence"].write_text(
        json.dumps(confidence, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["conflict_resolution"].write_text(
        json.dumps({
            "records": conflicts,
            "omissions": sorted(set(omission_notes)) or ["basis", "重启条件"],
            "detail": "basis 与重启条件在 Resolution.to_dict() 中不存在，已留空；"
                      "resolution_type 仅由 method 映射表得到，未另算证据强度",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8")
    paths["notes"].write_text(
        _FIELD_NOTES + "\n## 本次导出\n" + gate_line + "\n" + dedup_line + "\n",
        encoding="utf-8")
    return paths
