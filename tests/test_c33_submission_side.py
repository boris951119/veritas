"""C-33：冲突侧从消解记录映射进 conflicting_facts；支撑侧与被交结论同源。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.evidence import Conclusion, EvidenceNode
from app.export import official as official_mod
from app.export.official import (
    _FIELD_NOTES,
    _conclusion_support_diverged,
    _conflicting_facts,
    _conclusion_text,
    _supporting_facts,
    export_official,
)
from app.ingest.official_case import load_official_case
from tests.test_official_roundtrip import _para, _write_docs

ROOT = Path(__file__).resolve().parents[1]


def _dossier_two_sides(
    tmp_path: Path,
    *,
    winner: str = "CON-A",
    method: str = "strength",
    include_dissent_only_ev: bool = True,
    loser_segment: str = "para_lose",
    winner_segment: str = "para_win",
    dissent_only_segment: str = "para_dissent_only",
    headline: str = "headline 不应覆盖 majority statement",
):
    """造一题：majority CON-A vs dissent CON-B，冲突对有胜负；另挂一条只属 dissent 的证据。"""
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    win_text = "胜方引用：甲事件确由乙方主导。"
    lose_text = "败方引用：甲事件与乙方无关。"
    dissent_only = "仅少数意见独有的段落，不该进支撑集。"
    content = win_text + lose_text + dissent_only
    p_win_start = 0
    p_lose_start = len(win_text)
    p_do_start = len(win_text) + len(lose_text)
    case = _write_docs(tmp_path, [{
        "doc_id": "doc_1",
        "title": "t",
        "publish_time": "2024-01-02",
        "content": content,
        "source_credibility": 0.5,
        "content_url": "",
        "paragraphs": [
            _para(winner_segment, p_win_start, p_lose_start),
            _para(loser_segment, p_lose_start, p_do_start),
            _para(dissent_only_segment, p_do_start, len(content)),
        ],
    }])
    dossier = load_official_case(case)
    con_a = Conclusion.create("甲方主导甲事件", author="m", id="CON-A")
    con_a.status = "majority"
    con_b = Conclusion.create("甲方与甲事件无关", author="n", id="CON-B")
    con_b.status = "dissent"
    dossier.conclusions.extend([con_a, con_b])
    dossier.add_evidence(EvidenceNode.create(
        "CON-A", win_text, [winner_segment], id="EV-A"))
    dossier.add_evidence(EvidenceNode.create(
        "CON-B", lose_text, [loser_segment], id="EV-B"))
    if include_dissent_only_ev:
        dossier.add_evidence(EvidenceNode.create(
            "CON-B", dissent_only, [dissent_only_segment], id="EV-B-ONLY"))
    dossier.conflicts = [{
        "id": "CF-1",
        "a_id": "CON-A",
        "b_id": "CON-B",
        "topic": "主导方",
        "description": "谁主导",
        "resolution": {
            "winner_id": winner,
            "method": method,
            "rationale": "证据更强",
            "basis": {},
            "resolution_type": "Evidence_Strength",
            "decision_path": "strength",
            "omissions": [],
        },
    }]
    dossier.synthesis = {"headline": headline} if headline else {}
    return dossier


def _q(qid: str = "q1") -> dict:
    return {"question_id": qid, "question": "谁主导？"}


def _loser_locs(dossier) -> set[tuple[str, str]]:
    """落败结论（status=dissent 或非 winner）证据段落集合，供反查。"""
    locs: set[tuple[str, str]] = set()
    for con in dossier.conclusions:
        if con.status == "dissent" or con.id == "CON-B":
            for ev in dossier.evidences_of(con.id):
                for sid in ev.segment_ids:
                    loc = official_mod._segment_locator(dossier, sid)
                    if loc is not None:
                        locs.add(loc)
    return locs


# ---------- a ----------
def test_a_conflicting_facts_nonempty_and_traceable(tmp_path):
    """夹具真冲突有胜负 ⇒ conflicting_facts 非空，且每条能反查到落败结论证据段落。"""
    d = _dossier_two_sides(tmp_path / "a")
    paths = export_official([(_q(), d)], tmp_path / "a_out")
    rows = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    assert len(rows) == 1
    conf = rows[0]["conflicting_facts"]
    assert conf, "有胜负的冲突对不应再交空 conflicting_facts"
    loser_locs = _loser_locs(d)
    for fact in conf:
        key = (fact["doc_id"], fact["para_id"])
        assert key in loser_locs, f"{key} 无法从落败结论证据反查"


# ---------- b reverse ----------
def test_b_reverse_empty_conflicts_breaks_a(tmp_path, monkeypatch):
    """自证：把件①改回恒 [] ⇒ a 的非空断言必红。"""
    d = _dossier_two_sides(tmp_path / "b1")

    def _empty(dossier):
        return [], 0, 0

    monkeypatch.setattr(official_mod, "_conflicting_facts", _empty)
    paths = export_official([(_q(), d)], tmp_path / "b1_out")
    rows = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    with pytest.raises(AssertionError):
        assert rows[0]["conflicting_facts"], "恒 [] 时本句应红"


def test_b_tie_not_merged(tmp_path):
    """tie 不并入 conflicting_facts；计入跳过（tie 桶）。"""
    d = _dossier_two_sides(tmp_path / "b2", winner="tie", method="tie")
    facts, skip_tie, skip_noloc = _conflicting_facts(d)
    assert facts == []
    assert skip_tie == 1
    assert skip_noloc == 0
    paths = export_official([(_q(), d)], tmp_path / "b2_out")
    rows = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    assert rows[0]["conflicting_facts"] == []
    notes = paths["notes"].read_text(encoding="utf-8")
    assert "tie／未分胜负 1 对" in notes


def test_b_reverse_tie_counted_as_conflict_breaks(tmp_path, monkeypatch):
    """自证：把『tie 也算冲突』塞进去 ⇒ tie 不并入那格必红。"""
    d = _dossier_two_sides(tmp_path / "b3", winner="tie", method="tie")

    def _tie_as_conflict(dossier):
        # 假装把败方（任意一侧）也并入
        facts = []
        seen = set()
        for con in dossier.conclusions:
            for ev in dossier.evidences_of(con.id):
                for sid in ev.segment_ids:
                    loc = official_mod._segment_locator(dossier, sid)
                    if loc is None or loc in seen:
                        continue
                    seen.add(loc)
                    facts.append({"doc_id": loc[0], "para_id": loc[1]})
        return facts, 0, 0

    monkeypatch.setattr(official_mod, "_conflicting_facts", _tie_as_conflict)
    paths = export_official([(_q(), d)], tmp_path / "b3_out")
    rows = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    with pytest.raises(AssertionError):
        assert rows[0]["conflicting_facts"] == [], "tie 也被并入时本句应红"


# ---------- c ----------
def test_c_supporting_excludes_dissent_only_evidence(tmp_path):
    """支撑只含被交结论段落；只属于 dissent 的证据不在支撑集内。"""
    d = _dossier_two_sides(tmp_path / "c")
    paths = export_official([(_q(), d)], tmp_path / "c_out")
    rows = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    support = {(f["doc_id"], f["para_id"]) for f in rows[0]["supporting_facts"]}
    # dissent-only 段落
    assert ("doc_1", "para_dissent_only") not in support
    # winner 自己的段落在
    assert ("doc_1", "para_win") in support
    # 落败侧段落不在支撑（在冲突侧）
    assert ("doc_1", "para_lose") not in support


# ---------- d reverse ----------
def test_d_reverse_all_dossier_support_breaks_c(tmp_path, monkeypatch):
    """自证：把 _supporting_facts 改回全案卷 ⇒ c 必红。"""
    d = _dossier_two_sides(tmp_path / "d")

    def _all(dossier):
        return official_mod._supporting_facts_all(dossier)

    monkeypatch.setattr(official_mod, "_supporting_facts", _all)
    paths = export_official([(_q(), d)], tmp_path / "d_out")
    rows = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    support = {(f["doc_id"], f["para_id"]) for f in rows[0]["supporting_facts"]}
    with pytest.raises(AssertionError):
        assert ("doc_1", "para_dissent_only") not in support


# ---------- e ----------
def test_e_majority_statement_not_headline(tmp_path):
    """有带证据 majority 时 conclusion＝statement，≠ headline。"""
    d = _dossier_two_sides(
        tmp_path / "e1",
        headline="这是 headline，不该当 conclusion",
    )
    paths = export_official([(_q(), d)], tmp_path / "e1_out")
    rows = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    assert rows[0]["conclusion"] == "甲方主导甲事件"
    assert rows[0]["conclusion"] != "这是 headline，不该当 conclusion"
    assert _conclusion_text(d) == "甲方主导甲事件"


def test_e_headline_fallback_disclosed(tmp_path):
    """#123：不同源披露冒号后紧跟本题 qid；有兜底时点名。"""
    tmp = tmp_path / "e2"
    tmp.mkdir()
    content = "无证据时的背景段落足够长。"
    case = _write_docs(tmp, [{
        "doc_id": "doc_1",
        "title": "t",
        "publish_time": "2024-01-02",
        "content": content,
        "source_credibility": 0.5,
        "content_url": "",
        "paragraphs": [_para("para_x", 0, len(content))],
    }])
    d = load_official_case(case)
    # majority 但不挂证据
    con = Conclusion.create("空majority", author="m", id="CON-EMPTY")
    con.status = "majority"
    d.conclusions.append(con)
    d.synthesis = {"headline": "headline 兜底文本"}
    qid = "q-headline-1"
    paths = export_official([(_q(qid), d)], tmp_path / "e2_out")
    rows = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    assert rows[0]["conclusion"] == "headline 兜底文本"
    notes = paths["notes"].read_text(encoding="utf-8")
    needle = f"文本与支撑不同源（headline 兜底）的 question_id：{qid}"
    assert needle in notes
    # 冒号后紧跟本题 qid（不允许先写别的再附带）
    assert f"question_id：{qid}" in notes


