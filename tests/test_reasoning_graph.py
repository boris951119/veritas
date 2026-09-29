"""契约 A：推理轨迹图（结论→证据→段落→信源 + 冲突/质证/裁决节点）。

深化后由 app.core.reasoning_graph.build_reasoning_graph 提供。
"""

from __future__ import annotations

from app.core.conflicts import ConflictPair, Resolution
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    RelationKind,
    Segment,
    Source,
    SourceType,
)

_NODE_KINDS = {
    "conclusion", "evidence", "segment", "source",
    "conflict", "rebuttal", "arbitration", "analyst",
}
_EDGE_KINDS = {
    "supports", "cites", "from_source", "conflicts_with",
    "rebuts", "decides", "authored_by",
}


def _base_dossier() -> Dossier:
    d = Dossier(question="Q", panel=["a0", "a1"])
    src = Source.create("论文", SourceType.PAPER, credibility=0.8, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="全固态电芯的中试良率尚不足百分之四十。",
        locator="段 1"))
    d.add_source(src)
    for i, (stmt, author) in enumerate((("结论甲偏乐观", "a0"), ("结论乙偏悲观", "a1"))):
        con = Conclusion.create(stmt, author=author, id=f"CON-{i}")
        d.conclusions.append(con)
        d.add_evidence(EvidenceNode.create(
            f"CON-{i}", "全固态电芯的中试良率尚不足百分之四十",
            ["SRC1#s1"], level=EvidenceLevel.B,
            relation=RelationKind.CORRELATION, author=author, id=f"EV-{i}"))
    return d


def _path_exists(nodes: dict, edges: list, start: str, kinds: list[str]) -> bool:
    """沿指定 edge.kind 序列从 start 能否走到终点。"""
    cur = start
    by_src = {}
    for e in edges:
        by_src.setdefault(e["source"], []).append(e)
    for kind in kinds:
        nxt = None
        for e in by_src.get(cur, []):
            if e["kind"] == kind and e["target"] in nodes:
                nxt = e["target"]
                break
        if nxt is None:
            return False
        cur = nxt
    return True


def test_majority_chain_walks_to_source():
    """深化后：majority 结论可沿 supports→cites→from_source 走到 source。"""
    from app.core.reasoning_graph import build_reasoning_graph

    d = _base_dossier()
    graph = build_reasoning_graph(d)
    assert "nodes" in graph and "edges" in graph
    nodes = {n["id"]: n for n in graph["nodes"]}
    for n in graph["nodes"]:
        assert n["kind"] in _NODE_KINDS and "label" in n
    for e in graph["edges"]:
        assert e["kind"] in _EDGE_KINDS
        assert e["source"] in nodes and e["target"] in nodes
    assert _path_exists(nodes, graph["edges"], "CON-0",
                        ["supports", "cites", "from_source"])


def test_resolved_conflict_has_decides_edge():
    """深化后：已消解冲突出现 conflict 节点，且有指向胜方的 decides 边。"""
    from app.core.reasoning_graph import build_reasoning_graph

    d = _base_dossier()
    pair = ConflictPair(
        id="CFL-1", a_id="CON-0", b_id="CON-1", topic="量产前景",
        resolution=Resolution(
            winner_id="CON-0", method="arbitration",
            rationale="甲方证据更完整",
            rebuts={"a": "乙方断章", "b": "甲方样本不足"},
        ),
    )
    d.conflicts = [pair.to_dict()]
    d.conclusion("CON-1").status = "dissent"
    graph = build_reasoning_graph(d, conflicts=[pair])
    nodes = {n["id"]: n for n in graph["nodes"]}
    conflict_nodes = [n for n in graph["nodes"] if n["kind"] == "conflict"]
    assert conflict_nodes, "应有 conflict 节点"
    decides = [e for e in graph["edges"]
               if e["kind"] == "decides" and e["target"] == "CON-0"]
    assert decides, "应有指向胜方 CON-0 的 decides 边"


def test_dissent_conclusion_remains_in_graph():
    """深化后：少数意见结论仍保留在 nodes 中，不因落败被丢弃。"""
    from app.core.reasoning_graph import build_reasoning_graph

    d = _base_dossier()
    d.conclusion("CON-1").status = "dissent"
    pair = ConflictPair(
        id="CFL-1", a_id="CON-0", b_id="CON-1",
        resolution=Resolution(winner_id="CON-0", rationale="胜"),
    )
    graph = build_reasoning_graph(d, conflicts=[pair])
    ids = {n["id"] for n in graph["nodes"]}
    assert "CON-1" in ids


def test_empty_conflicts_still_builds_graph():
    """深化后：无冲突时仍能建图，含结论与信源节点。"""
    from app.core.reasoning_graph import build_reasoning_graph

    d = _base_dossier()
    graph = build_reasoning_graph(d, conflicts=None)
    kinds = {n["kind"] for n in graph["nodes"]}
    assert "conclusion" in kinds and "source" in kinds
    assert not any(n["kind"] == "conflict" for n in graph["nodes"])


def test_rebuttal_nodes_when_resolution_has_rebuts():
    """深化后：resolution.rebuts 非空时图中出现 rebuttal 节点。"""
    from app.core.reasoning_graph import build_reasoning_graph

    d = _base_dossier()
    pair = ConflictPair(
        id="CFL-1", a_id="CON-0", b_id="CON-1",
        resolution=Resolution(
            winner_id="CON-0", rationale="胜",
            rebuts={"a": "甲方质证文本", "b": "乙方质证文本"},
        ),
    )
    graph = build_reasoning_graph(d, conflicts=[pair])
    rebuts = [n for n in graph["nodes"] if n["kind"] == "rebuttal"]
    assert len(rebuts) >= 1
