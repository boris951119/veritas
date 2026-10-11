"""选料金标：该留的信源必须留下，不相关正式文件不能占满名额。"""

from eval.recall_gold import run_recall


def test_recall_gold_keeps_labeled_sources():
    rows = run_recall()
    failed = [r for r in rows if not r["ok"]]
    assert not failed, failed
    assert all(r["recall"] == 1.0 for r in rows)
    crowd = next(r for r in rows if r["id"] == "unrelated-officials")
    assert "ANS" in crowd["selected"]
    assert crowd["crowd_n"] < crowd["max_sources"]
