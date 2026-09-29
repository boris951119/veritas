"""契约 C：人机闭环 human_ops（改结论 / 推翻裁决 / 重开冲突）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.arbiter import Coordinator
from app.core.conflicts import ConflictPair, Resolution, apply_resolution
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceNode,
    Segment,
    Source,
    SourceType,
)


class ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, model, messages, json_mode=False):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(content=item)


def _dossier_pair() -> Dossier:
    d = Dossier(question="Q", panel=["a0", "a1"])
    src = Source.create("T", SourceType.PAPER, credibility=0.8, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="全固态电芯的中试良率尚不足百分之四十。",
        locator="段 1"))
    d.add_source(src)
    for i, stmt in enumerate(("结论甲", "结论乙")):
        con = Conclusion.create(stmt, author=f"a{i}", id=f"CON-{i}")
        d.conclusions.append(con)
        d.add_evidence(EvidenceNode.create(
            f"CON-{i}", "全固态电芯的中试良率尚不足百分之四十",
            ["SRC1#s1"], id=f"EV-{i}"))
    return d


def test_edit_conclusion_updates_statement():
    """深化后：edit_conclusion 改写结论文案。"""
    from app.core.human_ops import edit_conclusion

    d = _dossier_pair()
    edit_conclusion(d, "CON-0", "人工修订后的甲")
    assert d.conclusion("CON-0").statement == "人工修订后的甲"


def test_override_resolution_marks_loser_dissent():
    """深化后：人工指定胜方后败方 status=dissent，胜方挂 dissent 记录。"""
    from app.core.human_ops import override_resolution

    d = _dossier_pair()
    pair = ConflictPair(id="CFL-1", a_id="CON-0", b_id="CON-1", topic="t")
    d.conflicts = [pair.to_dict()]
    override_resolution(d, "CFL-1", "CON-0")
    assert d.conclusion("CON-1").status == "dissent"
    assert d.conclusion("CON-0").status == "majority"
    assert any(x.get("conclusion_id") == "CON-1"
               for x in d.conclusion("CON-0").dissent)
    stored = next(c for c in d.conflicts if c["id"] == "CFL-1")
    assert stored["resolution"]["winner_id"] == "CON-0"


def test_override_tie_keeps_both_majority():
    """深化后：人工判 tie 时双方保持 majority。"""
    from app.core.human_ops import override_resolution

    d = _dossier_pair()
    # 先落成一方胜利，再人工改 tie
    pair = ConflictPair(
        id="CFL-1", a_id="CON-0", b_id="CON-1",
        resolution=Resolution(winner_id="CON-0", rationale="旧裁决"))
    apply_resolution(pair, d)
    d.conflicts = [pair.to_dict()]
    # 恢复双方再 override tie（实现应能从 dissent 拉回或先清再判）
    d.conclusion("CON-1").status = "majority"
    d.conclusion("CON-0").dissent.clear()
    override_resolution(d, "CFL-1", "tie")
    assert d.conclusion("CON-0").status == "majority"
    assert d.conclusion("CON-1").status == "majority"
    stored = next(c for c in d.conflicts if c["id"] == "CFL-1")
    assert stored["resolution"]["winner_id"] == "tie"


def test_override_illegal_winner_raises():
    """深化后：非法 winner 抛 ValueError，案卷状态不动。"""
    from app.core.human_ops import override_resolution

    d = _dossier_pair()
    pair = ConflictPair(id="CFL-1", a_id="CON-0", b_id="CON-1")
    d.conflicts = [pair.to_dict()]
    with pytest.raises(ValueError):
        override_resolution(d, "CFL-1", "CON-9")
    assert d.conclusion("CON-0").status == "majority"
    assert d.conclusion("CON-1").status == "majority"


def test_reopen_conflicts_detects_and_resolves():
    """深化后：reopen_conflicts 用 Coordinator 重跑检测→质证→仲裁并落卷。"""
    from app.core.human_ops import edit_conclusion, reopen_conflicts

    d = _dossier_pair()
    edit_conclusion(d, "CON-0", "2030 前不可能量产")
    edit_conclusion(d, "CON-1", "2030 前必定规模量产")
    client = ScriptedClient([
        '{"conflicts": [{"a": "CON-0", "b": "CON-1", "topic": "量产",'
        ' "description": "对立"}]}',
        "甲方质证",
        "乙方质证",
        '{"winner": "CON-0", "rationale": "证据更扎实"}',
    ])
    coord = Coordinator(client, "m", personas={"a0": "甲", "a1": "乙"})
    pairs = reopen_conflicts(d, coord)
    assert pairs
    assert d.conflicts
    assert d.conclusion("CON-1").status == "dissent" or \
        next(c for c in d.conflicts)["resolution"]["winner_id"] in (
            "CON-0", "CON-1", "tie")
