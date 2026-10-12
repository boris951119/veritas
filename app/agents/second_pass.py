"""刀十一：未用关键段 → 二次定向研判。

第一轮编队结束后，取 unused_topic_segments 密度最高的 2–3 段，
再发一次分析师调用（仅见这些段落）。产出走同一套引文闸与归并。
关掉：VERITAS_SECOND_PASS=0。
"""

from __future__ import annotations

from typing import Callable

from app.agents.base import Analyst
from app.core.coverage_gap import unused_topic_segments
from app.core.evidence import Conclusion, Dossier

_DEFAULT_MAX = 3
_FOCUS_PERSONA = (
    "定向补漏分析师：上一轮研判漏用了下列关键段落。"
    "请【仅依据】这些段落回答议题中与段落主题相关的风险点"
    "（延期/进度、回款/坏账、人员流失等），给出可判定结论并挂逐字引文。"
    "不得引用清单外的段落编号。"
)


def pick_focus_segments(dossier: Dossier, *, limit: int = _DEFAULT_MAX
                        ) -> list[dict]:
    """密度最高、尚未被引用的议题相关段（最多 limit 条）。"""
    return unused_topic_segments(dossier, limit=max(1, int(limit)))


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
