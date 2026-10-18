"""主张闸探针：误伤率 ≤5%，跨案捕获率 ≥40%。写成等号不算完成。"""

from scripts.probe_warrant_gate import measure


def test_probe_false_positive_and_capture_are_inequalities():
    stats = measure()
    false_rate = stats["n_false"] / stats["n_positive"]
    capture = stats["n_caught"] / stats["n_negative"]
    assert false_rate <= 0.05
    assert capture >= 0.40
