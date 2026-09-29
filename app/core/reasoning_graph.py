"""推理轨迹图：把案卷物化为 nodes/edges，供工作台与 API 消费。

边语义：
- supports:     结论 → 证据
- cites:        证据 → 段落
- from_source:  段落 → 信源
- authored_by:  结论 → 分析师
- conflicts_with: 冲突 → 双方结论
- rebuts:       质证 → 冲突
- decides:      仲裁/冲突 → 胜方结论（tie 时不连 decides）
"""

from __future__ import annotations

from app.core.conflicts import ConflictPair
from app.core.evidence import Dossier


def _node(nid: str, kind: str, label: str) -> dict:
    return {"id": nid, "kind": kind, "label": (label or "")[:120]}


def _edge(source: str, target: str, kind: str) -> dict:
    return {"source": source, "target": target, "kind": kind}


def _as_pairs(dossier: Dossier, conflicts) -> list[ConflictPair]:
    if conflicts is None:
        return [ConflictPair.from_dict(c) for c in (dossier.conflicts or [])]
    out: list[ConflictPair] = []
    for c in conflicts:
        if isinstance(c, ConflictPair):
            out.append(c)
        elif isinstance(c, dict):
            out.append(ConflictPair.from_dict(c))
    return out


def build_reasoning_graph(dossier: Dossier,
                          conflicts=None) -> dict:
    """案卷 → {nodes, edges}；conflicts 缺省读 dossier.conflicts。"""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(nid: str, kind: str, label: str) -> None:
        if nid not in nodes:
            nodes[nid] = _node(nid, kind, label)

    for name in dossier.panel or []:
        add_node(f"analyst:{name}", "analyst", name)

    for src in dossier.sources:
        add_node(src.id, "source", src.title or src.id)
        for seg in src.segments:
            add_node(seg.id, "segment", seg.locator or seg.id)
            edges.append(_edge(seg.id, src.id, "from_source"))

    for con in dossier.conclusions:
        if con.status == "merged":
            continue  # 溯源成员不进主图，避免噪点；证据已转挂组结论
        add_node(con.id, "conclusion", con.statement)
        for author in con.author_names():
            aid = f"analyst:{author}"
            add_node(aid, "analyst", author)
            edges.append(_edge(con.id, aid, "authored_by"))

    for ev in dossier.evidences:
        con = dossier.conclusion(ev.conclusion_id)
        if con is None or con.status == "merged":
            continue
        add_node(ev.id, "evidence", ev.quote)
        edges.append(_edge(ev.conclusion_id, ev.id, "supports"))
        for sid in ev.segment_ids:
            seg = dossier.segment(sid)
            if seg is None:
                continue
            add_node(sid, "segment", seg.locator or sid)
            edges.append(_edge(ev.id, sid, "cites"))
            src = dossier.source_of_segment(sid)
            if src is not None:
                add_node(src.id, "source", src.title or src.id)
                edges.append(_edge(sid, src.id, "from_source"))

    for pair in _as_pairs(dossier, conflicts):
        add_node(pair.id, "conflict", pair.topic or pair.description or pair.id)
        for cid in (pair.a_id, pair.b_id):
            if cid in nodes or dossier.conclusion(cid) is not None:
                con = dossier.conclusion(cid)
                if con is not None:
                    add_node(cid, "conclusion", con.statement)
                edges.append(_edge(pair.id, cid, "conflicts_with"))
        if pair.resolution is None:
            continue
        res = pair.resolution
        arb_id = f"arb:{pair.id}"
        add_node(arb_id, "arbitration", res.rationale or res.method)
        if res.winner_id in (pair.a_id, pair.b_id):
            edges.append(_edge(pair.id, res.winner_id, "decides"))
            edges.append(_edge(arb_id, res.winner_id, "decides"))
        for side, text in (res.rebuts or {}).items():
            if not text:
                continue
            rid = f"rebut:{pair.id}:{side}"
            add_node(rid, "rebuttal", str(text))
            edges.append(_edge(rid, pair.id, "rebuts"))

    return {"nodes": list(nodes.values()), "edges": edges}