def test_e_headline_no_fallback_writes_none(tmp_path):
    """#123 反向腿：不兜底时披露行必须写（无）。"""
    d = _dossier_two_sides(tmp_path / "e3")
    assert _conclusion_support_diverged(d) is False
    paths = export_official([(_q("q-ok"), d)], tmp_path / "e3_out")
    notes = paths["notes"].read_text(encoding="utf-8")
    assert "文本与支撑不同源（headline 兜底）的 question_id：（无）。" in notes


def test_e_headline_diverged_always_false_self_proof(tmp_path, monkeypatch):
    """#123 自证：_conclusion_support_diverged 恒 False ⇒ 有兜底时披露必丢题号。"""
    tmp = tmp_path / "e4"
    tmp.mkdir()
    content = "无证据时的背景段落足够长。"
    case = _write_docs(tmp, [{
        "doc_id": "doc_1",
        "title": "t",
        "publish_time": "2024-01-02",
        "content": content,
        "source_credibility": 0.5,
        "content_url": "",
        "paragraphs": [_para("para_x", 0, len(content))],
    }])
    d = load_official_case(case)
    con = Conclusion.create("空majority", author="m", id="CON-EMPTY")
    con.status = "majority"
    d.conclusions.append(con)
    d.synthesis = {"headline": "headline 兜底文本"}
    monkeypatch.setattr(official_mod, "_conclusion_support_diverged", lambda _d: False)
    paths = export_official([(_q("q-should-appear"), d)], tmp_path / "e4_out")
    notes = paths["notes"].read_text(encoding="utf-8")
    diverge_lines = [
        ln for ln in notes.splitlines()
        if "文本与支撑不同源（headline 兜底）的 question_id：" in ln
    ]
    assert diverge_lines == [
        "文本与支撑不同源（headline 兜底）的 question_id：（无）。"
    ]
    assert "q-should-appear" not in diverge_lines[0]


