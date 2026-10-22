"""C-25：score_official --errors 三桶＋权重扰动探针（只动 scripts/＋tests/）。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.core.confidence import band_of, recompute_all
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    Segment,
    Source,
    SourceType,
)
from scripts.probe_weight_sensitivity import (
    MULTIPLIERS,
    band_flips,
    n_panel_of,
    probe,
    run_one,
)
from scripts.score_official import (
    CITATION_BUCKET,
    ERRORS_NOTE,
    error_buckets,
    format_report,
    score_submission,
)

ROOT = Path(__file__).resolve().parents[1]


def _dump(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _gold_fact(fact_id: str) -> dict:
    return {
        "fact_id": fact_id,
        "doc_id": "doc_001",
        "quote": "金标引文",
        "fact_des": "des",
        "verdict_label": "full_support",
    }


def _fixture_two_questions():
    """≥2 题金标；samples 换形。"""
    samples = [
        {"fact_id": "f1", "doc_id": "doc_001", "para_id": "p1", "quote": "金标引文甲"},
        {"fact_id": "f2", "doc_id": "doc_001", "para_id": "p2", "quote": "金标引文乙"},
        {"fact_id": "f3", "doc_id": "doc_001", "para_id": "p3", "quote": "金标引文丙"},
    ]
    gold_c = [
        {
            "question_id": "q1",
            "question": "问一",
            "conclusion": "结一",
            "supporting_facts": [_gold_fact("f1")],
            "conflicting_facts": [],
        },
        {
            "question_id": "q2",
            "question": "问二",
            "conclusion": "结二",
            "supporting_facts": [_gold_fact("f2"), _gold_fact("f3")],
            "conflicting_facts": [],
        },
    ]
    return samples, gold_c


# ---------- a-in ----------
def test_a_in_blank_all_miss_no_false(tmp_path):
    samples, gold_c = _fixture_two_questions()
    blank_c = [
        {"question_id": "q1", "question": "问一", "conclusion": "",
         "supporting_facts": [], "conflicting_facts": []},
        {"question_id": "q2", "question": "问二", "conclusion": "",
         "supporting_facts": [], "conflicting_facts": []},
    ]
    err = error_buckets(
        blank_c, gold_c, [], samples, samples=samples)
    assert err["漏召"]["count"] == 2
    assert set(err["漏召"]["question_ids"]) == {"q1", "q2"}
    assert err["误召"]["count"] == 0
    assert err[CITATION_BUCKET]["count"] == 0
    assert err["overlap"] == 0
    assert err["两侧都空"]["count"] == 0  # 金标非空


def test_a_in_full_hit_zero_buckets(tmp_path):
    samples, gold_c = _fixture_two_questions()
    full_c = [
        {"question_id": "q1", "question": "问一", "conclusion": "结一",
         "supporting_facts": [{"doc_id": "doc_001", "para_id": "p1"}],
         "conflicting_facts": []},
        {"question_id": "q2", "question": "问二", "conclusion": "结二",
         "supporting_facts": [
             {"doc_id": "doc_001", "para_id": "p2"},
             {"doc_id": "doc_001", "para_id": "p3"},
         ],
         "conflicting_facts": []},
    ]
    evidence = [
        {"doc_id": "doc_001", "para_id": "p1", "quote": "金标引文甲"},
        {"doc_id": "doc_001", "para_id": "p2", "quote": "金标引文乙"},
        {"doc_id": "doc_001", "para_id": "p3", "quote": "金标引文丙"},
    ]
    err = error_buckets(
        full_c, gold_c, evidence, samples, samples=samples)
    assert err["漏召"]["count"] == 0
    assert err["误召"]["count"] == 0
    assert err[CITATION_BUCKET]["count"] == 0
    assert err["overlap"] == 0


def test_a_in_extra_outside_gold_is_false_positive(tmp_path):
    samples, gold_c = _fixture_two_questions()
    sub = [
        {"question_id": "q1", "question": "问一", "conclusion": "结一",
         "supporting_facts": [
             {"doc_id": "doc_001", "para_id": "p1"},
             {"doc_id": "doc_001", "para_id": "p9"},  # 金标外
         ],
         "conflicting_facts": []},
        {"question_id": "q2", "question": "问二", "conclusion": "结二",
         "supporting_facts": [
             {"doc_id": "doc_001", "para_id": "p2"},
             {"doc_id": "doc_001", "para_id": "p3"},
         ],
         "conflicting_facts": []},
    ]
    err = error_buckets(sub, gold_c, [], samples, samples=samples)
    assert err["误召"]["count"] == 1
    assert err["误召"]["question_ids"] == ["q1"]
    assert err["漏召"]["count"] == 0


def test_a_in_empty_both_sides_counted(tmp_path):
    samples = [
        {"fact_id": "f1", "doc_id": "doc_001", "para_id": "p1", "quote": "甲"},
    ]
    gold_c = [
        {"question_id": "q_empty", "question": "空题", "conclusion": "",
         "supporting_facts": [], "conflicting_facts": []},
        {"question_id": "q_full", "question": "有题", "conclusion": "结",
         "supporting_facts": [_gold_fact("f1")], "conflicting_facts": []},
    ]
    sub = [
        {"question_id": "q_empty", "question": "空题", "conclusion": "",
         "supporting_facts": [], "conflicting_facts": []},
        {"question_id": "q_full", "question": "有题", "conclusion": "",
         "supporting_facts": [], "conflicting_facts": []},
    ]
    err = error_buckets(sub, gold_c, [], samples, samples=samples)
    assert err["两侧都空"]["count"] == 1
    assert err["两侧都空"]["question_ids"] == ["q_empty"]
    assert "q_full" in err["漏召"]["question_ids"]


def test_a_in_format_report_says_buckets_not_additive(tmp_path):
    samples, gold_c = _fixture_two_questions()
    metrics = score_submission(
        _dump(tmp_path / "e.json", []),
        _dump(tmp_path / "c.json", [
            {"question_id": "q1", "supporting_facts": [], "conflicting_facts": []},
            {"question_id": "q2", "supporting_facts": [], "conflicting_facts": []},
        ]),
        _dump(tmp_path / "ge.json", samples),
        _dump(tmp_path / "gc.json", gold_c),
        samples_path=_dump(tmp_path / "s.json", samples),
    )
    metrics["errors"] = error_buckets(
        [{"question_id": "q1", "supporting_facts": [], "conflicting_facts": []},
         {"question_id": "q2", "supporting_facts": [], "conflicting_facts": []}],
        gold_c, [], samples, samples=samples,
    )
    text = format_report(metrics)
    assert ERRORS_NOTE in text
    assert "三桶不可相加" in text
    assert CITATION_BUCKET in text


# ---------- b ----------
def test_b_delete_supporting_enters_miss_not_empty_both(tmp_path):
    samples, gold_c = _fixture_two_questions()
    # q1 有金标支撑；提交删光 ⇒ 漏召，不是两侧都空
    sub = [
        {"question_id": "q1", "supporting_facts": [], "conflicting_facts": []},
        {"question_id": "q2", "supporting_facts": [
            {"doc_id": "doc_001", "para_id": "p2"},
            {"doc_id": "doc_001", "para_id": "p3"},
        ], "conflicting_facts": []},
    ]
    err = error_buckets(sub, gold_c, [], samples, samples=samples)
    assert "q1" in err["漏召"]["question_ids"]
    assert "q1" not in err["两侧都空"]["question_ids"]


# ---------- c ----------
def test_c_overlap_has_real_count(tmp_path):
    """金标外证据 + 引文与金标不一致 ⇒ 误召与第三桶重叠 ≥1。"""
    samples, gold_c = _fixture_two_questions()
    # q1：金标要 p1；提交 p1（quote 被改）＋金标外 p9
    sub = [
        {"question_id": "q1", "supporting_facts": [
            {"doc_id": "doc_001", "para_id": "p1"},
            {"doc_id": "doc_001", "para_id": "p9"},
        ], "conflicting_facts": []},
        {"question_id": "q2", "supporting_facts": [
            {"doc_id": "doc_001", "para_id": "p2"},
            {"doc_id": "doc_001", "para_id": "p3"},
        ], "conflicting_facts": []},
    ]
    evidence = [
        {"doc_id": "doc_001", "para_id": "p1", "quote": "被改过的引文"},
        {"doc_id": "doc_001", "para_id": "p9", "quote": "外头"},
    ]
    err = error_buckets(sub, gold_c, evidence, samples, samples=samples)
    assert err["误召"]["count"] >= 1
    assert err[CITATION_BUCKET]["count"] >= 1
    assert err["overlap"] >= 1
    assert "q1" in err["overlap_question_ids"]


# ---------- CLI --errors ----------
def test_cli_errors_flag(tmp_path):
    venv_py = ROOT / ".venv" / "bin" / "python"
    if not venv_py.is_file():
        import pytest
        pytest.skip("no .venv (C-24/#99)：裸 clone 上此格 skip，勿读成 failed")
    samples, gold_c = _fixture_two_questions()
    e = _dump(tmp_path / "e.json", [])
    c = _dump(tmp_path / "c.json", [
        {"question_id": "q1", "supporting_facts": [], "conflicting_facts": []},
        {"question_id": "q2", "supporting_facts": [], "conflicting_facts": []},
    ])
    ge = _dump(tmp_path / "ge.json", samples)
    gc = _dump(tmp_path / "gc.json", gold_c)
    out = subprocess.check_output(
        [str(venv_py), "-m", "scripts.score_official",
         "--evidence", str(e), "--conclusions", str(c),
         "--gold-evidence", str(ge), "--gold-conclusions", str(gc),
         "--errors"],
        cwd=ROOT, text=True,
    )
    assert "三桶不可相加" in out
    assert "漏召=2" in out


# ---------- d / e sensitivity ----------
def _sens_dossier() -> Dossier:
    """3 结论 × 2 信源；调 cred 使 ×0.8／×1.2 相对 ×1.0 都会翻 band。

    panel 取 1 人：与探针 n_panel 规则一致；多人编队会把 agreement 打到地板、
    分数挤在低档、×0.8 再也翻不出去。
    C-36 v2 加权和后 strength 权重仅 0.25——旧 cred=0.95／0.70＋4 条证据会全进高档、
    ±20% 翻不动；改用 cred=0.55／0.30＋各 1 条，让 CON-mid 贴 0.8 边界。
    """
    d = Dossier(question="敏感度夹具", panel=["a"])
    s1 = Source.create("S1", SourceType.PAPER, credibility=0.55, id="SRC1")
    s1.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text="段一原文足够长。"))
    s2 = Source.create("S2", SourceType.NEWS, credibility=0.30, id="SRC2")
    s2.segments.append(Segment(id="SRC2#s1", source_id="SRC2", text="段二原文足够长。"))
    d.add_source(s1)
    d.add_source(s2)
    # CON-hi：贴中档上沿
    d.conclusions.append(Conclusion.create("高侧", author="a", id="CON-hi"))
    d.add_evidence(EvidenceNode.create(
        "CON-hi", "段一原文足够长。", ["SRC1#s1"],
        level=EvidenceLevel.A, weight=1.0, id="EV-hi-0"))
    # CON-lo：中档下沿
    d.conclusions.append(Conclusion.create("低侧", author="a", id="CON-lo"))
    d.add_evidence(EvidenceNode.create(
        "CON-lo", "段二原文足够长。", ["SRC2#s1"],
        level=EvidenceLevel.A, weight=1.0, id="EV-lo-0"))
    # CON-mid：贴高档边界（×0.8／×1.2 翻档）
    d.conclusions.append(Conclusion.create("中侧", author="a", id="CON-mid"))
    for i in range(3):
        d.add_evidence(EvidenceNode.create(
            "CON-mid", "段一原文足够长。", ["SRC1#s1"],
            level=EvidenceLevel.B, weight=1.0, id=f"EV-mid-{i}"))
    recompute_all(d, n_panel=n_panel_of(d))
    return d


def test_d_deterministic_and_identity_at_1_0(tmp_path):
    d = _sens_dossier()
    report = tmp_path / "report.json"
    d.to_json(report)
    a = probe(report)
    b = probe(report)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    row1 = next(r for r in a["rows"] if r["multiplier"] == 1.0)
    assert row1["band_flips"] == 0
    assert row1["winner_flips"] == 0
    assert row1["objective_scores_changed"] is None  # 未给金标＝未量，不算变


def test_e_bands_flip_at_0_8_and_1_2(tmp_path):
    """#⑱：钉死 ×0.8 掉档／×1.2 升档的 conclusion id；等 cred 自证必红。"""
    d = _sens_dossier()
    report = tmp_path / "report.json"
    d.to_json(report)
    result = probe(report)
    by_m = {r["multiplier"]: r for r in result["rows"]}
    assert set(by_m) == set(MULTIPLIERS)
    base = by_m[1.0]["bands"]
    b08 = by_m[0.8]["bands"]
    b12 = by_m[1.2]["bands"]
    assert by_m[0.8]["band_flips"] >= 1
    assert by_m[1.2]["band_flips"] >= 1
    # 钉具体 id：×0.8 CON-mid 高→中（掉）；×1.2 CON-hi 中→高（升）
    assert base["CON-mid"] == "高" and b08["CON-mid"] == "中"
    assert base["CON-hi"] == "中" and b12["CON-hi"] == "高"

    # 自证：两侧信源 cred 拉平 ⇒ 上述 id 钉必红（只数 flips≥1 不够）
    d_eq = _sens_dossier()
    for src in d_eq.sources:
        src.credibility = 0.4
    from app.core.confidence import recompute_all
    recompute_all(d_eq, n_panel=n_panel_of(d_eq))
    eq_path = tmp_path / "eq.json"
    d_eq.to_json(eq_path)
    eq = probe(eq_path)
    eq_m = {r["multiplier"]: r for r in eq["rows"]}
    eq_base, eq08, eq12 = eq_m[1.0]["bands"], eq_m[0.8]["bands"], eq_m[1.2]["bands"]
    mid_drops = eq_base.get("CON-mid") == "高" and eq08.get("CON-mid") == "中"
    hi_rises = eq_base.get("CON-hi") == "中" and eq12.get("CON-hi") == "高"
    assert mid_drops is False
    assert hi_rises is False



def test_n_panel_uses_dossier_panel_len():
    d = _sens_dossier()
    assert n_panel_of(d) == 1
    d3 = Dossier(question="x", panel=["a", "b", "c"])
    assert n_panel_of(d3) == 3
    empty = Dossier(question="x", panel=[])
    assert n_panel_of(empty) == 1


def test_g_c21_face_artifact_guard():
    """C-21 样本面不许回潮「本文件仅含」（长期形状断言；瞬时 git diff 已摘＝#87）。"""
    n = int(subprocess.run(
        ["grep", "-c", "本文件仅含", "app/core/evidence.py"],
        cwd=ROOT, text=True, capture_output=True,
    ).stdout.strip() or "0")
    assert n == 0


def test_form_yi_named_in_error_buckets():
    samples, gold_c = _fixture_two_questions()
    err = error_buckets([], gold_c, [], samples, samples=samples)
    assert err["citation_bucket_form"] == "乙"
    assert CITATION_BUCKET in err
