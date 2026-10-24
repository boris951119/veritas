# -*- coding: utf-8 -*-
"""C-51：召回漏桶探针——合成夹具四桶各埋已知漏＋CLI／反向腿。

期望整数写死在本文件，不许拿探针返回值自比。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# 独立写死的期望（夹具构造与此一一对应；改夹具必须同步改这里）
# 分母＝4 段：g1,g2,g3,g4
# L1：g1–g3 在案卷，g4 不在      → 3/4
# L2：仅 g1,g2 进装箱（g3 在案卷但未装箱）→ 2/4
# L3：仅 g1 被引用（para_id）              → 1/4
# L4：仅 g1 出现在提交面                    → 1/4
EXPECT = {
    "denom": 4,
    "l1": 3,
    "l2": 2,
    "l3": 1,
    "l4": 1,
}


def _fixture_gold() -> dict[tuple[str, str], set[str]]:
    return {
        ("doc_a", "doc_a#p1"): {"金标引文甲"},
        ("doc_a", "doc_a#p2"): {"金标引文乙"},
        ("doc_b", "doc_b#p1"): {"金标引文丙"},
        ("doc_c", "doc_c#p9"): {"金标引文丁-不在案卷"},
    }


def test_funnel_counts_match_independent_expect():
    """四桶读数必须等于本文件写死的期望整数（不许自比探针返回值）。"""
    from scripts.probe_recall_funnel import Bucket, measure_question
    from app.core.evidence import Dossier
    import tempfile

    gold = _fixture_gold()
    # 构造最小 dossier（sources/evidences 空即可——全部走 override）
    d = Dossier(title="t", question="q")
    # 伪造 report 路径结构：.../CASE/questions/qid/report.json
    with tempfile.TemporaryDirectory() as td:
        case_root = Path(td) / "合成案" / "questions" / "q_001"
        case_root.mkdir(parents=True)
        report = {
            "title": "t",
            "question": "q",
            "sources": [],
            "evidences": [],
            "conclusions": [],
            "accounting": {"pack_window": {"budget": 1000}},
        }
        rp = case_root / "report.json"
        rp.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

        dossier_ids = {"doc_a#p1", "doc_a#p2", "doc_b#p1"}  # 缺 g4
        pack = {"doc_a#p1", "doc_a#p2"}  # 缺 g3
        cited = {("doc_a", "doc_a#p1")}
        exported = {("doc_a", "doc_a#p1")}

        r = measure_question(
            rp,
            Path(td) / "合成案",
            l4_tmp=Path(td) / "l4",
            override_dossier_ids=dossier_ids,
            override_pack=pack,
            override_cited=cited,
            override_exported=exported,
            gold_override=gold,
        )
        assert r.denom == EXPECT["denom"]
        assert r.l1.numer == EXPECT["l1"]
        assert r.l2.numer == EXPECT["l2"]
        assert r.l3.numer == EXPECT["l3"]
        assert r.l4.numer == EXPECT["l4"]
        assert r.l1.denom == EXPECT["denom"]
        assert r.l2.denom == EXPECT["denom"]
        assert r.l3.denom == EXPECT["denom"]
        assert r.l4.denom == EXPECT["denom"]


def test_reverse_leg_zero_l2_numerator_must_change():
    """反向腿：把 L2 装箱集置空 ⇒ L2 分子必须变 0（相对期望 2）。"""
    from scripts.probe_recall_funnel import measure_question
    from app.core.evidence import Dossier
    import tempfile

    gold = _fixture_gold()
    with tempfile.TemporaryDirectory() as td:
        case_root = Path(td) / "合成案" / "questions" / "q_001"
        case_root.mkdir(parents=True)
        report = {
            "title": "t", "question": "q",
            "sources": [], "evidences": [], "conclusions": [],
            "accounting": {"pack_window": {"budget": 1000}},
        }
        rp = case_root / "report.json"
        rp.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

        r = measure_question(
            rp, Path(td) / "合成案", l4_tmp=Path(td) / "l4",
            override_dossier_ids={"doc_a#p1", "doc_a#p2", "doc_b#p1"},
            override_pack=set(),  # ← 置空
            override_cited={("doc_a", "doc_a#p1")},
            override_exported={("doc_a", "doc_a#p1")},
            gold_override=gold,
        )
        assert r.l2.numer == 0
        assert r.l2.numer != EXPECT["l2"], "置空后 L2 必须不同于期望 2"
        # 其余桶不受影响
        assert r.l1.numer == EXPECT["l1"]
        assert r.l3.numer == EXPECT["l3"]
        assert r.l4.numer == EXPECT["l4"]


def test_reverse_leg_drop_l3_calc_must_red():
    """自证：摘掉 L3 计算（cited 覆盖成全集却断言仍等于期望 1）⇒ 本格必红。

    这里直接断言「若有人把 L3 分子错写成 denom，必与 EXPECT 冲突」。
    """
    from scripts.probe_recall_funnel import measure_question
    import tempfile

    gold = _fixture_gold()
    with tempfile.TemporaryDirectory() as td:
        case_root = Path(td) / "合成案" / "questions" / "q_001"
        case_root.mkdir(parents=True)
        report = {
            "title": "t", "question": "q",
            "sources": [], "evidences": [], "conclusions": [],
            "accounting": {"pack_window": {"budget": 1000}},
        }
        rp = case_root / "report.json"
        rp.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

        # 模拟「摘掉 L3 过滤」＝ cited 放进全部分母键
        r = measure_question(
            rp, Path(td) / "合成案", l4_tmp=Path(td) / "l4",
            override_dossier_ids={"doc_a#p1", "doc_a#p2", "doc_b#p1"},
            override_pack={"doc_a#p1", "doc_a#p2"},
            override_cited=set(gold.keys()),  # 摘掉过滤
            override_exported={("doc_a", "doc_a#p1")},
            gold_override=gold,
        )
        # 这颗格子的牙：摘掉后分子＝denom ≠ EXPECT["l3"]
        assert r.l3.numer == r.denom
        assert r.l3.numer != EXPECT["l3"]


def test_cli_requires_run_dir():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/probe_recall_funnel.py")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert r.returncode != 0
    blob = r.stderr + r.stdout
    assert "--run-dir" in blob or "显式" in blob


def test_cli_help_exit_zero():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/probe_recall_funnel.py"), "--help"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert r.returncode == 0
    assert "--run-dir" in r.stdout


def test_bucket_helpers_independent():
    """Bucket 算术不依赖探针主路径（防空壳）。"""
    from scripts.probe_recall_funnel import Bucket
    b = Bucket(3, 4)
    assert b.as_pair() == "3/4"
    assert abs(b.rate - 0.75) < 1e-9
    empty = Bucket(0, 0)
    assert empty.rate == 0.0
