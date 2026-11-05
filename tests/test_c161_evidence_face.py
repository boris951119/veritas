"""C-161：2.2 证据面量尺探针的守护格（只护探针与计分接线，不护任何生产行为）。

本票＝只量不开刀：app/ 与 config.json 零 diff，故这里没有生产臂可测。
钉的是四件事：
  1 pooled 的匹配边界＝案内一对一，不许池成跨案全集（doc_id 跨案重名会虚高）；
  2 漏召分层 L1‥L4 的落点与 Σ层＝漏召总数 不变式；
  3 一对一消耗语义（重复提交同一 locator 不顶两条金标，多出来的记误召）；
  4 有肉门槛与「建议开实现票」的接线（门槛全过才说「是」）。
外加一条：判定与件齐否同行——尺跑通＝YES，部分案干跑＝PARTIAL。
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "probe_c161_evidence_face", ROOT / "scripts" / "probe_c161_evidence_face.py")
probe = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(probe)


# ---- 夹具构造 helper -------------------------------------------------------

def _ev(doc: str, para: str | None = None) -> dict:
    para = para or f"{doc}#p1"
    return {"doc_id": doc, "para_id": para, "quote": f"q-{doc}-{para}"}


def _gold_fact(doc: str, para: str, fact_id: str) -> dict:
    return {"fact_id": fact_id, "doc_id": doc, "para_id": para,
            "quote": f"g-{para}"}


def _ref(fact_id: str) -> dict:
    return {"fact_id": fact_id}


def _sub_ref(doc: str, para: str) -> dict:
    return {"doc_id": doc, "para_id": para}


def _write_case(run_root: Path, name: str, *, submitted: list[dict],
                cited: dict[str, list[dict]], boxed: dict[str, list[str]],
                internal: dict[str, list[str]] | None = None) -> None:
    """交卷面：案级 evidence.json／conclusions.json ＋ 逐题 report/progress。"""
    case = run_root / name
    (case / "questions").mkdir(parents=True, exist_ok=True)
    (case / "evidence.json").write_text(
        json.dumps(submitted, ensure_ascii=False), encoding="utf-8")
    concl = [{"question_id": qid, "supporting_facts": refs, "conflicting_facts": []}
             for qid, refs in cited.items()]
    (case / "conclusions.json").write_text(
        json.dumps(concl, ensure_ascii=False), encoding="utf-8")
    for qid in cited:
        qdir = case / "questions" / qid
        qdir.mkdir(parents=True, exist_ok=True)
        (qdir / "progress.json").write_text(
            json.dumps({"material_pack_union": boxed.get(qid, [])},
                       ensure_ascii=False), encoding="utf-8")
        evidences = [{"segment_ids": internal.get(qid, [])}] if internal else []
        (qdir / "report.json").write_text(
            json.dumps({"evidences": evidences}, ensure_ascii=False), encoding="utf-8")


def _write_gold(gold_root: Path, name: str, *, facts: dict[str, tuple[str, str]],
                q_sup: dict[str, list[str]]) -> None:
    """金标面：evidence_samples.json（fact_id→locator）＋ conclusions.json（按 fact_id 引用）。"""
    case = gold_root / name
    case.mkdir(parents=True, exist_ok=True)
    (case / "evidence_samples.json").write_text(
        json.dumps([_gold_fact(doc, para, fid)
                    for fid, (doc, para) in facts.items()],
                   ensure_ascii=False), encoding="utf-8")
    concl = [{"question_id": qid,
              "supporting_facts": [_ref(fid) for fid in fids],
              "conflicting_facts": []}
             for qid, fids in q_sup.items()]
    (case / "conclusions.json").write_text(
        json.dumps(concl, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    """两案夹具：A 案 locator 全对齐；B 案故意用同一个 locator 说别的事。

    A 案金标＝p1（被引且已导出）、p2（只在材料窗口）、p3（只在内部证据面）、
      p4（哪都没进）；A 案另外多交一条 p7（A 案金标没有）。
    B 案金标＝doc_001#p7（＝A 案多交的那条），但 B 案自己只交了 doc_001#p9。
    ⇒ 案内匹配总命中＝1（只有 A 案 p1）；若把 6 案池成一个全集，A 案那条 p7
      会去顶 B 案金标＝虚高 1 命。真跑数据里这个虚高是 52→59（见 artifacts json）。
    """
    run_root = tmp_path / "runs"
    gold_root = tmp_path / "gold"
    facts_a = {"f1": ("doc_001", "doc_001#p1"), "f2": ("doc_001", "doc_001#p2"),
               "f3": ("doc_001", "doc_001#p3"), "f4": ("doc_001", "doc_001#p4")}
    _write_case(run_root, "caseA",
                submitted=[_ev("doc_001", "doc_001#p1"), _ev("doc_001", "doc_001#p7")],
                cited={"q_001": [_sub_ref("doc_001", "doc_001#p1")]},
                boxed={"q_001": ["doc_001#p2"]},
                internal={"q_001": ["doc_001#p3"]})
    _write_gold(gold_root, "caseA", facts=facts_a,
                q_sup={"q_001": ["f1", "f2", "f3", "f4"]})
    _write_case(run_root, "caseB",
                submitted=[_ev("doc_001", "doc_001#p9")],
                cited={"q_001": [_sub_ref("doc_001", "doc_001#p9")]},
                boxed={"q_001": []})
    _write_gold(gold_root, "caseB",
                facts={"f7": ("doc_001", "doc_001#p7")}, q_sup={"q_001": ["f7"]})
    return run_root, gold_root


def _run(tmp_path: Path) -> dict:
    run_root, gold_root = _fixture(tmp_path)
    argv = ["--run-root", str(run_root), "--gold-root", str(gold_root),
            "--out-prefix", str(tmp_path / "out" / "C161_evidence_face")]
    assert probe.main(argv) == 0
    return json.loads((tmp_path / "out" / "C161_evidence_face.json")
                      .read_text(encoding="utf-8"))


# ---- 1 pooled 的匹配边界 ---------------------------------------------------

def test_pooled_matches_within_case_not_across_cases(tmp_path):
    data = _run(tmp_path)
    # 案内匹配：A 案 p1 命中 1 条；A 案多交的 p7 在 A 案金标里没有＝误召不是命中
    assert data["pooled"]["one_to_one_hits"] == 1
    # 池成全集时，A 案那条 p7 会去顶 B 案金标＝虚高一命；这臂只披露、不进判定
    naive = data["pooled"]["naive_union_disclosure_only"]
    assert naive["hits"] == 2
    assert naive["locator_keys_shared_across_cases"] >= 1


def test_pooled_counts_are_sums_of_cases(tmp_path):
    data = _run(tmp_path)
    assert data["pooled"]["submitted_evidence_rows"] == sum(
        c["counts"]["submitted_evidence_rows"] for c in data["cases"])
    assert data["pooled"]["gold_evidence_rows"] == sum(
        c["counts"]["gold_evidence_rows"] for c in data["cases"])


# ---- 2 分层落点与不变式 ----------------------------------------------------

def test_layering_puts_each_miss_in_exactly_one_layer(tmp_path):
    data = _run(tmp_path)
    case_a = next(c for c in data["cases"] if c["case"] == "caseA")
    counts = case_a["gap_layering"]["counts"]
    assert counts["L1_cited_not_exported"] == 0
    assert counts["L2_internal_not_exported"] == 1  # p3 只在内部证据面
    assert counts["L3_boxed_not_cited"] == 1        # p2 只在材料窗口
    assert counts["L4_never_in_products"] == 1      # p4 哪都没进
    assert case_a["gap_layering"]["fn_total"] == sum(counts.values())


def test_layering_l1_wins_when_conclusion_cites_it(tmp_path):
    """同一条既被结论引用又在窗口里 ⇒ 归 L1（导出层丢），不许双计。"""
    run_root = tmp_path / "runs"
    gold_root = tmp_path / "gold"
    _write_case(run_root, "caseC",
                submitted=[],
                cited={"q_001": [_sub_ref("doc_009", "doc_009#p1")]},
                boxed={"q_001": ["doc_009#p1"]})
    _write_gold(gold_root, "caseC",
                facts={"f1": ("doc_009", "doc_009#p1")}, q_sup={"q_001": ["f1"]})
    argv = ["--run-root", str(run_root), "--gold-root", str(gold_root),
            "--out-prefix", str(tmp_path / "out" / "x")]
    assert probe.main(argv) == 0
    data = json.loads((tmp_path / "out" / "x.json").read_text(encoding="utf-8"))
    c = data["cases"][0]
    assert c["gap_layering"]["counts"]["L1_cited_not_exported"] == 1
    assert c["gap_layering"]["counts"]["L3_boxed_not_cited"] == 0
    assert c["gap_layering"]["fn_total"] == 1


def test_layer_invariant_is_wired_and_bites(monkeypatch, tmp_path):
    """两腿：(a) 层数和≠漏召总数必须抛；(b) 真跑里逐案都调了它、且 total 非零。"""
    with pytest.raises(AssertionError):
        probe.check_layer_sum({k: 0 for k in probe.LAYER_KEYS}, 4)
    probe.check_layer_sum({k: 1 for k in probe.LAYER_KEYS}, 4)  # 齐时不抛

    calls: list[tuple[dict, int]] = []
    monkeypatch.setattr(probe, "check_layer_sum",
                        lambda layers, total: calls.append((dict(layers), total)))
    data = _run(tmp_path)
    assert len(calls) == len(data["cases"])  # 逐案都走到，不是只跑一案
    for layers, total in calls:
        assert total > 0  # 自证两侧都取到数（不许空比空）
        assert sum(layers.values()) == total
    assert sum(t for _, t in calls) == data["totals"]["fn"]


# ---- 3 一对一消耗语义 ------------------------------------------------------

def test_duplicate_submission_consumes_only_one_gold_row():
    submitted = [("doc_001", "doc_001#p1"), ("doc_001", "doc_001#p1")]
    gold = [("doc_001", "doc_001#p1")]
    hits, fp, fn = probe.one_to_one_residuals(submitted, gold)
    assert (hits, sum(fp.values()), sum(fn.values())) == (1, 1, 0)


def test_duplicate_gold_needs_duplicate_submission():
    gold = [("doc_001", "doc_001#p1"), ("doc_001", "doc_001#p1")]
    submitted = [("doc_001", "doc_001#p1")]
    hits, fp, fn = probe.one_to_one_residuals(submitted, gold)
    assert (hits, sum(fp.values()), sum(fn.values())) == (1, 0, 1)


def test_conservation_raises_on_impossible_input(monkeypatch):
    """反向腿：命中数被人为改动时，守恒校验必须抛，不许静默出账。"""
    monkeypatch.setattr(probe.so, "exact_hits", lambda s, g: 99)
    with pytest.raises(AssertionError):
        probe.one_to_one_residuals([("d", "d#p1")], [("d", "d#p1")])


# ---- 4 门槛与建议接线 ------------------------------------------------------

def test_meat_gate_fails_short(tmp_path):
    data = _run(tmp_path)
    meat = data["verdict"]["meat_threshold"]
    assert meat["gate_pooled_F1_ge"]["gate"] == 0.65
    assert meat["both_pass"] is False
    assert data["verdict"]["recommend_implementation"] == "否"
    # 尺跑通＝判定 YES，与建议「否」并存（量到了但不值得开刀）
    assert data["verdict"]["judgement"] == "YES"


def test_meat_gate_passes_when_both_cases_hit(tmp_path):
    run_root = tmp_path / "runs"
    gold_root = tmp_path / "gold"
    for name, doc in (("刘翔案", "doc_001"), ("别案", "doc_002")):
        _write_case(run_root, name,
                    submitted=[_ev(doc, f"{doc}#p1")],
                    cited={"q_001": [_sub_ref(doc, f"{doc}#p1")]},
                    boxed={"q_001": []})
        _write_gold(gold_root, name,
                    facts={"f1": (doc, f"{doc}#p1")}, q_sup={"q_001": ["f1"]})
    argv = ["--run-root", str(run_root), "--gold-root", str(gold_root),
            "--out-prefix", str(tmp_path / "out" / "y")]
    assert probe.main(argv) == 0
    data = json.loads((tmp_path / "out" / "y.json").read_text(encoding="utf-8"))
    assert data["pooled"]["F1_src"] == 1.0
    assert data["verdict"]["recommend_implementation"] == "是"


def test_partial_run_is_marked_partial(tmp_path):
    run_root, gold_root = _fixture(tmp_path)
    argv = ["--run-root", str(run_root), "--gold-root", str(gold_root),
            "--only-case", "caseA",
            "--out-prefix", str(tmp_path / "out" / "z")]
    assert probe.main(argv) == 0
    data = json.loads((tmp_path / "out" / "z.json").read_text(encoding="utf-8"))
    assert data["verdict"]["judgement"] == "PARTIAL"
    assert data["pooled"] is None


# ---- 5 上界披露臂：案内去重，不吃跨案重名 ---------------------------------

def test_upper_bound_dedupes_per_case(tmp_path):
    data = _run(tmp_path)
    ub = data["upper_bound_disclosure"]
    # 夹具案内无重复 locator：案内去重和＝全局去重＝原条数（自证两侧都取到数）
    assert ub["submitted_rows"] == 3
    assert ub["submitted_distinct_within_case_sum"] == 3
    assert ub["submitted_distinct_global"] == 3
    assert ub["gold_rows"] == 5
    assert ub["gold_duplicate_rows_within_case"] == 0
    # 去重臂不得吃掉案内已有命中
    assert ub["submitted_dedup_only"]["hits"] == data["pooled"]["one_to_one_hits"]


def test_upper_bound_dedup_is_case_local_not_global(tmp_path):
    """刀：若去重写成「全局去重」，B 案的 p7 会被 A 案的 p7 吃掉⇒条数对不上。"""
    run_root = tmp_path / "runs"
    gold_root = tmp_path / "gold"
    _write_case(run_root, "caseA",
                submitted=[_ev("doc_001", "doc_001#p7")],
                cited={"q_001": [_sub_ref("doc_001", "doc_001#p7")]},
                boxed={"q_001": []})
    _write_gold(gold_root, "caseA", facts={"f7": ("doc_001", "doc_001#p7")},
                q_sup={"q_001": ["f7"]})
    _write_case(run_root, "caseB",
                submitted=[_ev("doc_001", "doc_001#p7")],
                cited={"q_001": [_sub_ref("doc_001", "doc_001#p7")]},
                boxed={"q_001": []})
    _write_gold(gold_root, "caseB", facts={"f7": ("doc_001", "doc_001#p7")},
                q_sup={"q_001": ["f7"]})
    argv = ["--run-root", str(run_root), "--gold-root", str(gold_root),
            "--out-prefix", str(tmp_path / "out" / "w")]
    assert probe.main(argv) == 0
    data = json.loads((tmp_path / "out" / "w.json").read_text(encoding="utf-8"))
    ub = data["upper_bound_disclosure"]
    assert ub["submitted_rows"] == 2
    assert ub["submitted_distinct_within_case_sum"] == 2  # 案内各 1 条，去重仍是 2
    assert ub["submitted_distinct_global"] == 1           # 全局去重会并成 1＝只作碰撞披露
    assert data["pooled"]["one_to_one_hits"] == 2         # 案内匹配两案都命中
    assert ub["submitted_dedup_only"]["hits"] == 2


# ---- 6 产物面：判定在文首、数字是现抄的 -----------------------------------

def test_md_starts_with_verdict_and_face_sizes(tmp_path):
    _run(tmp_path)
    md = (tmp_path / "out" / "C161_evidence_face.md").read_text(encoding="utf-8")
    first = md.splitlines()[0]
    assert first.startswith("# C-161") and "判定：YES" in first
    assert "分层三张面自身规模" in md  # L1/L2 记 0 时的自证面
    assert "未含语义匹配" in md


def test_probe_does_not_import_app():
    """零 LLM 的硬证据＝探针的 import 面里没有 app/（只看真语句，不看注释）。"""
    tree = ast.parse((ROOT / "scripts" / "probe_c161_evidence_face.py").read_text(encoding="utf-8"))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods.append(node.module or "")
    assert not [m for m in mods if m == "app" or m.startswith("app.")], mods
