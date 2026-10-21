"""C-21：样本面披露＋conclusion_face 同源＋两道闸反向格（固定 id 合成案卷）。"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
from pathlib import Path

from app.core.confidence import row_score_of
from app.core.evidence import (
    Conclusion,
    EvidenceLevel,
    EvidenceNode,
    conclusion_face,
    conclusion_face_pooled,
    format_conclusion_face_line,
)
from app.core.hashchain import HashChain
from app.export.official import export_official
from app.ingest.official_case import load_official_case
from app.pipeline import render_report_md
from scripts.score_official import score_submission
from tests.test_official_roundtrip import _para, _write_docs

ROOT = Path(__file__).resolve().parents[1]

_FACE_RE = re.compile(
    r"majority 态结论 (?P<n>\d+) 条；"
    r"内部结论 (?P<m>\d+) 条（逐态：majority (?P<maj>\d+)／"
    r"insufficient (?P<ins>\d+)／dissent (?P<dis>\d+)／"
    r"merged (?P<mer>\d+)＝归并组成员的溯源副本"
)


def _parse_face(text: str) -> dict[str, int]:
    m = _FACE_RE.search(text)
    assert m, f"face line missing in:\n{text[:800]}"
    return {k: int(m.group(k)) for k in ("n", "m", "maj", "ins", "dis", "mer")}


def _synth(
    tmp_path: Path,
    *,
    statuses: list[tuple[str, str]] | None = None,
    headline: str = "",
) -> "object":
    """固定 id 合成案卷。statuses＝[(status, statement), ...]。"""
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    content = "能量密度显著高于液态锂离子电池，客户回款率下降。"
    case = _write_docs(tmp_path, [{
        "doc_id": "doc_1",
        "title": "t",
        "publish_time": "2024-01-02",
        "content": content,
        "source_credibility": 0.5,
        "content_url": "",
        "paragraphs": [_para("para_9", 0, len(content))],
    }])
    dossier = load_official_case(case)
    specs = statuses or [
        ("majority", "多数结论甲"),
        ("insufficient", "资料不足：缺证乙"),
        ("dissent", "少数意见丙"),
        ("merged", "归并副本丁"),
    ]
    parts = {"strength": 0.4, "coverage": 0.5, "agreement": 1.0, "chain": 1.0}
    for i, (st, stmt) in enumerate(specs, start=1):
        cid = f"CON-{i}"
        con = Conclusion.create(stmt, author="m", id=cid)
        con.status = st
        con.confidence_parts = dict(parts)
        con.confidence = row_score_of(parts)
        dossier.conclusions.append(con)
        if st == "majority":
            dossier.add_evidence(EvidenceNode.create(
                cid, "能量密度显著高于液态锂离子电池", ["para_9"],
                level=EvidenceLevel.B, id=f"EV-{i}"))
    if headline:
        dossier.synthesis = {"headline": headline}
    else:
        dossier.synthesis = {}
    return dossier


def _q(qid: str = "q1") -> dict:
    return {"question_id": qid, "question": "能量密度是否占优？"}


# ---------- a ----------
def test_a_face_line_per_status_counts(tmp_path):
    d = _synth(tmp_path / "a")
    paths = export_official([(_q(), d)], tmp_path / "a_out")
    notes = paths["notes"].read_text(encoding="utf-8")
    assert "## 本次导出" in notes
    assert "本次提交物 pooled" in notes
    assert "questions/<question_id>/report.json" in notes
    assert "其余" not in notes.split("## 本次导出", 1)[1]
    assert "其他" not in notes.split("## 本次导出", 1)[1]
    face = _parse_face(notes)
    assert face["n"] == 1 and face["maj"] == 1
    assert face["ins"] == 1 and face["dis"] == 1 and face["mer"] == 1
    assert face["m"] == 4
    assert face["n"] + face["ins"] + face["dis"] + face["mer"] == face["m"]
    assert "溯源副本" in notes
    assert f"不含副本 {face['m'] - face['mer']} 条" in notes


# ---------- a2 ----------
def test_a2_all_insufficient_still_discloses(tmp_path):
    d = _synth(tmp_path / "a2i", statuses=[
        ("insufficient", "资料不足：甲"),
        ("insufficient", "资料不足：乙"),
        ("insufficient", "资料不足：丙"),
    ])
    paths = export_official([(_q(), d)], tmp_path / "a2i_out")
    face = _parse_face(paths["notes"].read_text(encoding="utf-8"))
    assert face["n"] == 0
    assert face["ins"] == 3
    assert face["m"] == 3


def test_a2_merged_only_not_swallowed(tmp_path):
    d = _synth(tmp_path / "a2m", statuses=[
        ("merged", "副本甲"),
        ("merged", "副本乙"),
    ])
    paths = export_official([(_q(), d)], tmp_path / "a2m_out")
    face = _parse_face(paths["notes"].read_text(encoding="utf-8"))
    assert face["n"] == 0
    assert face["mer"] == 2
    assert face["m"] == 2


# ---------- b ----------
def test_b_structure_one_def_two_call_sites():
    hits = subprocess.check_output(
        ["grep", "-rn", "def conclusion_face(", "app/",
         "--include=*.py"],
        cwd=ROOT, text=True,
    ).strip().splitlines()
    assert len(hits) == 1, hits
    assert "app/core/evidence.py" in hits[0]
    off = (ROOT / "app/export/official.py").read_text(encoding="utf-8")
    pipe = (ROOT / "app/pipeline.py").read_text(encoding="utf-8")
    assert "conclusion_face_pooled(" in off
    assert "conclusion_face(" in pipe
    assert "format_conclusion_face_line(" in off
    assert "format_conclusion_face_line(" in pipe


def test_b_behavior_single_run_four_numbers_match(tmp_path):
    d = _synth(tmp_path / "b1")
    paths = export_official([(_q(), d)], tmp_path / "b1_out")
    notes_face = _parse_face(paths["notes"].read_text(encoding="utf-8"))
    md = render_report_md(d, HashChain(), [])
    report_face = _parse_face(md)
    for key in ("n", "m", "maj", "ins", "dis", "mer"):
        assert notes_face[key] == report_face[key], key
    assert "本案卷" in md
    assert "本次提交物 pooled" in paths["notes"].read_text(encoding="utf-8")


def test_b_behavior_dual_run_pooled_m_strictly_greater(tmp_path):
    d1 = _synth(tmp_path / "b2a", statuses=[
        ("majority", "甲"),
        ("insufficient", "乙"),
    ])
    d2 = _synth(tmp_path / "b2b", statuses=[
        ("majority", "丙"),
        ("dissent", "丁"),
        ("merged", "戊"),
    ])
    paths = export_official(
        [(_q("q1"), d1), (_q("q2"), d2)],
        tmp_path / "b2_out",
    )
    notes_face = _parse_face(paths["notes"].read_text(encoding="utf-8"))
    md = render_report_md(d1, HashChain(), [])
    case_face = _parse_face(md)
    assert notes_face["m"] > case_face["m"]
    assert notes_face["m"] == 5
    assert case_face["m"] == 2


def test_b_docstring_insufficient_documented_no_third_assignment():
    ev = (ROOT / "app/core/evidence.py").read_text(encoding="utf-8")
    assert ev.lower().count("insufficient") >= 1
    # 赋值点仍＝2（pipeline + ingress），不许新增第三处
    hits = subprocess.check_output(
        ["grep", "-rn", 'status = "insufficient"', "app/",
         "--include=*.py"],
        cwd=ROOT, text=True,
    ).strip().splitlines()
    assert len(hits) == 2, hits
    joined = "\n".join(hits)
    assert "pipeline.py" in joined and "ingress.py" in joined


# ---------- c：两把刀红名不相交 ----------
def test_c_knife_confidence_excludes_insufficient(tmp_path):
    """摘 official.py:_confidence_rows 的 majority continue 必红本格。"""
    d = _synth(tmp_path / "c1", statuses=[
        ("majority", "多数句"),
        ("insufficient", "资料不足：不该进 confidence"),
    ], headline="")
    paths = export_official([(_q(), d)], tmp_path / "c1_out")
    conf = json.loads(paths["confidence"].read_text(encoding="utf-8"))
    ids = {r["conclusion_id"] for r in conf}
    assert "CON-1" in ids
    assert "CON-2" not in ids
    assert len(conf) == 1


def test_c_knife_conclusion_text_excludes_insufficient(tmp_path):
    """摘 _conclusion_text 的 majority 过滤必红本格；headline 必须空才走到那半。"""
    secret = "资料不足：这句话不该进 conclusions.conclusion"
    d = _synth(tmp_path / "c2", statuses=[
        ("insufficient", secret),
        ("dissent", "少数句也不该当 conclusion"),
    ], headline="")
    assert not (d.synthesis or {}).get("headline")
    paths = export_official([(_q(), d)], tmp_path / "c2_out")
    rows = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["conclusion"] == ""
    assert secret not in rows[0]["conclusion"]


# ---------- d ----------
def test_d_four_json_byte_stable_across_two_exports(tmp_path):
    """库内形状＝C-17:154-173；face_line 只动 notes，四份 JSON 两次导出逐字节相同。"""
    d = _synth(tmp_path / "d", statuses=[
        ("majority", "有支撑"),
        ("insufficient", "资料不足：x"),
    ])
    a = export_official([(_q(), d)], tmp_path / "d_a")
    b = export_official([(_q(), d)], tmp_path / "d_b")
    for key in ("evidence", "conclusions", "confidence", "conflict_resolution"):
        assert a[key].read_bytes() == b[key].read_bytes()
    notes = a["notes"].read_text(encoding="utf-8")
    assert "本次提交物 pooled" in notes
    assert a["notes"].read_bytes() == b["notes"].read_bytes()


# ---------- e ----------
def test_e_score_official_diff_empty():
    out = subprocess.check_output(
        ["git", "diff", "--", "scripts/score_official.py"],
        cwd=ROOT, text=True,
    )
    assert out == ""


def test_e_blank_submission_still_all_zero(tmp_path):
    """库内三格②：沿用 test_official_roundtrip.test_blank_submission_scores_all_zero。"""
    from scripts.score_official import format_report
    from tests.test_official_roundtrip import _dump, _gold_fact

    samples = [
        {"fact_id": "fact_001", "doc_id": "doc_001",
         "para_id": "doc_001#p2", "quote": "甲"},
    ]
    gold_c = [{
        "question_id": "q_001",
        "question": "问",
        "conclusion": "结",
        "supporting_facts": [_gold_fact("fact_001")],
        "conflicting_facts": [_gold_fact("fact_001", conflict=True)],
    }]
    blank_c = [{
        "question_id": "q_001",
        "question": "问",
        "conclusion": "",
        "supporting_facts": [],
        "conflicting_facts": [],
    }]
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", []),
        _dump(tmp_path / "conclusions.json", blank_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=_dump(tmp_path / "evidence_samples.json", samples),
    )
    for key in ("score_2_2_1", "score_2_4_1", "score_2_4_2",
                "score_2_5_1", "score_2_5_2"):
        assert metrics[key] == 0, key
    assert metrics["Precision_src"] == 0.0
    assert metrics["Precision_sup"] == 0.0
    assert metrics["Precision_conf"] == 0.0
    assert format_report(metrics).splitlines()[0]


def test_e_c20_score_submission_has_no_confidence_param():
    """库内三格③：score_submission 形参与全文不含 confidence。"""
    params = inspect.signature(score_submission).parameters
    assert "confidence" not in params
    src = (ROOT / "scripts" / "score_official.py").read_text(encoding="utf-8")
    assert src.count("confidence") == 0


# ---------- f ----------
def test_f_dead_numbers_gone():
    proc = subprocess.run(
        ["grep", "-cE", r"0/40|0/57|max≈0.55",
         "app/export/official.py"],
        cwd=ROOT, text=True, capture_output=True,
    )
    # grep -c 零命中时退出码 1、stdout 仍是 "0"
    n = int((proc.stdout or "0").strip() or "0")
    assert n == 0
    notes_src = (ROOT / "app/export/official.py").read_text(encoding="utf-8")
    conf_sec = notes_src.split("## confidence.json", 1)[1].split(
        "## conflict_resolution.json", 1)[0]
    assert "0/40" not in conf_sec
    assert "0/57" not in conf_sec
    assert "max≈0.55" not in conf_sec


def test_f_face_line_matches_fixture_counts(tmp_path):
    d = _synth(tmp_path / "f")
    paths = export_official([(_q(), d)], tmp_path / "f_out")
    notes = paths["notes"].read_text(encoding="utf-8")
    face = conclusion_face(d)
    parsed = _parse_face(notes)
    assert parsed["maj"] == face["majority"]
    assert parsed["ins"] == face["insufficient"]
    assert parsed["dis"] == face["dissent"]
    assert parsed["mer"] == face["merged"]
    assert parsed["m"] == face["total"]
    assert parsed["n"] == face["majority"]


# ---------- r1（第二轮：模板点名 confidence.json，不许写「本文件」）----------
def test_r1a_benwenjian_gone_confidence_json_literal():
    proc_a = subprocess.run(
        ["grep", "-c", "本文件仅含", "app/core/evidence.py"],
        cwd=ROOT, text=True, capture_output=True,
    )
    proc_b = subprocess.run(
        ["grep", "-c", "未进本文件", "app/core/evidence.py"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert int((proc_a.stdout or "0").strip() or "0") == 0
    assert int((proc_b.stdout or "0").strip() or "0") == 0
    src = (ROOT / "app/core/evidence.py").read_text(encoding="utf-8")
    assert '_FACE_ARTIFACT = "confidence.json"' in src
    assert "提交物 {_FACE_ARTIFACT} 仅含消解后 majority 态结论" in src
    assert "未进 {_FACE_ARTIFACT} 的" in src


def test_r1b_report_md_names_artifact_not_benwenjian(tmp_path):
    """首屏 face 行：不含「本文件」、含 confidence.json；未进条数＝三非多数态之和。"""
    d = _synth(tmp_path / "r1b")
    face = conclusion_face(d)
    expected_out = (
        int(face["insufficient"])
        + int(face["dissent"])
        + int(face["merged"])
    )
    assert expected_out == 3  # 夹具默认各 1
    md = render_report_md(d, HashChain(), [])
    hits = [
        ln for ln in md.splitlines()
        if "majority 态结论" in ln and "内部结论" in ln
    ]
    assert len(hits) == 1
    line = hits[0]
    assert "本文件" not in line
    assert "confidence.json" in line
    assert f"未进 confidence.json 的 {expected_out} 条" in line


# ---------- k helpers / regression guards ----------
def test_k_c20_band_case_face_literal_still_two():
    n = int(subprocess.check_output(
        ["grep", "-c", "本案卷 3 条", "tests/test_c20_band.py"],
        cwd=ROOT, text=True,
    ).strip())
    assert n == 2


def test_k_no_second_status_counter_impl():
    """全仓只许一处 def conclusion_face；majority_conclusions 语义不动。"""
    hits = subprocess.check_output(
        ["grep", "-rn", "def conclusion_face(", "app/",
         "--include=*.py"],
        cwd=ROOT, text=True,
    ).strip().splitlines()
    assert len(hits) == 1
    from app.core.conflicts import majority_conclusions
    from app.core.evidence import Dossier

    d = Dossier(question="q")
    c1 = Conclusion.create("a", author="m", id="CON-1")
    c2 = Conclusion.create("b", author="m", id="CON-2")
    c2.status = "insufficient"
    d.conclusions.extend([c1, c2])
    assert len(majority_conclusions(d)) == 1
    face = conclusion_face(d)
    assert face["majority"] == 1
    assert face["insufficient"] == 1


def test_k_json_never_promotes_non_majority(tmp_path):
    d = _synth(tmp_path / "k")
    paths = export_official([(_q(), d)], tmp_path / "k_out")
    conf = json.loads(paths["confidence"].read_text(encoding="utf-8"))
    conc = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    blob = json.dumps(conf) + json.dumps(conc)
    assert "insufficient" not in blob
    assert "dissent" not in blob
    assert '"merged"' not in blob


def test_k_pooled_helper_sums():
    from app.core.evidence import Dossier
    a = Dossier(question="a")
    b = Dossier(question="b")
    for st in ("majority", "insufficient"):
        c = Conclusion.create(st, author="m", id=f"A-{st}")
        c.status = st
        a.conclusions.append(c)
    for st in ("dissent", "merged", "majority"):
        c = Conclusion.create(st, author="m", id=f"B-{st}")
        c.status = st
        b.conclusions.append(c)
    pooled = conclusion_face_pooled([a, b])
    assert pooled == {
        "majority": 2, "insufficient": 1, "dissent": 1, "merged": 1,
        "other": 0, "total": 5,
    }
    line = format_conclusion_face_line(pooled, surface="本次提交物 pooled")
    assert "majority 2" in line and "insufficient 1" in line
    assert "不含副本 4 条" in line
    assert "confidence.json" in line
    assert "本文件" not in line
