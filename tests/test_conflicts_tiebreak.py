"""C-14：票数只在强度差 ≤0.20 时破平，消解记录带可核验 basis。"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.confidence import evidence_strength_of
from app.core.conflicts import (
    METHOD_TO_RESOLUTION_TYPE,
    RESOLUTION_METHODS,
    ConflictPair,
    Resolution,
    _OFFICIAL_RESOLUTION_TYPES,
    apply_resolution,
    independent_source_count,
    prefer_stronger_side,
    reopen_when_for,
)
from app.core.dup_check import near_dup_pairs
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    Segment,
    Source,
    SourceType,
)


def _side(dossier: Dossier, cid: str, statement: str,
          pieces: list[tuple[str, str, EvidenceLevel]],
          credibility: float = 0.8) -> None:
    dossier.conclusions.append(Conclusion.create(statement, author="a", id=cid))
    for i, (sid, text, level) in enumerate(pieces):
        src = Source.create(sid, SourceType.REPORT, credibility=credibility, id=sid)
        src.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text))
        dossier.add_source(src)
        dossier.add_evidence(EvidenceNode.create(
            cid, text, [f"{sid}#s1"], level=level, id=f"EV-{cid}-{i}"))


def _pair(a_id: str = "CON-A", b_id: str = "CON-B") -> ConflictPair:
    return ConflictPair(id="CFL-1", a_id=a_id, b_id=b_id, topic="t")


def test_a_strength_gap_ignores_more_sources():
    """a) 强度差 > 0.20 时，更多独立信源不能翻案。"""
    d = Dossier(question="Q")
    _side(d, "CON-A", "甲", [("S-A", "甲方唯一的一手实测记录写在这里。", EvidenceLevel.A)], 0.9)
    _side(d, "CON-B", "乙", [
        (f"S-B{i}", f"乙方第{i}份低可信转述，内容彼此不同且足够长。", EvidenceLevel.D)
        for i in range(5)
    ], 0.9)
    out = prefer_stronger_side(
        _pair(), d, Resolution(winner_id="CON-B", rationale="票多"))
    assert out.winner_id == "CON-A"
    assert out.decision_path == "strength"
    assert out.basis["independent_sources"]["CON-B"] > out.basis["independent_sources"]["CON-A"]
    assert out.basis["decision_path"] == "strength"


def test_b_close_strength_breaks_by_source_count():
    """b) 强度差 ≤ 0.20 时，独立信源多的一方胜。"""
    d = Dossier(question="Q")
    _side(d, "CON-A", "甲", [("S-A", "甲方只有这一份独立记录。", EvidenceLevel.C)])
    _side(d, "CON-B", "乙", [
        ("S-B0", "乙方第一份独立记录，讲的是产线。", EvidenceLevel.C),
        ("S-B1", "乙方第二份独立记录，讲的是良率。", EvidenceLevel.C),
        ("S-B2", "乙方第三份独立记录，讲的是订单。", EvidenceLevel.C),
    ])
    out = prefer_stronger_side(
        _pair(), d, Resolution(winner_id="CON-A", rationale="仲裁"))
    assert out.winner_id == "CON-B"
    assert out.method == "source_majority"
    assert out.resolution_type == "多数投票"


def test_c_equal_sources_tie_is_order_independent():
    """c) 独立信源数相同则 tie，对调构造顺序也不改胜负。"""
    def build(first_b: bool) -> Resolution:
        d = Dossier(question="Q")
        a_pieces = [
            ("S-A0", "甲方记录一，主题是能量密度。", EvidenceLevel.C),
            ("S-A1", "甲方记录二，主题是循环寿命。", EvidenceLevel.C),
        ]
        b_pieces = [
            ("S-B0", "乙方记录一，主题是停工传闻。", EvidenceLevel.C),
            ("S-B1", "乙方记录二，主题是资金链。", EvidenceLevel.C),
        ]
        if first_b:
            _side(d, "CON-B", "乙", b_pieces)
            _side(d, "CON-A", "甲", a_pieces)
        else:
            _side(d, "CON-A", "甲", a_pieces)
            _side(d, "CON-B", "乙", b_pieces)
        return prefer_stronger_side(
            _pair(), d, Resolution(winner_id="CON-A", rationale="先写的一方"))

    left = build(False)
    right = build(True)
    assert left.winner_id == "tie"
    assert right.winner_id == "tie"
    assert left.winner_id == right.winner_id


def test_d_near_dup_collapses_to_two_sources():
    """d) 归一化后相同的两份信源只算一件。"""
    base = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉"
    d = Dossier(question="Q")
    _side(d, "CON-A", "甲", [
        ("S0", "这是一份完全不同的第三方调查记录正文。", EvidenceLevel.C),
        ("S1", base, EvidenceLevel.C),
        ("S2", base + " ", EvidenceLevel.C),
    ])
    pairs = near_dup_pairs(d)
    assert any({a, b} == {"S1", "S2"} for a, b, _jac in pairs)
    assert independent_source_count("CON-A", d) == 2


def test_e_method_map_is_exhaustive_and_unique():
    """e) 映射表键集等于 method 取值集，导出层没有第二份表。"""
    assert set(METHOD_TO_RESOLUTION_TYPE) == set(RESOLUTION_METHODS)
    for method in RESOLUTION_METHODS:
        assert METHOD_TO_RESOLUTION_TYPE[method] in _OFFICIAL_RESOLUTION_TYPES
    src = Path("app/export/official.py").read_text(encoding="utf-8")
    assert "METHOD_TO_RESOLUTION_TYPE =" not in src
    assert '"evidence_weight"' not in src


def test_f_reopen_when_differs_by_path():
    """f) 三条路径的重启条件互不相同且非空，并写入 dissent。"""
    texts = [reopen_when_for(p) for p in ("strength", "source_majority", "tie")]
    assert all(texts)
    assert len(set(texts)) == 3

    d = Dossier(question="Q")
    _side(d, "CON-A", "甲", [("S-A", "甲方唯一的一手实测记录写在这里。", EvidenceLevel.A)], 0.9)
    _side(d, "CON-B", "乙", [("S-B", "乙方的一条低可信转述写在这里。", EvidenceLevel.D)], 0.9)
    pair = _pair()
    pair.resolution = prefer_stronger_side(
        pair, d, Resolution(winner_id="CON-B", rationale="票多"))
    assert pair.resolution.decision_path == "strength"
    assert apply_resolution(pair, d) is None
    dissent = d.conclusion("CON-A").dissent
    assert dissent and dissent[0]["reopen_when"] == reopen_when_for("strength")

    d2 = Dossier(question="Q")
    _side(d2, "CON-A", "甲", [("S-A", "甲方只有这一份独立记录。", EvidenceLevel.C)])
    _side(d2, "CON-B", "乙", [
        ("S-B0", "乙方第一份独立记录，讲的是产线。", EvidenceLevel.C),
        ("S-B1", "乙方第二份独立记录，讲的是良率。", EvidenceLevel.C),
        ("S-B2", "乙方第三份独立记录，讲的是订单。", EvidenceLevel.C),
    ])
    pair2 = _pair()
    pair2.resolution = prefer_stronger_side(
        pair2, d2, Resolution(winner_id="CON-A", rationale="仲裁"))
    assert pair2.resolution.decision_path == "source_majority"
    assert apply_resolution(pair2, d2) is None
    assert d2.conclusion("CON-B").dissent[0]["reopen_when"] == reopen_when_for(
        "source_majority")

    d3 = Dossier(question="Q")
    _side(d3, "CON-A", "甲", [("S-A", "甲方记录。", EvidenceLevel.C)])
    _side(d3, "CON-B", "乙", [("S-B", "乙方记录完全不同。", EvidenceLevel.C)])
    pair3 = _pair()
    pair3.resolution = prefer_stronger_side(
        pair3, d3, Resolution(winner_id="tie", method="tie", rationale="打平"))
    assert pair3.resolution.to_dict()["重启条件"] == reopen_when_for("tie")


def test_g_above_margin_keeps_winner_method_rationale():
    """g) 强度差 > 0.20 时 winner / method / rationale 与改前逐字相同。"""
    d = Dossier(question="Q")
    _side(d, "CON-0", "甲", [("S0", "甲方强证据。", EvidenceLevel.A)])
    _side(d, "CON-1", "乙", [
        (f"S{i}", f"乙方弱证据第{i}份，彼此不同。", EvidenceLevel.D) for i in range(1, 6)
    ])
    pair = ConflictPair(a_id="CON-0", b_id="CON-1")
    out = prefer_stronger_side(pair, d, Resolution(
        winner_id="CON-1", rationale="票多",
        evidence_weight={"CON-0": 0.68, "CON-1": 0.12}))
    assert out.winner_id == "CON-0"
    assert out.method == "evidence_weight"
    assert out.rationale == (
        "程序按证据强度否决票数：CON-0=0.68 > CON-1=0.12"
        "（多数派引用不能压过更高强度证据）。 原仲裁：票多"
    )
    held = prefer_stronger_side(pair, d, Resolution(
        winner_id="CON-0", rationale="原文",
        evidence_weight={"CON-0": 0.50, "CON-1": 0.29}))
    assert held.winner_id == "CON-0"
    assert held.method == "arbitration"
    assert held.rationale == "原文"
    assert held.decision_path == "strength"
    tied = prefer_stronger_side(pair, d, Resolution(
        winner_id="tie", method="tie", rationale="维持"))
    assert tied.winner_id == "tie"
    assert tied.method == "tie"
    assert tied.rationale == "维持"


def _flat_numbers(value) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        out: list[float] = []
        for item in value.values():
            out.extend(_flat_numbers(item))
        return out
    return []


def test_h_basis_matches_direct_calls_and_sentences():
    """h) basis 数值等于直接调用，两句里的数字能在 basis 里找到。"""
    d = Dossier(question="Q")
    _side(d, "CON-A", "甲", [("S-A", "甲方只有这一份独立记录。", EvidenceLevel.C)])
    _side(d, "CON-B", "乙", [
        ("S-B0", "乙方第一份独立记录，讲的是产线。", EvidenceLevel.C),
        ("S-B1", "乙方第二份独立记录，讲的是良率。", EvidenceLevel.C),
        ("S-B2", "乙方第三份独立记录，讲的是订单。", EvidenceLevel.C),
    ])
    out = prefer_stronger_side(
        _pair(), d, Resolution(winner_id="CON-A", rationale="仲裁"))
    basis = out.basis
    assert basis["strength"]["CON-A"] == evidence_strength_of("CON-A", d)
    assert basis["strength"]["CON-B"] == evidence_strength_of("CON-B", d)
    assert basis["independent_sources"]["CON-A"] == independent_source_count("CON-A", d)
    assert basis["independent_sources"]["CON-B"] == independent_source_count("CON-B", d)
    pool = _flat_numbers(basis)
    for sentence in (basis["type_applies"], basis["loser_excluded"]):
        assert sentence
        for raw in re.findall(r"\d+(?:\.\d+)?", sentence):
            shown = float(raw)
            assert any(abs(shown - item) <= 5e-4 for item in pool)


def test_i_old_resolution_dict_loads():
    """i) 旧报告没有 basis / resolution_type 时仍能加载。"""
    old = {
        "winner_id": "CON-0",
        "method": "arbitration",
        "rationale": "x",
        "evidence_weight": {"CON-0": 0.5},
        "rebuts": {},
    }
    loaded = Resolution.from_dict(old)
    assert loaded.basis == {}
    assert loaded.resolution_type == ""
    assert loaded.decision_path == ""
    assert loaded.winner_id == "CON-0"
    assert loaded.rationale == "x"
