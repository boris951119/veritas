"""四份官方提交 JSON＋字段说明。

fact_des／argument／entities 本版本留空，不编造。
conflict 记录只读 Resolution.to_dict() 已有键；basis、重启条件读不到就留空。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.confidence import (
    BAND_RULE,
    band_of,
    band_rel_of,
    band_rel_rule_of,
    row_score_detail,
)
from app.core.conflicts import METHOD_TO_RESOLUTION_TYPE
from app.core.evidence import (
    Dossier,
    conclusion_face_pooled,
    format_conclusion_face_line,
)

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
另有两套呈现档（不许合并、不许互替）：
- band：绝对档。高阈值 0.8＝官方达标行原文「高置信（≥0.8）」；中阈值 0.5＝我方设定（官方未写中/低分界）。
  一律从本行 score（parts 重算）来，不从 dossier_confidence 来（二者实测可差 1e-4）。
- band_rel：同跑次分位档。切点＝statistics.quantiles(scores, n=100, method=inclusive) 的第 34／67 个；
  样本面＝整份 confidence.json pooled（跨题合并）；样本 <2 整档记「低」。方法名与当次切点写在 band_rel_rule。
  退化规则（我方设定）：score≤0 ⇒ 恒记「低」（0 分不参与分位）；切点重合（hi−lo < 1e-9）时并列在切点上的记「不可分」。
  「不可分」＝我方设定，出现在本次分布退化（切点重合）时，表示这一档说不出高低，不是缺数据、也不是低。
当前公式下四因子均 ≤1 且 coverage 是渐近量，故提交物高档（≥0.8）常为空是结构性的，不是单次没跑好；
因此 ≥85% 那条达标线在高档为空时无样本可判，已向发榜方提问。
首屏「本案卷 N 条」是单案卷面；提交物分位面是 pooled 全跑次——两面不要混读。
本文件（confidence.json）仅含消解后 majority 态；逐态真数见下方「本次导出」里当场数出来的样本面披露。
配色（工作台）＝绝对档同一对阈值；提交行多数落在绝对档低／中时卡片偏红/黄是实测结果，不是渲染坏了。

## conflict_resolution.json
schema 自定。resolution_type 取官方五级之一，由 method 经模块级映射表得到
（映射表在 conflicts.py）。
basis、重启条件：由 Resolution.to_dict() 输出；缺失时留空并在 omissions 里披露。
omissions 取值含：人工改判、假不等式已拦截，以及导出层对缺失字段的标注。
导出层不另算证据强度，也不另数独立信源。

## 窗口装箱
本次按假定窗口装箱；若现场模型窗口更大请调 VERITAS_MODEL_CTX_TOKENS；
关闭＝VERITAS_PACK_TO_WINDOW=0。
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
        score, terms = row_score_detail(parts)
        strength = terms["strength"]
        coverage = terms["coverage"]
        agreement = terms["agreement"]
        chain_num = terms["chain"]
        agreement_factor = terms["agreement_factor"]
        chain_factor = terms["chain_factor"]
        rows.append({
            "question_id": question_id,
            "conclusion_id": con.id,
            "信源可信度": strength,
            "证据数量与一致性": {
                "coverage": coverage,
                "agreement": agreement,
                "agreement_factor": agreement_factor,
            },
            "推理链完整性": chain_num,
            "formula": "min(1, strength * coverage * agreement_factor * chain_factor)",
            "terms": dict(terms),
            "substitution": (
                f"min(1, {strength} * {coverage} * {agreement_factor}"
                f" * {chain_factor}) = {score}"
            ),
            "score": score,
            "dossier_confidence": con.confidence,
            "band": band_of(score),
            "band_rule": BAND_RULE,
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
        for note in list(res.get("omissions") or []):
            text = str(note or "").strip()
            if text and text not in omissions:
                omissions.append(text)
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
    # 早退只在 pipeline 写这一句 confidence_note；此处只读，不改早退条件。
    n_slot = sum(
        1 for _, dossier in runs
        if (dossier.accounting or {}).get("confidence_note")
        == "议题槽位未齐，未发起模型研判")
    slot_line = f"本次 {n_slot} 题因槽位未齐未调用分析师。"
    dedup_line = f"evidence.json 去重 {deduped} 行（键 doc_id, para_id, quote）。"
    face = conclusion_face_pooled([d for _, d in runs])
    face_line = format_conclusion_face_line(face, surface="本次提交物 pooled")
    print(gate_line)
    print(slot_line)
    print(dedup_line)
    print(face_line)

    # C-20：band_rel 必须看整份提交物 pooled，不能在 _confidence_rows（单案卷）里算
    pooled = [float(r["score"]) for r in confidence]
    rel_rule = band_rel_rule_of(pooled)
    for row in confidence:
        row["band_rel"] = band_rel_of(pooled, float(row["score"]))
        row["band_rel_rule"] = rel_rule

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
            "omissions": (
                (sorted(set(omission_notes)) or ["basis", "重启条件"])
                + [slot_line]
            ),
            "detail": "basis 与重启条件在 Resolution.to_dict() 中不存在，已留空；"
                      "resolution_type 仅由 method 映射表得到，未另算证据强度",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8")
    paths["notes"].write_text(
        _FIELD_NOTES + "\n## 本次导出\n" + gate_line + "\n"
        + slot_line + "\n" + dedup_line + "\n" + face_line + "\n",
        encoding="utf-8")
    return paths
