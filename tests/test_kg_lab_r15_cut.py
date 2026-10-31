"""R15：踢掉的不补回；大盒里分数更高的可以通过二筛进交卷前 7。"""

from __future__ import annotations

from app.kg_lab.r15_stage2 import cut_question


def _row(pid: str, rank: int, gold: bool, feat: dict):
    return {"qid": "q", "id": pid, "gold": gold, "rank": rank, "feat": feat}


def test_kicked_item_is_not_refilled_and_deeper_gold_can_enter():
    rows = [
        _row("head_bad", 1, False, {"kick": 1.0, "keep": 0.0}),
        _row("head_gold", 2, True, {"kick": 0.0, "keep": 0.0}),
        _row("deep_gold", 19, True, {"kick": 0.0, "keep": 1.0}),
    ]
    coeff = {"kick": -0.12, "keep": 0.08}
    chosen = cut_question(rows, coeff, ("kick", "keep"), k=7)
    assert [r["id"] for r in chosen] == ["deep_gold", "head_gold"]
