"""刀十一：未用关键段 → 二次定向研判。

第一轮编队结束后，取 unused_topic_segments 密度最高的 2–3 段，
再发一次分析师调用（仅见这些段落）。产出走同一套引文闸与归并。
关掉：VERITAS_SECOND_PASS=0。

C-57：官方新闻议题往往命不中企业风险主题词表（延期／回款／坏账…），
`unused_topic_segments` 会返回空 ⇒ 二次研判整题跳过。回退＝从本轮
装箱已选且尚未被引用的段里，按 BM25（对议题）取前 limit 条——
不读金标、不改 SEGMENT_MAX、不弱化引文闸。
"""

from __future__ import annotations

import os
from typing import Callable

from app.agents.base import Analyst
from app.core.bm25 import rank_segments
from app.core.coverage_gap import unused_topic_segments
from app.core.evidence import Conclusion, Dossier
from app.core.material import pack_material

_DEFAULT_MAX = 3
_FOCUS_PERSONA = (
    "定向补漏分析师：上一轮研判漏用了下列关键段落。"
    "请【仅依据】这些段落回答议题中与段落主题相关的要点，"
    "给出可判定结论并挂逐字引文。"
    "不得引用清单外的段落编号。"
)


def _cited_segment_ids(dossier: Dossier) -> set[str]:
    out: set[str] = set()
    for ev in dossier.evidences:
        out.update(str(sid) for sid in (ev.segment_ids or []))
    return out


def _fallback_focus_from_pack(dossier: Dossier, *, limit: int) -> list[dict]:
    """主题词表未命中时的回退：装箱已选 ∩ 未引用，BM25 降序取 limit。"""
    pack = set(str(x) for x in (pack_material(dossier).get("selected") or []))
    if not pack:
        return []
    cited = _cited_segment_ids(dossier)
    ranked = rank_segments(dossier)
    out: list[dict] = []
    for sid, score in ranked:
        sid = str(sid)
        if sid in cited or sid not in pack:
            continue
        if float(score or 0.0) <= 0.0:
            continue
        seg = dossier.segment(sid)
        if seg is None:
            continue
        snip = (seg.text or "").strip().replace("\n", " ")
        if len(snip) > 40:
            snip = snip[:39] + "…"
        out.append({
            "segment_id": sid,
            "source_id": seg.source_id,
            "themes": [],
            "density": float(score),
            "snip": snip,
            "focus_via": "bm25_pack_fallback",
        })
        if len(out) >= limit:
            break
    return out


def pick_focus_segments(dossier: Dossier, *, limit: int = _DEFAULT_MAX
                        ) -> list[dict]:
    """尚未被引用的补漏焦点段（最多 limit 条）。

    先走主题词密度（企业风险议题）；空则回退 BM25×装箱已选。
    """
    lim = max(1, int(limit))
    primary = unused_topic_segments(dossier, limit=lim)
    if primary:
        return primary
    # 配对真跑基线臂：VERITAS_SECOND_PASS_FALLBACK=0 关回退＝改前「主题词空⇒跳过」
    if os.environ.get("VERITAS_SECOND_PASS_FALLBACK", "1").strip() in {
            "0", "false", "False", "no", "OFF"}:
        return []
    return _fallback_focus_from_pack(dossier, limit=lim)


def run_second_pass(
    dossier: Dossier,
    analysts: list[Analyst],
    *,
    max_segments: int = _DEFAULT_MAX,
    on_done: Callable[[str, list[Conclusion]], None] | None = None,
) -> dict:
    """对焦点段落跑一次定向分析；失败软降级，不炸管线。

    选用编队中第一名仍可用的分析师（优先 mainstream），临时换向补漏角色。
    """
    focus = pick_focus_segments(dossier, limit=max_segments)
    focus_ids = [str(it["segment_id"]) for it in focus if it.get("segment_id")]
    if not focus_ids or not analysts:
        return {
            "kind": "second_pass",
            "status": "skipped",
            "reason": "no_focus" if not focus_ids else "no_analyst",
            "focus_ids": focus_ids,
            "n_conclusions": 0,
        }

    analyst = next((a for a in analysts if a.name == "mainstream"), analysts[0])
    saved_persona = analyst.persona
    analyst.persona = _FOCUS_PERSONA
    cons: list[Conclusion] = []
    err = ""
    try:
        cons = analyst.analyze(dossier, focus_segment_ids=focus_ids)
        if on_done:
            on_done(f"{analyst.name}+second_pass", cons)
    except Exception as exc:  # 二次失败不阻断主链
        err = f"{type(exc).__name__}: {exc}"
    finally:
        analyst.persona = saved_persona

    status = "ok" if cons and not err else ("failed" if err else "empty")
    return {
        "kind": "second_pass",
        "status": status,
        "analyst": analyst.name,
        "focus_ids": focus_ids,
        "focus": focus,
        "n_conclusions": len(cons),
        "error": err,
        "note": (
            f"二次定向研判：就未引用关键段 {', '.join(focus_ids)} "
            f"由 {analyst.name} 补答，新增 {len(cons)} 条结论"
            + (f"（失败：{err}）" if err else "")
        ),
    }
