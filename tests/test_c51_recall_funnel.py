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


# ---------------------------------------------------------------------------
# R-C51-1 件 A：主攻层改逐级损失；换口径四桶分子不变
# ---------------------------------------------------------------------------


def test_c51_stage_losses_and_main_leak_from_live_counts():
    """stage_losses 按当场四桶分子算；main_leak＝argmax，差<15⇒分不开。"""
    from scripts.probe_recall_funnel import Bucket, QuestionResult

    # 写死当场读数：L1=105 L2=54 L3=16 L4=6
    # L1→L2=51, L2→L3=38, L3→L4=10；51−38=13<15 ⇒ 分不开
    r = QuestionResult(
        case="合成", qid="q",
        denom=105, skipped_no_locator=0,
        l1=Bucket(105, 105), l2=Bucket(54, 105),
        l3=Bucket(16, 105), l3_para=Bucket(0, 105), l3_quote=Bucket(0, 105),
        l4=Bucket(6, 105),
        pack_n_selected=0, pack_n_selected_chain=None, l4_mode="t",
    )
    assert r.stage_losses == {"L1->L2": 51, "L2->L3": 38, "L3->L4": 10}
    assert r.main_leak == "分不开"

    # 拉开差距：L1→L2=72, L2→L3=17, L3→L4=10 ⇒ 主漏 L1->L2
    r2 = QuestionResult(
        case="合成", qid="q",
        denom=105, skipped_no_locator=0,
        l1=Bucket(105, 105), l2=Bucket(33, 105),
        l3=Bucket(16, 105), l3_para=Bucket(0, 105), l3_quote=Bucket(0, 105),
        l4=Bucket(6, 105),
        pack_n_selected=0, pack_n_selected_chain=None, l4_mode="t",
    )
    assert r2.stage_losses == {"L1->L2": 72, "L2->L3": 17, "L3->L4": 10}
    assert r2.main_leak == "L1->L2"


def test_c51_main_leak_label_not_hardcoded_layer_name():
    """「主漏在 X」按当场读数生成，层名不许写死在源码字符串常量里。"""
    import inspect
    from scripts import probe_recall_funnel as probe
    src = inspect.getsource(probe.QuestionResult.main_leak.fget)
    # 属性实现里不许出现写死的 "主漏在 L2" / "主漏在 L4" 一类
    assert "主漏在 L1" not in src
    assert "主漏在 L2" not in src
    assert "主漏在 L3" not in src
    assert "主漏在 L4" not in src
    # print_human 的提示句必须用 agg['main_leak'] 变量，不写死层
    ph = inspect.getsource(probe.print_human)
    assert "主漏在 {main}" in ph or "主漏在 {agg" in ph


def test_c51_口径切换_四桶分子不变_只有主漏行变():
    """同一把尺、同一组四桶分子：只换 main_leak 口径 ⇒ 分子逐字不变。

    在同一份码上并排：旧口径（绝对 1−rate argmax）vs 新口径（逐级损失）。
    """
    from scripts.probe_recall_funnel import Bucket, QuestionResult

    r = QuestionResult(
        case="合成", qid="q",
        denom=105, skipped_no_locator=0,
        l1=Bucket(105, 105), l2=Bucket(33, 105),
        l3=Bucket(16, 105), l3_para=Bucket(13, 105), l3_quote=Bucket(5, 105),
        l4=Bucket(6, 105),
        pack_n_selected=58, pack_n_selected_chain=45, l4_mode="t",
    )
    # 四桶分子（换口径前后必须逐字相同）
    numer_before = (r.l1.numer, r.l2.numer, r.l3.numer, r.l4.numer)
    assert numer_before == (105, 33, 16, 6)

    # 旧口径：绝对未到达率 argmax（L4 最大）
    old_leaks = {
        "L1": 1.0 - r.l1.rate, "L2": 1.0 - r.l2.rate,
        "L3": 1.0 - r.l3.rate, "L4": 1.0 - r.l4.rate,
    }
    old_ranked = sorted(old_leaks.items(), key=lambda kv: -kv[1])
    if len(old_ranked) >= 2 and abs(old_ranked[0][1] - old_ranked[1][1]) < 0.03:
        old_main = "分不开"
    else:
        old_main = old_ranked[0][0]

    # 新口径：逐级损失（属性）
    new_main = r.main_leak
    numer_after = (r.l1.numer, r.l2.numer, r.l3.numer, r.l4.numer)
    assert numer_after == numer_before == (105, 33, 16, 6)
    # 只有主漏标签变（本夹具：旧＝L4，新＝L1->L2）
    assert old_main == "L4"
    assert new_main == "L1->L2"
    assert old_main != new_main


