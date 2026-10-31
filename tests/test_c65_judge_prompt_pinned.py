"""C-65 件③＝#201：JUDGE_SYSTEM 逐字钉（不许 startswith／切片／逐条 in）。

脚本 scripts/probe_c60_submission_variants.py:347 仍是弱断言
（startswith 前缀子串）——C-60 已收口、本单不许改 scripts/；
真守护搬到本测试面。
"""

from __future__ import annotations

from scripts.measure_s4_gates import JUDGE_SYSTEM

# 完整期望字面量（与 scripts/measure_s4_gates.py:549 逐字相同；改原文必红）
_EXPECTED_JUDGE_SYSTEM = (
    "你在做结论级语义对齐。只判断「待评结论」是否表达了「金标结论」的核心主张。"
    "口径：一致＝主张与关键限定都相同；部分一致＝主张方向相同但限定或口径不同；"
    "不一致＝主张相反或答的不是同一件事；未答＝待评结论里没有可对齐的主张。"
    "必须只输出 JSON 对象，键为 agreement、matched、why。matched 是待评结论 id 数组，可为空。"
)

_EXPECTED_FOUR_STATES = [
    "一致＝主张与关键限定都相同",
    "部分一致＝主张方向相同但限定或口径不同",
    "不一致＝主张相反或答的不是同一件事",
    "未答＝待评结论里没有可对齐的主张",
]


def test_c65_judge_system_byte_equal():
    """JUDGE_SYSTEM 与测试内完整期望字面量逐字 ==。"""
    assert JUDGE_SYSTEM == _EXPECTED_JUDGE_SYSTEM


def test_c65_judge_system_four_states_ordered():
    """按「口径：」切开后，四态定义串列表 == 期望列表（顺序也钉）。"""
    assert "口径：" in JUDGE_SYSTEM
    after = JUDGE_SYSTEM.split("口径：", 1)[1]
    # 四态句止于「。」——「必须只输出」之前
    states_blob = after.split("。", 1)[0]
    states = states_blob.split("；")
    assert states == _EXPECTED_FOUR_STATES
