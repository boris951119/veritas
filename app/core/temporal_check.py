"""时序核对器（零 LLM）：信源有先后，结论必须有锚。

两类时序幻觉的机械侧：
- 时效闸（stale）：对撞台账显示同一 (实体, 指标) 有新旧两个时点的值，
  而某结论只引用了**旧时点**信源 → 黄牌「存在更新时点资料」——
  2025 年报说风险高、2026 进展说已化解，模型引旧的不能装作新的不存在；
- as-of 闸：结论所引信源全部带时点、结论却没有任何时点词 → 黄牌
  「未锚定时点」——把快照写成永恒真理是时序冲突的温床。

信源时点来源：manifest 的 published_at（首选），缺省回退正文首个
「20XX年」（case_loader 落入 meta.year）。全部字符串/数值运算。
"""

from __future__ import annotations

import re

from app.core.evidence import Dossier
from app.core.fact_ledger import Collision, find_collisions

_YEAR_IN_TEXT = re.compile(r"(19|20)\d{2}\s*年|\d{4}[-/.]\d{1,2}")
_DATE_TAIL = re.compile(r"(\d{4})(\d{2})(\d{2})$")

# C-69：VERITAS_SOURCE_TIME_UNIFIED（默认关＝改前逐字）。
_SOURCE_TIME_UNIFIED = False


def set_source_time_unified(on: bool) -> None:
    """pipeline／单测设置件① 开关；默认 False。"""
    global _SOURCE_TIME_UNIFIED
    _SOURCE_TIME_UNIFIED = bool(on)


def source_time_unified() -> bool:
    return bool(_SOURCE_TIME_UNIFIED)


def normalize_to_day(raw: str) -> str:
    """时点串 → YYYYMMDD；不足 8 位数字回空（不许推断日）。"""
    digits = re.sub(r"\D", "", str(raw or "").strip())
    return digits[:8] if len(digits) >= 8 else ""


def source_date(src) -> str:
    """信源时点统一读点（C-69／R-C69-1）。

    开关关：改前行为＝published_at（去非数字后 ≥4 取前 8，否则原样）＞ year ＞ ''。
    开关开：按 published_at → publish_time → year 取**第一个有值的键**，
    归一沿用改前口径（数字 ≥4 → digits[:8]，否则原样）；**不许因不足 8 位就跳键**
    （月粒度 published_at=2026-03 必须得 202603，不得回退 year）。
    日粒度比较／行内展示仍要求 8 位（normalize_to_day／time_class），不足即 unknown_time。
    """
    if not _SOURCE_TIME_UNIFIED:
        raw = str(src.meta.get("published_at") or "").strip()
        if raw:
            digits = re.sub(r"\D", "", raw)
            return digits[:8] if len(digits) >= 4 else raw
        year = str(src.meta.get("year") or "").strip()
        return year
    for key in ("published_at", "publish_time", "year"):
        raw = str(src.meta.get(key) or "").strip()
        if not raw:
            continue
        digits = re.sub(r"\D", "", raw)
        return digits[:8] if len(digits) >= 4 else raw
    return ""


def _newer_older(pair: Collision) -> tuple[list, list]:
    """对撞事实按信源时点分成新/旧两组（无时点的事实不参与）。"""
    with_date = [(f, f.date) for f in pair.facts if f.date]
    if len(with_date) < 2:
        return [], []
    with_date.sort(key=lambda x: x[1])
    newest_date = with_date[-1][1]
    older = [(f, d) for f, d in with_date if d < newest_date]
    newer = [(f, d) for f, d in with_date if d == newest_date]
    return older, newer


def audit_temporal(dossier: Dossier) -> list[dict]:
    flags: list[dict] = []
    collisions = find_collisions(dossier)
    for pair in collisions:
        older, newer = _newer_older(pair)
        if not older or not newer:
            continue
        newer_desc = "；".join(f"{f.source_id}({d}) 说 {f.raw}" for f, d in newer)
        for con in dossier.conclusions:
            if con.status == "merged":
                continue
            if pair.metric not in con.statement \
                    or (pair.entity and pair.entity not in con.statement):
                continue  # 结论未谈这条指标
            cited = {_seg_source(dossier, sid)
                     for ev in dossier.evidences_of(con.id)
                     for sid in ev.segment_ids} - {""}
            if cited and cited <= {f.source_id for f, _ in older}:
                flags.append({
                    "kind": "stale", "severity": "medium",
                    "conclusion_id": con.id,
                    "value": f"{pair.entity}·{pair.metric}",
                    "detail": f"结论只引用了旧时点资料，但存在更新时点的数值："
                              f"{newer_desc}——应引用最新时点或明示两个时点的变化",
                })
    # as-of 闸：所引信源全部带时点、结论无时点词
    for con in dossier.conclusions:
        if con.status == "merged":
            continue
        evs = dossier.evidences_of(con.id)
        if not evs:
            continue
        dates = []
        for ev in evs:
            for sid in ev.segment_ids:
                src = _source_of_seg(dossier, sid)
                if src is not None:
                    d = source_date(src)
                    if d:
                        dates.append(d)
        if not dates or len(dates) != len([
                sid for ev in evs for sid in ev.segment_ids]):
            continue  # 有信源无时点：不强求锚定
        if _YEAR_IN_TEXT.search(con.statement):
            continue
        flags.append({
            "kind": "as_of", "severity": "medium",
            "conclusion_id": con.id,
            "value": con.statement[:30],
            "detail": f"所引信源均带时点（{min(dates)}~{max(dates)}），"
                      "但结论未锚定时点——应写「截至X时点」",
        })
    return flags


def _source_of_seg(dossier: Dossier, seg_id: str):
    return dossier.source_of_segment(seg_id)


def _seg_source(dossier: Dossier, seg_id: str) -> str:
    src = dossier.source_of_segment(seg_id)
    return src.id if src else ""
