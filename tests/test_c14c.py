"""C-14c：人工改判不再声称按强度裁决；规则只留一份。"""

from __future__ import annotations

import re

from app.core.conflicts import (
    ConflictPair,
    Resolution,
    mechanical_decision_path,
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


def _ab_fixture():
    """甲 1×A、乙 2×D，可信度同 0.5 → 强度 0.5000 vs 0.1500。"""
    d = Dossier(question="Q")
    _side(d, "CON-0", "甲", [
        ("S0", "甲方强证据写在这里足够长。", EvidenceLevel.A)], 0.5)
    _side(d, "CON-1", "乙", [
        ("S1", "乙方弱证据第一份写在这里。", EvidenceLevel.D),
        ("S2", "乙方弱证据第二份写在这里。", EvidenceLevel.D),
    ], 0.5)
    return d


def _assert_no_reversed_strength_claim(basis: dict) -> None:
    """从文案里取出两个数，与 basis.strength 真实大小关系对账。"""
    strength = basis.get("strength") or {}
    texts = [
        str(basis.get("type_applies") or ""),
        str(basis.get("loser_excluded") or ""),
    ]
    joined = "／".join(texts)
    nums = [float(x) for x in re.findall(r"\d+\.\d+", joined)]
    if len(nums) < 2:
        return
    # 文案里若出现「A ＜ B」形状，则必须 A < B 在 strength 里也成立。
    for text in texts:
        for m in re.finditer(
            r"(\d+\.\d+)\s*[＜<]\s*(\d+\.\d+)", text
        ):
            left, right = float(m.group(1)), float(m.group(2))
            assert left < right, f"文案假不等式：{text}"
            # 与 strength 字典对账：left 必须真的小于 right 所对应的两侧值关系
            vals = sorted(float(v) for v in strength.values())
            assert abs(left - vals[0]) < 1e-9 or left in strength.values()
            assert abs(right - vals[-1]) < 1e-9 or right in strength.values()
            real_left_is_smaller = True
            for a, b in ((left, right),):
                # 若 left 是败方、right 是胜方，真实 strength 里 left 对应的 id 必须更弱
                id_for = {float(v): k for k, v in strength.items()}
                # 浮点键可能对不上，改成按值匹配
                left_ids = [k for k, v in strength.items() if abs(float(v) - left) < 1e-9]
                right_ids = [k for k, v in strength.items() if abs(float(v) - right) < 1e-9]
                if left_ids and right_ids:
                    assert float(strength[left_ids[0]]) < float(strength[right_ids[0]])


def test_a_override_to_weaker_side_has_no_reversed_inequality():
    """a) 人改到弱侧：文案不得与 strength 大小关系相反。"""
    from app.core.human_ops import override_resolution

    d = _ab_fixture()
    prefer_stronger_side(
        ConflictPair(a_id="CON-0", b_id="CON-1"), d,
        Resolution(winner_id="CON-0", rationale="机械先走"))
    pair = ConflictPair(id="CFL-1", a_id="CON-0", b_id="CON-1", topic="t")
    d.conflicts = [pair.to_dict()]
    override_resolution(d, "CFL-1", "CON-1")
    basis = d.conflicts[0]["resolution"]["basis"]
    _assert_no_reversed_strength_claim(basis)
    assert "＜" not in basis["loser_excluded"]
    assert "<" not in basis["loser_excluded"]


def test_b_machine_path_strength_wording_unchanged():
    """b) 机器路径仍是 strength／语义可信度／0.1500 ＜ 0.5000。"""
    d = _ab_fixture()
    out = prefer_stronger_side(
        ConflictPair(a_id="CON-0", b_id="CON-1"), d,
        Resolution(winner_id="CON-0", rationale="原文"))
    assert out.decision_path == "strength"
    assert out.resolution_type == "语义可信度"
    assert out.basis["loser_excluded"] == "败方强度 0.1500 ＜ 胜方 0.5000"

    # 人改到强侧不得顺手改掉机器路径的实现：再跑一遍 prefer 仍逐字相同。
    from app.core.human_ops import override_resolution
    pair = ConflictPair(id="CFL-1", a_id="CON-0", b_id="CON-1", topic="t")
    d2 = _ab_fixture()
    d2.conflicts = [pair.to_dict()]
    override_resolution(d2, "CFL-1", "CON-0")
    again = prefer_stronger_side(
        ConflictPair(a_id="CON-0", b_id="CON-1"), _ab_fixture(),
        Resolution(winner_id="CON-0", rationale="原文"))
    assert again.basis["loser_excluded"] == "败方强度 0.1500 ＜ 胜方 0.5000"


def test_c_override_exports_human_override_shape():
    """c) 人工改判：路径／类型／说理／omissions 形状钉死。"""
    from app.core.human_ops import override_resolution
    from app.export.official import _conflict_rows

    d = _ab_fixture()
    pair = ConflictPair(id="CFL-1", a_id="CON-0", b_id="CON-1", topic="t")
    d.conflicts = [pair.to_dict()]
    override_resolution(d, "CFL-1", "CON-1")
    stored = d.conflicts[0]["resolution"]
    assert stored["decision_path"] == "human_override"
    assert stored["resolution_type"] == "其他"
    applies = stored["basis"]["type_applies"]
    assert applies.startswith("人工改判")
    assert "strength" in applies or "source_majority" in applies or "tie" in applies
    assert re.search(r"\d+\.\d+", applies)
    assert "＜" not in stored["basis"]["loser_excluded"]
    assert "<" not in stored["basis"]["loser_excluded"]
    assert stored["重启条件"] == "若人工撤销改判则恢复机械路径"
    rows, _ = _conflict_rows("q1", d)
    assert "人工改判" in rows[0]["omissions"]


def test_d_prefer_and_mechanical_paths_agree_and_rule_is_shared():
    """d) 两路径 decision_path 逐字相同；w_lose > w_win 只剩 1 处。"""
    from pathlib import Path

    src = Path("app/core/conflicts.py").read_text(encoding="utf-8")
    assert src.count("w_lose > w_win") == 1

    cases = []

    # strength：甲强乙弱
    d1 = _ab_fixture()
    pair1 = ConflictPair(a_id="CON-0", b_id="CON-1")
    out1 = prefer_stronger_side(
        pair1, d1, Resolution(winner_id="CON-0", rationale="原文"))
    mech1 = mechanical_decision_path(pair1, d1, out1)
    cases.append(("strength", out1.decision_path, mech1))

    # source_majority：势均力敌，乙信源多
    d2 = Dossier(question="Q")
    _side(d2, "CON-A", "甲", [("SA", "甲方只有这一份独立记录。", EvidenceLevel.C)])
    _side(d2, "CON-B", "乙", [
        ("SB0", "乙方第一份独立记录，讲的是产线。", EvidenceLevel.C),
        ("SB1", "乙方第二份独立记录，讲的是良率。", EvidenceLevel.C),
        ("SB2", "乙方第三份独立记录，讲的是订单。", EvidenceLevel.C),
    ])
    pair2 = ConflictPair(a_id="CON-A", b_id="CON-B")
    out2 = prefer_stronger_side(
        pair2, d2, Resolution(winner_id="CON-A", rationale="仲裁"))
    mech2 = mechanical_decision_path(pair2, d2, out2)
    cases.append(("source_majority", out2.decision_path, mech2))

    # tie：双方势均且信源数相同
    d3 = Dossier(question="Q")
    _side(d3, "CON-A", "甲", [("SA", "甲方记录。", EvidenceLevel.C)])
    _side(d3, "CON-B", "乙", [("SB", "乙方记录完全不同。", EvidenceLevel.C)])
    pair3 = ConflictPair(a_id="CON-A", b_id="CON-B")
    out3 = prefer_stronger_side(
        pair3, d3, Resolution(winner_id="tie", method="tie", rationale="打平"))
    mech3 = mechanical_decision_path(pair3, d3, out3)
    cases.append(("tie", out3.decision_path, mech3))

    # llm_arbitration：winner 非法字符串走兜底
    d4 = _ab_fixture()
    pair4 = ConflictPair(a_id="CON-0", b_id="CON-1")
    res4 = Resolution(winner_id="not-a-side", rationale="乱")
    out4 = prefer_stronger_side(pair4, d4, res4)
    mech4 = mechanical_decision_path(pair4, d4, out4)
    cases.append(("llm_arbitration", out4.decision_path, mech4))

    seen = {name for name, pref, mech in cases}
    assert seen >= {"strength", "source_majority", "tie", "llm_arbitration"}
    for name, pref, mech in cases:
        assert pref == mech == name, (name, pref, mech)


def test_d_shared_rule_mutation_would_diverge(monkeypatch):
    """d 反向：把 mechanical 改成恒真 strength ⇒ 与 prefer 当场分叉。"""
    import app.core.conflicts as mod

    real = mod.mechanical_decision_path

    def always_strength(pair, dossier, resolution, exact=None, pairs=None):
        if resolution.winner_id == "tie":
            return "tie"
        return "strength"

    monkeypatch.setattr(mod, "mechanical_decision_path", always_strength)
    d = Dossier(question="Q")
    _side(d, "CON-A", "甲", [("SA", "甲方只有这一份独立记录。", EvidenceLevel.C)])
    _side(d, "CON-B", "乙", [
        ("SB0", "乙方第一份独立记录，讲的是产线。", EvidenceLevel.C),
        ("SB1", "乙方第二份独立记录，讲的是良率。", EvidenceLevel.C),
        ("SB2", "乙方第三份独立记录，讲的是订单。", EvidenceLevel.C),
    ])
    pair = ConflictPair(a_id="CON-A", b_id="CON-B")
    out = prefer_stronger_side(
        pair, d, Resolution(winner_id="CON-A", rationale="仲裁"))
    # prefer 仍走 source_majority；变异后的 mechanical 恒 strength
    assert out.decision_path == "source_majority"
    assert mod.mechanical_decision_path(pair, d, out) == "strength"
    assert out.decision_path != mod.mechanical_decision_path(pair, d, out)
    monkeypatch.setattr(mod, "mechanical_decision_path", real)


def test_strength_false_inequality_is_intercepted():
    """strength 模板：数值关系不成立时落中性句并记 omissions。"""
    from app.core.conflicts import _stamp

    d = _ab_fixture()
    pair = ConflictPair(a_id="CON-0", b_id="CON-1")
    # 人为把弱侧写成胜方，却仍走 strength 盖章——自检必须拦住假不等式。
    res = Resolution(winner_id="CON-1", method="arbitration", rationale="错盖")
    _stamp(res, pair, d, "strength")
    assert "＜" not in res.basis["loser_excluded"]
    assert "<" not in res.basis["loser_excluded"]
    assert "假不等式已拦截" in res.omissions
    _assert_no_reversed_strength_claim(res.basis)


def _dissent_section_lines(md: str) -> list[str]:
    """只取「## 少数意见（依规保留）」那一节，避免撞上冲突消解区的同句。"""
    lines = md.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## 少数意见（依规保留）"):
            start = i
            break
    assert start is not None, "报告缺少数意见节"
    out = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def test_human_override_dissent_line_in_report():
    """少数意见节内败方那一行必须是新串，且不含旧串。"""
    from app.core.hashchain import HashChain
    from app.core.human_ops import override_resolution
    from app.pipeline import render_report_md

    d = _ab_fixture()
    pair = ConflictPair(id="CFL-1", a_id="CON-0", b_id="CON-1", topic="t")
    d.conflicts = [pair.to_dict()]
    override_resolution(d, "CFL-1", "CON-1")
    md = render_report_md(d, HashChain(), [])
    section = _dissent_section_lines(md)
    loser_lines = [ln for ln in section if ln.startswith("- 「甲」")]
    assert len(loser_lines) == 1, section
    line = loser_lines[0]
    assert "人工改判后未采信（原机械判断：" in line
    assert "经仲裁证据加权后列为少数意见" not in line


def test_margin_keeps_near_miss_from_strength_flip():
    """败方强度落在 (胜方, 胜方+margin] 内：不按强度翻盘，也不写 strength。"""
    from app.core.conflicts import _WEIGHT_MARGIN

    d = Dossier(question="Q")
    _side(d, "CON-A", "甲", [("SA", "甲方只有这一份独立记录。", EvidenceLevel.C)])
    _side(d, "CON-B", "乙", [("SB", "乙方记录完全不同。", EvidenceLevel.C)])
    w_win, w_lose = 0.40, 0.50
    assert w_win < w_lose <= w_win + _WEIGHT_MARGIN
    res = Resolution(
        winner_id="CON-A", rationale="票多",
        evidence_weight={"CON-A": w_win, "CON-B": w_lose})
    pair = ConflictPair(a_id="CON-A", b_id="CON-B")
    assert mechanical_decision_path(pair, d, res) != "strength"
    out = prefer_stronger_side(pair, d, res)
    assert out.method != "evidence_weight"
    assert out.decision_path != "strength"
    assert out.winner_id != "CON-B"


def test_resolution_omissions_survive_from_dict_roundtrip():
    """to_dict → from_dict → to_dict：omissions／路径／mechanical_path 逐字保留。"""
    from app.core.human_ops import override_resolution

    d = _ab_fixture()
    pair = ConflictPair(id="CFL-1", a_id="CON-0", b_id="CON-1", topic="t")
    d.conflicts = [pair.to_dict()]
    override_resolution(d, "CFL-1", "CON-1")
    raw = d.conflicts[0]["resolution"]
    again = Resolution.from_dict(raw).to_dict()
    assert again["omissions"] == raw["omissions"]
    assert again["decision_path"] == raw["decision_path"] == "human_override"
    assert again["basis"]["mechanical_path"] == raw["basis"]["mechanical_path"]
    assert again["omissions"]
    assert again["basis"]["mechanical_path"]
