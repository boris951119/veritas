"""评测集可跑通：三个核心指标可出数，编造闸不得退化。"""

from pathlib import Path

from scripts.run_eval import _load_items, summarize
from app.ingest.case_loader import load_case

_ROOT = Path(__file__).resolve().parent.parent


def test_benchmark_has_enough_items():
    items = _load_items()
    assert len(items) >= 30
    kinds = {i["kind"] for i in items}
    assert kinds == {"retrieval", "conflict", "fabrication"}


def test_eval_metrics_smoke():
    cache: dict = {}

    def get_case(name: str):
        if name not in cache:
            cache[name] = load_case(_ROOT / "cases" / name)
        return cache[name]

    report = summarize(_load_items(), get_case)
    m = report["metrics"]
    # 编造检出是主轴可信抓手：期望拒绝的必须拒
    assert m["fabrication_detection_rate"] == 1.0
    assert m["fabrication_false_positive_rate"] == 0.0
    # 冲突召回（机械对立词典）在本标注集上应可复现
    assert m["conflict_recall"] is not None and m["conflict_recall"] >= 0.8
    # 检索允许同义盲区拉低召回，但不允许整体塌掉
    assert m["bm25_recall_at_k"] is not None and m["bm25_recall_at_k"] >= 0.7