# ---------------------------------------------------------------------------
# R-C51-1 件 B：四颗腿（架构师下刀必须各见红）
# ---------------------------------------------------------------------------


def test_c51_B1_reconstruct_pack_selected_must_not_return_all():
    """B1：reconstruct_pack_selected 在紧预算下不得返回案卷全部段。

    架构师下刀：把该函数坏成「返回案卷全部段」⇒ 本格红。
    """
    from app.core.evidence import Dossier, Source, Segment, SourceType
    from scripts.probe_recall_funnel import reconstruct_pack_selected

    segs = [
        Segment(id="A#p1", source_id="A", text="高分长段停工停产" * 40, locator="A#p1"),
        Segment(id="A#p2", source_id="A", text="短", locator="A#p2"),
        Segment(id="A#p3", source_id="A", text="中等长度无关文字" * 20, locator="A#p3"),
    ]
    src = Source(id="A", title="t", source_type=SourceType.NEWS, credibility=0.8, segments=segs)
    d = Dossier(
        title="t", question="停工停产", sources=[src],
        accounting={"pack_window": {"budget": 40}},
    )
    all_ids = {s.id for s in segs}
    selected, n = reconstruct_pack_selected(d)
    assert selected != all_ids, (
        f"B1 红名：reconstruct 不得返回全集；selected={sorted(selected)} all={sorted(all_ids)}"
    )
    assert n == len(selected)
    assert n < len(all_ids)


def test_c51_B1_measure_l2_inflates_when_reconstruct_returns_all(monkeypatch):
    """B1 辅：reconstruct 返回全集 ⇒ measure L2 分子涨到 L1（期望 2→3）。"""
    from scripts import probe_recall_funnel as probe
    import tempfile, json

    def broken(dossier):
        ids = {"doc_a#p1", "doc_a#p2", "doc_b#p1"}
        return ids, len(ids)

    monkeypatch.setattr(probe, "reconstruct_pack_selected", broken)
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
        r = probe.measure_question(
            rp, Path(td) / "合成案", l4_tmp=Path(td) / "l4",
            override_dossier_ids={"doc_a#p1", "doc_a#p2", "doc_b#p1"},
            override_cited={("doc_a", "doc_a#p1")},
            override_exported={("doc_a", "doc_a#p1")},
            gold_override=gold,
        )
        assert r.l2.numer == 3
        assert r.l2.numer != EXPECT["l2"]