# ---------- f（禁品零 diff：本文件不碰那些路径，另有命令核）----------
def test_f_forbidden_paths_untouched_by_this_change():
    """内容断言钉住禁品常量字面值（不许依赖工作树瞬时状态的常驻用例）。"""
    root = Path(__file__).resolve().parents[1]
    conf_src = (root / "app/core/confidence.py").read_text(encoding="utf-8")
    ev_src = (root / "app/core/evidence.py").read_text(encoding="utf-8")
    assert "_CAUSATION_BONUS = 1.15" in conf_src
    assert "EvidenceLevel.A: 1.0" in ev_src
    assert "EvidenceLevel.B: 0.8" in ev_src
    assert "EvidenceLevel.C: 0.55" in ev_src
    assert "EvidenceLevel.D: 0.3" in ev_src


# ---------- g ----------
def test_g_probe_help_exit_zero():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/probe_submission_coverage.py"),
         "--help"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert r.returncode == 0
    assert "--dir" in r.stdout


def test_g_probe_requires_dir():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/probe_submission_coverage.py")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert r.returncode != 0
    assert "--dir" in (r.stderr + r.stdout) or "显式" in (r.stderr + r.stdout)


def test_g_probe_prints_counts(tmp_path):
    d = _dossier_two_sides(tmp_path / "g")
    paths = export_official([(_q(), d)], tmp_path / "g_out")
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/probe_submission_coverage.py"),
         "--dir", str(tmp_path / "g_out")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "支撑" in out and "冲突" in out
    assert "冲突侧跳过" in out
    assert "题数=" in out


# ---------- h ----------
def test_h_field_notes_three_sentences():
    notes = _FIELD_NOTES
    assert "winner_id" in notes or "对立" in notes
    assert "tie" in notes and ("段落取不到" in notes or "取不到" in notes)
    assert "抽取即可能编造" in notes


def test_h_no_instant_vcs_assertions():
    """新增测试禁瞬时 vcs 断言（判据 h：源文件不得出现连续的 git+diff 字面量）。"""
    src = Path(__file__).read_text(encoding="utf-8")
    needle = "git" + " " + "diff"
    assert src.count(needle) == 0
