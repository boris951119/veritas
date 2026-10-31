"""C-46：conflict_resolution 记录可读化——冲突清单 + 结果。

边界：只动交付面 records 构造与字段说明；不改 conflicts.py 判定／
_REOPEN_WHEN／METHOD_TO_RESOLUTION_TYPE／_conflicting_facts 跳平局／置信合式。
零 LLM。不读未入库 cases/*/out* 做断言绿（通用性腿用 Dossier.from_dict
合成缺 decision_path 的旧形态，或本机有产物时选跑）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.core.evidence import Conclusion, Dossier, EvidenceNode
from app.export import official as official_mod
from app.export.official import (
    _FIELD_NOTES,
    _C46_RECORD_MAX,
    _C46_SIZE_OMISSION,
    _C46_STMT_MAX,
    _C46_TRUNC_MARK,
    _c46_result_of,
    _c46_side_entry,
    _c46_truncate_statement,
    _conflict_rows,
    export_official,
)
from tests.test_c33_submission_side import _dossier_two_sides, _q


# ---------- helpers ----------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _records(paths) -> list[dict]:
    payload = json.loads(paths["conflict_resolution"].read_text(encoding="utf-8"))
    return list(payload.get("records") or [])


def _old_conflict_rows(question_id: str, dossier: Dossier):
    """改前形态：无 冲突清单／结果（仅用于 sha 对照）。"""
    from app.core.conflicts import METHOD_TO_RESOLUTION_TYPE

    rows = []
    omitted_any: list[str] = []
    for pair in dossier.conflicts or []:
        if not isinstance(pair, dict):
            continue
        res = pair.get("resolution") if isinstance(pair.get("resolution"), dict) else {}
        method = str(res.get("method") or "")
        basis = res.get("basis")
        rtype = res.get("resolution_type")
        restart = res.get("restart_condition")
        if restart is None:
            restart = res.get("重启条件")
        omissions = []
        for note in list(res.get("omissions") or []):
            text = str(note or "").strip()
            if text and text not in omissions:
                omissions.append(text)
        if basis is None or basis == "" or basis == {}:
            omissions.append("basis")
            basis = ""
        if rtype in (None, ""):
            omissions.append("resolution_type")
            rtype = METHOD_TO_RESOLUTION_TYPE.get(method, "其他")
        if restart in (None, ""):
            omissions.append("重启条件")
            restart = ""
        omitted_any.extend(omissions)
        rows.append({
            "question_id": question_id,
            "conflict_id": str(pair.get("id") or ""),
            "resolution_type": rtype,
            "basis": basis if basis is not None else "",
            "重启条件": restart if restart is not None else "",
            "method": method,
            "rationale": str(res.get("rationale") or ""),
            "omissions": omissions,
        })
    return rows, sorted(set(omitted_any))


# ---------- a：换分三项 sha 不变 ----------

def test_a_three_json_sha_unchanged_when_only_conflict_rows_change(tmp_path, monkeypatch):
    """同一夹具：只换 _conflict_rows（改前形态 vs 现形态），
    evidence／conclusions／confidence 三份 sha256 逐位相同；
    conflict_resolution 允许变。"""
    d = _dossier_two_sides(tmp_path / "a_src")
    out_new = tmp_path / "a_new"
    paths_new = export_official([(_q(), d)], out_new)
    sha_e = _sha(paths_new["evidence"])
    sha_c = _sha(paths_new["conclusions"])
    sha_f = _sha(paths_new["confidence"])
    sha_cr = _sha(paths_new["conflict_resolution"])

    monkeypatch.setattr(official_mod, "_conflict_rows", _old_conflict_rows)
    out_old = tmp_path / "a_old"
    paths_old = export_official([(_q(), d)], out_old)
    assert _sha(paths_old["evidence"]) == sha_e
    assert _sha(paths_old["conclusions"]) == sha_c
    assert _sha(paths_old["confidence"]) == sha_f
    assert _sha(paths_old["conflict_resolution"]) != sha_cr, "conflict_resolution 应因新字段而变"


# ---------- b：键在场（探针认 冲突清单／结果）----------

def test_b_keys_present_and_probe_element_helpers():
    """汇总形态：冲突清单／结果键在场 ⇒ 探针 _element_* 报 present。"""
    from scripts import probe_resolution_records as probe

    rec = {
        "冲突清单": [
            {"conclusion_id": "CON-A", "statement": "甲", "source_ids": [], "para_ids": []},
            {"conclusion_id": "CON-B", "statement": "乙", "source_ids": [], "para_ids": []},
        ],
        "结果": {"outcome": "甲胜", "winner_id": "CON-A", "tie": False},
        "rationale": "x",
        "basis": {"type_applies": True},
        "resolution_type": "语义可信度",
    }
    q, _ = probe._element_清单(rec)
    r, _ = probe._element_结果(rec)
    assert q == "present"
    assert r == "present"


def test_b_export_records_have_both_keys(tmp_path):
    d = _dossier_two_sides(tmp_path / "b_src")
    paths = export_official([(_q(), d)], tmp_path / "b_out")
    recs = _records(paths)
    assert len(recs) == 1
    assert "冲突清单" in recs[0]
    assert "结果" in recs[0]
    assert len(recs[0]["冲突清单"]) == 2


# ---------- c：平局不许伪造 winner；摘掉 outcome 必须红 ----------

def test_c_tie_outcome_并存不裁决_empty_winner(tmp_path):
    d = _dossier_two_sides(tmp_path / "c_src", winner="tie", method="tie")
    paths = export_official([(_q(), d)], tmp_path / "c_out")
    rec = _records(paths)[0]
    result = rec["结果"]
    assert result["outcome"] == "并存不裁决"
    assert result["winner_id"] == ""
    assert result["tie"] is True


def test_c_reverse_omit_outcome_must_red(tmp_path, monkeypatch):
    """自证：把 outcome 那行摘掉 ⇒ 守护断言必红。"""
    d = _dossier_two_sides(tmp_path / "c_rev", winner="tie", method="tie")

    real = official_mod._c46_result_of

    def _drop_outcome(pair, res):
        out = real(pair, res)
        out.pop("outcome", None)
        return out

    monkeypatch.setattr(official_mod, "_c46_result_of", _drop_outcome)
    paths = export_official([(_q(), d)], tmp_path / "c_rev_out")
    rec = _records(paths)[0]
    with pytest.raises(AssertionError):
        assert rec["结果"].get("outcome") == "并存不裁决"
        assert rec["结果"].get("winner_id") == ""


def test_c_winner_maps_甲乙(tmp_path):
    d = _dossier_two_sides(tmp_path / "c_win", winner="CON-A")
    paths = export_official([(_q(), d)], tmp_path / "c_win_out")
    r = _records(paths)[0]["结果"]
    assert r["outcome"] == "甲胜"
    assert r["winner_id"] == "CON-A"
    assert r["tie"] is False

    d2 = _dossier_two_sides(tmp_path / "c_win_b", winner="CON-B")
    # CON-B is b_id → 乙胜；但 fixture 把 winner 设为 CON-B 时 status 仍是 A majority
    # ——结果字段只看 winner_id vs a_id/b_id，不看 status
    paths2 = export_official([(_q(), d2)], tmp_path / "c_win_b_out")
    r2 = _records(paths2)[0]["结果"]
    assert r2["outcome"] == "乙胜"
    assert r2["winner_id"] == "CON-B"


# ---------- d：statement 逐字；自造文案必须红 ----------

def test_d_statement_is_verbatim_prefix_or_full(tmp_path):
    d = _dossier_two_sides(tmp_path / "d_src")
    # 加长 statement 测截断
    long = "甲" * 200
    for con in d.conclusions:
        if con.id == "CON-A":
            con.statement = long
    paths = export_official([(_q(), d)], tmp_path / "d_out")
    side_a = _records(paths)[0]["冲突清单"][0]
    assert side_a["conclusion_id"] == "CON-A"
    stmt = side_a["statement"]
    assert stmt.endswith(_C46_TRUNC_MARK)
    assert len(stmt) <= _C46_STMT_MAX
    # 去掉截断标后必须是原文前缀
    prefix = stmt[: -len(_C46_TRUNC_MARK)]
    assert long.startswith(prefix)
    assert prefix == long[: len(prefix)]


def test_d_reverse_fabricated_statement_must_red(tmp_path, monkeypatch):
    """自证：把逐字取法换成自造文案 ⇒ 守护断言必红。"""
    d = _dossier_two_sides(tmp_path / "d_rev")
    real_stmt = next(c.statement for c in d.conclusions if c.id == "CON-A")

    def _fake_side(dossier, conclusion_id, stmt_limit=_C46_STMT_MAX):
        entry = _c46_side_entry(dossier, conclusion_id, stmt_limit)
        if conclusion_id == "CON-A":
            entry["statement"] = "这是自造文案，不是产物原文"
        return entry

    monkeypatch.setattr(official_mod, "_c46_side_entry", _fake_side)
    paths = export_official([(_q(), d)], tmp_path / "d_rev_out")
    stmt = _records(paths)[0]["冲突清单"][0]["statement"]
    with pytest.raises(AssertionError):
        assert real_stmt.startswith(stmt.replace(_C46_TRUNC_MARK, "")) or stmt == real_stmt
        assert "自造" not in stmt


# ---------- e：零模型 ----------

def test_e_n_calls_zero(tmp_path, monkeypatch):
    """导出路径不得触发任何 LLM 客户端。"""
    calls = {"n": 0}

    class _Boom:
        def __getattr__(self, name):
            calls["n"] += 1
            raise RuntimeError(f"LLM touched: {name}")

    # 若有人误 import chat／complete，这里会炸
    import sys
    monkeypatch.setitem(sys.modules, "app.llm", _Boom())  # type: ignore
    d = _dossier_two_sides(tmp_path / "e_src")
    export_official([(_q(), d)], tmp_path / "e_out")
    assert calls["n"] == 0


# ---------- f：通用性／缺 decision_path 不抛 ----------

def test_f_missing_decision_path_no_raise(tmp_path):
    """旧产物缺 decision_path：_conflict_rows 不得抛。"""
    d = _dossier_two_sides(tmp_path / "f_src")
    for pair in d.conflicts:
        res = pair.get("resolution") or {}
        res.pop("decision_path", None)
        # 也清 restart，模拟旧形态
        res.pop("restart_condition", None)
        res.pop("重启条件", None)
        pair["resolution"] = res
    rows, _ = _conflict_rows("q1", d)
    assert len(rows) == 1
    assert "冲突清单" in rows[0]
    assert "结果" in rows[0]
    # 缺重启条件 → omissions 含标注，值空串
    assert rows[0]["重启条件"] == ""
    assert "重启条件" in rows[0]["omissions"]


def test_f_generality_over_inrepo_reports_if_present(tmp_path):
    """本机若有 cases/*/out*/report.json，抽样导出也必须出两字段。
    无产物则用合成旧形态 dossier（缺 decision_path）走同一导出路径——
    不把绿建立在未入库产物上，也不引入 pytest.skip（免碰 c37 skip 登记闸）。"""
    root = Path(__file__).resolve().parents[1] / "cases"
    reports = sorted(root.glob("*/out*/report.json"))[:3]
    runs = []
    for rp in reports:
        data = json.loads(rp.read_text(encoding="utf-8"))
        for pair in data.get("conflicts") or []:
            if isinstance(pair, dict) and isinstance(pair.get("resolution"), dict):
                pair["resolution"].pop("decision_path", None)
        qid = rp.parent.name
        runs.append(({"question_id": qid, "question": str(data.get("question") or "")},
                      Dossier.from_dict(data)))
    runs = [(q, d) for q, d in runs if d.conflicts]
    if not runs:
        # 合成旧形态：缺 decision_path，仍须出两字段、不抛
        d = _dossier_two_sides(tmp_path / "f_syn")
        for pair in d.conflicts:
            res = pair.get("resolution") or {}
            res.pop("decision_path", None)
            res.pop("restart_condition", None)
            res.pop("重启条件", None)
            pair["resolution"] = res
        runs = [(_q("q-syn"), d)]
    paths = export_official(runs, tmp_path / "f_gen")
    recs = _records(paths)
    assert recs, "有冲突应出记录"
    for rec in recs:
        assert "冲突清单" in rec
        assert "结果" in rec
        assert rec["结果"]["outcome"] in ("甲胜", "乙胜", "并存不裁决")


# ---------- g：条数账由 writeback 报；本文件 collect 可数 ----------

def test_g_field_notes_document_both_keys():
    """禁止项⑤：字段说明同笔更新两键。"""
    assert "冲突清单" in _FIELD_NOTES
    assert "结果（C-46）" in _FIELD_NOTES or (
        "结果" in _FIELD_NOTES and "并存不裁决" in _FIELD_NOTES
    )
    assert "甲胜" in _FIELD_NOTES and "乙胜" in _FIELD_NOTES
    assert "并存不裁决" in _FIELD_NOTES
    assert "800" in _FIELD_NOTES


# ---------- h：≤800 字；超限截断 + omissions ----------

def test_h_record_within_800_chars(tmp_path):
    d = _dossier_two_sides(tmp_path / "h_src")
    paths = export_official([(_q(), d)], tmp_path / "h_out")
    for rec in _records(paths):
        n = len(json.dumps(rec, ensure_ascii=False))
        assert n <= _C46_RECORD_MAX, f"单条 {n} > {_C46_RECORD_MAX}"


def test_h_oversize_truncated_and_omission_flagged(tmp_path):
    """把 rationale／statement 撑爆 ⇒ 截断且 omissions 含标注。"""
    d = _dossier_two_sides(tmp_path / "h_big")
    for con in d.conclusions:
        con.statement = ("论述" * 80) + con.statement
    for pair in d.conflicts:
        pair["resolution"]["rationale"] = "理由" * 500
        pair["resolution"]["basis"] = {
            "type_applies": True,
            "loser_excluded": True,
            "strength": {"CON-A": 0.9, "CON-B": 0.1},
            "pad": "垫" * 200,
        }
    rows, _ = _conflict_rows("q1", d)
    assert rows
    raw = json.dumps(rows[0], ensure_ascii=False)
    assert len(raw) <= _C46_RECORD_MAX
    assert _C46_SIZE_OMISSION in rows[0]["omissions"]


# ---------- 辅助：truncate / result 纯函数 ----------

def test_truncate_helper_marks_inside():
    s = "字" * 150
    out = _c46_truncate_statement(s)
    assert len(out) <= _C46_STMT_MAX
    assert out.endswith(_C46_TRUNC_MARK)
    assert s.startswith(out[: -len(_C46_TRUNC_MARK)])


def test_result_empty_winner_is_tie():
    pair = {"a_id": "A", "b_id": "B"}
    assert _c46_result_of(pair, {"winner_id": ""}) == {
        "outcome": "并存不裁决", "winner_id": "", "tie": True,
    }
    assert _c46_result_of(pair, {"winner_id": "tie"})["outcome"] == "并存不裁决"
    assert _c46_result_of(pair, {"winner_id": "A"})["outcome"] == "甲胜"
    assert _c46_result_of(pair, {"winner_id": "B"})["outcome"] == "乙胜"