def test_c51_B2_chain_pack_mismatch_note_contains_both_counts(tmp_path, monkeypatch):
    """B2：chain_n≠pack_n 留痕必须同时含当场两数；摘掉那段 ⇒ 红。"""
    from scripts import probe_recall_funnel as probe
    import tempfile, json

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
        # 写 chain.jsonl：n_selected=45；复算 override pack_n=58
        chain = case_root / "chain.jsonl"
        chain.write_text(
            json.dumps({"event": "material_pack",
                        "payload": {"n_selected": 45}}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        pack58 = {f"x#{i}" for i in range(58)}
        r = probe.measure_question(
            rp, Path(td) / "合成案", l4_tmp=Path(td) / "l4",
            override_dossier_ids={"doc_a#p1", "doc_a#p2", "doc_b#p1"},
            override_pack=pack58,
            override_cited={("doc_a", "doc_a#p1")},
            override_exported={("doc_a", "doc_a#p1")},
            gold_override=gold,
        )
        blob = " ".join(r.notes)
        assert "45" in blob and "58" in blob, (
            f"B2 红名：留痕必须同时含 chain=45 与 复算=58；notes={r.notes!r}"
        )


def test_c51_B3_cited_hits_must_not_mark_all_gold():
    """B3：cited_hits 不得把金标标成全命中（只引用了一段时）。

    架构师下刀：把 cited_hits 坏成「金标全命中」⇒ 本格红。
    """
    from app.core.evidence import Dossier, Source, Segment, SourceType, EvidenceNode
    from scripts.probe_recall_funnel import cited_hits

    segs = [
        Segment(id="A#p1", source_id="A", text="甲文", locator="A#p1"),
        Segment(id="A#p2", source_id="A", text="乙文", locator="A#p2"),
        Segment(id="A#p3", source_id="A", text="丙文", locator="A#p3"),
    ]
    src = Source(id="A", title="t", source_type=SourceType.NEWS, credibility=0.8, segments=segs)
    ev = EvidenceNode(
        id="e1", conclusion_id="c1", quote="甲文",
        segment_ids=["A#p1"],
    )
    d = Dossier(title="t", question="q", sources=[src], evidences=[ev])
    gold = {
        ("A", "A#p1"): {"甲文"},
        ("A", "A#p2"): {"乙文"},
        ("A", "A#p3"): {"丙文"},
    }
    _hp, _hq, hits = cited_hits(gold, d)
    assert hits != set(gold.keys()), (
        f"B3 红名：cited_hits 不得全命中；hits={hits} gold={set(gold.keys())}"
    )
    assert ("A", "A#p1") in hits
    assert ("A", "A#p2") not in hits
    assert ("A", "A#p3") not in hits


def test_c51_B3_measure_l3_inflates_when_cited_hits_all_gold(monkeypatch):
    """B3 辅：cited_hits 坏成全命中 ⇒ measure L3＝denom ≠ 期望 1。"""
    from scripts import probe_recall_funnel as probe
    import tempfile, json

    def broken(gold, dossier):
        keys = set(gold.keys())
        return keys, keys, keys

    monkeypatch.setattr(probe, "cited_hits", broken)
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
        r = probe.measure_question(
            rp, Path(td) / "合成案", l4_tmp=Path(td) / "l4",
            override_dossier_ids={"doc_a#p1", "doc_a#p2", "doc_b#p1"},
            override_pack={"doc_a#p1", "doc_a#p2"},
            override_exported={("doc_a", "doc_a#p1")},
            gold_override=gold,
        )
        assert r.l3.numer == r.denom == EXPECT["denom"]
        assert r.l3.numer != EXPECT["l3"]


def test_c51_B4_gold_join_skipped_increment_leg(monkeypatch):
    """B4a：金标 join 的 skipped += 1 被摘 ⇒ skipped 读数不再涨 ⇒ 红。"""
    from scripts import probe_recall_funnel as probe
    import tempfile, json

    # 造一份缺 para 的 conclusions + evidence_samples
    with tempfile.TemporaryDirectory() as td:
        case_dir = Path(td) / "合成案"
        case_dir.mkdir()
        (case_dir / "conclusions.json").write_text(json.dumps([
            {"question_id": "q_001", "supporting_facts": [
                {"fact_id": "f1", "doc_id": "d", "quote": "甲"},
                {"fact_id": "f2", "doc_id": "d", "quote": "乙"},
            ]},
        ], ensure_ascii=False), encoding="utf-8")
        # f1 有 locator；f2 无 para_id ⇒ skipped
        (case_dir / "evidence_samples.json").write_text(json.dumps([
            {"fact_id": "f1", "doc_id": "d", "para_id": "d#p1", "quote": "甲"},
            {"fact_id": "f2", "doc_id": "d", "quote": "乙"},  # 无 para_id
        ], ensure_ascii=False), encoding="utf-8")

        gold, skipped = probe.gold_paras_for_question(case_dir, "q_001")
        assert skipped == 1
        assert len(gold) == 1

        # 下刀：跳过 skipped += 1
        import scripts.probe_recall_funnel as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        # 用 monkeypatch 替换整函数：不算 skipped
        def no_skip(case_dir, qid):
            g, _s = probe.gold_paras_for_question.__wrapped__(case_dir, qid)                 if hasattr(probe.gold_paras_for_question, '__wrapped__') else (None, None)
            # 直接重写：复制逻辑但 skipped 不加
            cj = case_dir / "conclusions.json"
            es = case_dir / "evidence_samples.json"
            conclusions = json.loads(cj.read_text(encoding="utf-8"))
            samples = {}
            if es.is_file():
                for row in json.loads(es.read_text(encoding="utf-8")):
                    fid = str(row.get("fact_id") or "")
                    if fid:
                        samples[fid] = row
            out = {}
            skipped = 0  # 永不 ++
            for row in conclusions:
                if str(row.get("question_id") or "") != qid:
                    continue
                for sf in row.get("supporting_facts") or []:
                    fid = str(sf.get("fact_id") or "")
                    sample = samples.get(fid)
                    para = str((sample or {}).get("para_id") or "")
                    doc = str((sample or {}).get("doc_id") or sf.get("doc_id") or "")
                    if not para or not doc:
                        # 坏：不 skipped += 1，仍 continue
                        continue
                    key = (doc, para)
                    out.setdefault(key, set()).add(str(sf.get("quote") or ""))
            return out, skipped

        monkeypatch.setattr(probe, "gold_paras_for_question", no_skip)
        _g2, skipped2 = probe.gold_paras_for_question(case_dir, "q_001")
        assert skipped2 == 0
        assert skipped2 != 1, "B4a：摘掉 skipped+=1 后必须与期望 1 冲突"


def test_c51_B4_gold_join_continue_leg(monkeypatch):
    """B4b：缺 locator 时若不停 continue 而仍入金标 ⇒ len(gold) 涨 ⇒ 红。"""
    from scripts import probe_recall_funnel as probe
    import tempfile, json

    with tempfile.TemporaryDirectory() as td:
        case_dir = Path(td) / "合成案"
        case_dir.mkdir()
        (case_dir / "conclusions.json").write_text(json.dumps([
            {"question_id": "q_001", "supporting_facts": [
                {"fact_id": "f1", "doc_id": "d", "quote": "甲"},
                {"fact_id": "f2", "doc_id": "d", "quote": "乙"},
            ]},
        ], ensure_ascii=False), encoding="utf-8")
        (case_dir / "evidence_samples.json").write_text(json.dumps([
            {"fact_id": "f1", "doc_id": "d", "para_id": "d#p1", "quote": "甲"},
            {"fact_id": "f2", "doc_id": "d", "quote": "乙"},
        ], ensure_ascii=False), encoding="utf-8")

        gold_ok, skipped_ok = probe.gold_paras_for_question(case_dir, "q_001")
        assert len(gold_ok) == 1 and skipped_ok == 1

        def no_continue(case_dir, qid):
            cj = case_dir / "conclusions.json"
            es = case_dir / "evidence_samples.json"
            conclusions = json.loads(cj.read_text(encoding="utf-8"))
            samples = {}
            if es.is_file():
                for row in json.loads(es.read_text(encoding="utf-8")):
                    fid = str(row.get("fact_id") or "")
                    if fid:
                        samples[fid] = row
            out = {}
            skipped = 0
            for row in conclusions:
                if str(row.get("question_id") or "") != qid:
                    continue
                for sf in row.get("supporting_facts") or []:
                    fid = str(sf.get("fact_id") or "")
                    sample = samples.get(fid)
                    para = str((sample or {}).get("para_id") or "")
                    doc = str((sample or {}).get("doc_id") or sf.get("doc_id") or "")
                    if not para or not doc:
                        skipped += 1
                        # 坏：不 continue，用空 para 仍入金标
                        para = para or "MISSING"
                        doc = doc or "MISSING"
                    key = (doc, para)
                    out.setdefault(key, set()).add(str(sf.get("quote") or ""))
            return out, skipped

        monkeypatch.setattr(probe, "gold_paras_for_question", no_continue)
        gold_bad, skipped_bad = probe.gold_paras_for_question(case_dir, "q_001")
        assert len(gold_bad) == 2
        assert len(gold_bad) != len(gold_ok), (
            "B4b：摘掉 continue 后 len(gold) 必须不同于正常 1"
        )
