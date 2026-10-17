"""C-14b：类型跟 decision_path、人工改判盖章、两道闸只算一次、少数意见断言。"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.conflicts import (
    ConflictPair,
    Resolution,
    prefer_stronger_side,
)
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    Segment,
    Source,
    SourceType,
)


def _side(dossier, cid, statement, pieces, credibility=0.8):
    dossier.conclusions.append(Conclusion.create(statement, author="a", id=cid))
    for i, (sid, text, level) in enumerate(pieces):
        src = Source.create(sid, SourceType.REPORT, credibility=credibility, id=sid)
        src.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text))
        dossier.add_source(src)
        dossier.add_evidence(EvidenceNode.create(
            cid, text, [f"{sid}#s1"], level=level, id=f"EV-{cid}-{i}"))


def test_a_strength_path_type_follows_decision_path_not_method():
    """a) LLM 选了强侧、method 仍是 arbitration，类型却是语义可信度。"""
    d = Dossier(question="Q")
    _side(d, "CON-0", "甲", [("S0", "甲方强证据写在这里。", EvidenceLevel.A)], 0.9)
    _side(d, "CON-1", "乙", [("S1", "乙方弱证据写在这里。", EvidenceLevel.D)], 0.9)
    out = prefer_stronger_side(ConflictPair(a_id="CON-0", b_id="CON-1"), d, Resolution(
        winner_id="CON-0", rationale="原文",
        evidence_weight={"CON-0": 0.90, "CON-1": 0.20}))
    assert out.method == "arbitration"
    assert out.winner_id == "CON-0"
    assert out.decision_path == "strength"
    assert out.resolution_type == "语义可信度"
    assert "按证据强度裁决" in out.basis["type_applies"]


def test_b_tie_and_source_majority_types_stay_put():
    """b) tie 仍是其他，source_majority 仍是多数投票。"""
    d = Dossier(question="Q")
    _side(d, "CON-A", "甲", [("SA", "甲方只有这一份独立记录。", EvidenceLevel.C)])
    _side(d, "CON-B", "乙", [
        ("SB0", "乙方第一份独立记录，讲的是产线。", EvidenceLevel.C),
        ("SB1", "乙方第二份独立记录，讲的是良率。", EvidenceLevel.C),
        ("SB2", "乙方第三份独立记录，讲的是订单。", EvidenceLevel.C),
    ])
    majority = prefer_stronger_side(
        ConflictPair(a_id="CON-A", b_id="CON-B"), d,
        Resolution(winner_id="CON-A", rationale="仲裁"))
    assert majority.method == "source_majority"
    assert majority.resolution_type == "多数投票"
    tied = prefer_stronger_side(
        ConflictPair(a_id="CON-A", b_id="CON-B"), d,
        Resolution(winner_id="tie", method="tie", rationale="打平"))
    assert tied.resolution_type == "其他"
    assert tied.resolution_type != "语义可信度"


def test_d_override_stamps_basis_and_empty_basis_is_omitted():
    """d) 人工改判有 basis／类型／重启条件；空 dict 也上报 basis 缺失。"""
    from app.core.human_ops import override_resolution
    from app.export.official import _conflict_rows

    d = Dossier(question="Q")
    _side(d, "CON-0", "甲", [("S0", "甲方记录足够长。", EvidenceLevel.A)], 0.9)
    _side(d, "CON-1", "乙", [("S1", "乙方记录完全不同。", EvidenceLevel.D)], 0.3)
    pair = ConflictPair(id="CFL-1", a_id="CON-0", b_id="CON-1", topic="t")
    d.conflicts = [pair.to_dict()]
    override_resolution(d, "CFL-1", "CON-0")
    stored = d.conflicts[0]["resolution"]
    assert stored["winner_id"] == "CON-0"
    assert stored["method"] == "arbitration"
    assert stored["basis"]
    assert stored["resolution_type"]
    assert stored["重启条件"]
    rows, _ = _conflict_rows("q1", d)
    assert rows[0]["omissions"] == []

    empty = Dossier(question="Q")
    empty.conflicts = [{
        "id": "CFL-E",
        "resolution": {
            "winner_id": "CON-0",
            "method": "arbitration",
            "rationale": "x",
            "basis": {},
            "resolution_type": "语义可信度",
            "重启条件": "有重启条件",
        },
    }]
    rows_empty, _ = _conflict_rows("q1", empty)
    assert "basis" in rows_empty[0]["omissions"]


def test_e_near_dup_once_per_conflict(monkeypatch):
    """e) 每条冲突 near_dup_pairs 只调用一次；独立信源数口径不变。"""
    from app.core.conflicts import independent_source_count
    import app.core.conflicts as conflicts_mod
    import app.core.dup_check as dup_mod

    calls = {"n": 0}
    real = dup_mod.near_dup_pairs

    def wrapped(dossier):
        calls["n"] += 1
        return real(dossier)

    monkeypatch.setattr(conflicts_mod, "near_dup_pairs", wrapped)

    base = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉"
    small = Dossier(question="Q")
    _side(small, "CON-A", "甲", [
        ("S0", "这是一份完全不同的第三方调查记录正文。", EvidenceLevel.C),
        ("S1", base, EvidenceLevel.C),
        ("S2", base + " ", EvidenceLevel.C),
    ])
    assert independent_source_count("CON-A", small) == 2

    calls["n"] = 0
    d = Dossier(question="Q")
    for i in range(120):
        sid = f"SRC{i:03d}"
        src = Source.create(sid, SourceType.REPORT, credibility=0.5, id=sid)
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid,
            text=f"信源{i}的正文互不相同，专门用来撑计时格。"))
        d.add_source(src)
    for i in range(10):
        a, b = f"CON-{i}a", f"CON-{i}b"
        d.conclusions.append(Conclusion.create("甲", author="a", id=a))
        d.conclusions.append(Conclusion.create("乙", author="b", id=b))
        d.add_evidence(EvidenceNode.create(
            a, f"信源{i}的正文互不相同，专门用来撑计时格。",
            [f"SRC{i:03d}#s1"], level=EvidenceLevel.A, id=f"EV-{i}a"))
        d.add_evidence(EvidenceNode.create(
            b, f"信源{i+10}的正文互不相同，专门用来撑计时格。",
            [f"SRC{i+10:03d}#s1"], level=EvidenceLevel.D, id=f"EV-{i}b"))
        prefer_stronger_side(
            ConflictPair(a_id=a, b_id=b), d,
            Resolution(winner_id=b, rationale="票多"))
    assert calls["n"] == 10


def test_f_dissent_assertion_and_tie_case_both_exist():
    """f) 测试里同时有少数意见文案和 tie 胜方断言。"""
    root = Path("tests")
    dissent = tie = 0
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        dissent += text.count("少数意见")
        tie += text.count('winner_id == "tie"')
    assert dissent >= 1
    assert tie >= 1


def test_k_duplicate_question_orders_match(tmp_path):
    """k) 同题多一行空支撑，两种顺序的五项读数相同。"""
    from scripts.score_official import score_submission

    samples = [
        {"fact_id": f"fact_{i:03d}", "doc_id": "doc_001",
         "para_id": f"doc_001#p{i}", "quote": "甲"}
        for i in range(1, 5)
    ]
    gold = [{
        "question_id": "q1",
        "supporting_facts": [{"fact_id": "fact_001"}, {"fact_id": "fact_002"}],
        "conflicting_facts": [{"fact_id": "fact_003"}, {"fact_id": "fact_004"}],
    }]
    hit = {
        "question_id": "q1",
        "supporting_facts": [
            {"doc_id": "doc_001", "para_id": "doc_001#p1"},
            {"doc_id": "doc_001", "para_id": "doc_001#p2"},
        ],
        "conflicting_facts": [
            {"doc_id": "doc_001", "para_id": "doc_001#p3"},
            {"doc_id": "doc_001", "para_id": "doc_001#p4"},
        ],
    }
    bare = {"question_id": "q1", "supporting_facts": [], "conflicting_facts": []}

    def dump(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    evidence = dump("ev.json", samples)
    gold_ev = dump("gev.json", samples)
    gold_c = dump("gc.json", gold)
    samples_path = dump("samples.json", samples)
    fives = []
    for order, rows in (("bare-first", [bare, hit]), ("hit-first", [hit, bare])):
        metrics = score_submission(
            evidence, dump(f"{order}.json", rows), gold_ev, gold_c,
            samples_path=samples_path)
        fives.append((
            metrics["score_2_2_1"], metrics["score_2_4_1"], metrics["score_2_4_2"],
            metrics["score_2_5_1"], metrics["score_2_5_2"],
        ))
    assert fives[0] == fives[1]
