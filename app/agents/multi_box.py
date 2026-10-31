"""树16／C-66：续盒研判——第 2‥N 箱各做一次定向分析（仅见该箱段）。

首箱仍走主编队（三分析师同料）。续盒沿用 second_pass 形态＝一名分析师
＋ focus_segment_ids，避免整面板 ×N 的墙钟爆炸；材料到达面与件① 探针同形。

关：VERITAS_MULTI_BOX=0。
"""

from __future__ import annotations

from typing import Callable

from app.agents.base import Analyst
from app.core.evidence import Conclusion, Dossier
from app.core.material import pack_continuation_boxes

_BOX_PERSONA = (
    "续盒分析师：上一箱预算已满，下列段落是下一箱新装入的材料。"
    "请【仅依据】这些段落补充回答议题中尚未覆盖的要点，"
    "给出可判定结论并挂逐字引文。"
    "不得引用清单外的段落编号；不要重复首箱已充分论证、且本箱无新证据的结论。"
)


def run_multi_box_passes(
    dossier: Dossier,
    analysts: list[Analyst],
    *,
    max_boxes: int = 3,
    budget_chars: int | None = None,
    on_done: Callable[[str, list[Conclusion]], None] | None = None,
) -> dict:
    """对第 2‥N 箱各跑一次定向分析；失败软降级。

    返回 accounting 形状（含 boxes／passes／n_conclusions）。
    """
    plan = pack_continuation_boxes(
        dossier, budget_chars=budget_chars, max_boxes=max_boxes)
    boxes = plan.get("boxes") or []
    out: dict = {
        "kind": "multi_box",
        "n_boxes": plan.get("n_boxes"),
        "max_boxes": plan.get("max_boxes"),
        "budget": plan.get("budget"),
        "n_union": len(plan.get("union_selected") or []),
        "per_box": [
            {
                "index": b["index"],
                "n_selected": b["n_selected"],
                "used_chars": b["used_chars"],
            }
            for b in boxes
        ],
        "passes": [],
        "n_conclusions": 0,
        "status": "ok",
    }
    if len(boxes) <= 1 or not analysts:
        out["status"] = "skipped"
        out["reason"] = (
            "single_box" if len(boxes) <= 1 else "no_analyst"
        )
        return out

    analyst = next(
        (a for a in analysts if a.name == "mainstream"), analysts[0])
    saved = analyst.persona
    total = 0
    try:
        for b in boxes[1:]:
            focus_ids = list(b["selected"])
            if not focus_ids:
                continue
            analyst.persona = _BOX_PERSONA
            cons: list[Conclusion] = []
            err = ""
            try:
                cons = analyst.analyze(dossier, focus_segment_ids=focus_ids)
                if on_done:
                    on_done(f"{analyst.name}+multi_box{b['index']}", cons)
            except Exception as exc:  # 续盒失败不阻断主链
                err = f"{type(exc).__name__}: {exc}"
            total += len(cons)
            out["passes"].append({
                "box_index": b["index"],
                "focus_ids": focus_ids,
                "n_focus": len(focus_ids),
                "n_conclusions": len(cons),
                "analyst": analyst.name,
                "error": err,
                "status": (
                    "ok" if cons and not err
                    else ("failed" if err else "empty")
                ),
            })
    finally:
        analyst.persona = saved

    out["n_conclusions"] = total
    if not out["passes"]:
        out["status"] = "skipped"
        out["reason"] = "no_extra_box_material"
    elif any(p.get("status") == "failed" for p in out["passes"]):
        out["status"] = "partial"
    return out
