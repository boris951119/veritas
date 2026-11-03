"""Entity／Event 笔记 + aliases；抽 causes／enables／contradicts 候选边。"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.kg_lab.config import EDGES_DIR, ENTITIES_DIR, EVENTS_DIR, SUMMARIES_DIR
from app.kg_lab.slices import safe_name

_SAFE = re.compile(r"[^\w.\-\u4e00-\u9fff]+", re.UNICODE)


def _ent_fname(name: str) -> str:
    s = _SAFE.sub("_", name.strip()) or "entity"
    return s[:80]


def build_graph_from_summaries(case_slug: str) -> dict[str, Any]:
    """扫描 summaries JSON → 实体笔记＋边表（邻接用）。"""
    sdir = SUMMARIES_DIR / case_slug
    if not sdir.is_dir():
        return {"case": case_slug, "n_entities": 0, "n_edges": 0}

    # entity → {aliases, mentions:[(doc_id,para_id)], ...}
    entities: dict[str, dict[str, Any]] = {}
    # para → entities
    para_entities: dict[str, list[str]] = defaultdict(list)
    edges: list[dict[str, Any]] = []

    for path in sorted(sdir.glob("*.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        doc_id = str(obj.get("doc_id") or "")
        para_id = str(obj.get("para_id") or "")
        if not para_id:
            continue
        for e in obj.get("entities") or []:
            name = str(e).strip()
            if not name:
                continue
            slot = entities.setdefault(name, {
                "name": name,
                "aliases": [name],
                "mentions": [],
            })
            slot["mentions"].append({"doc_id": doc_id, "para_id": para_id})
            para_entities[para_id].append(name)
        for c in obj.get("causal") or []:
            if not isinstance(c, dict):
                continue
            edges.append({
                "type": c.get("type"),
                "subj": c.get("subj"),
                "obj": c.get("obj"),
                "hint": c.get("hint") or "",
                "src_doc_id": doc_id,
                "src_para_id": para_id,
            })

    # 写实体笔记
    ent_root = ENTITIES_DIR / case_slug
    ent_root.mkdir(parents=True, exist_ok=True)
    for name, slot in entities.items():
        # aliases：同 mention 共现的短名／括号别称简易抽取
        aliases = list(dict.fromkeys(slot["aliases"]))
        md = ent_root / f"{_ent_fname(name)}.md"
        lines = [
            "---",
            "type: entity",
            f"name: {json.dumps(name, ensure_ascii=False)}",
            f"aliases: {json.dumps(aliases, ensure_ascii=False)}",
            f"n_mentions: {len(slot['mentions'])}",
            "---",
            "",
            f"# {name}",
            "",
            "## Mentions",
        ]
        for m in slot["mentions"][:80]:
            link = f"[[slices/{case_slug}/{safe_name(m['doc_id'], m['para_id'])}]]"
            lines.append(f"- {link} (`{m['para_id']}`)")
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 事件笔记：有因果边的 subj／obj 也落一份轻量笔记
    ev_root = EVENTS_DIR / case_slug
    ev_root.mkdir(parents=True, exist_ok=True)
    event_names = sorted({
        str(e.get("subj") or "").strip() for e in edges
    } | {
        str(e.get("obj") or "").strip() for e in edges
    } - {""})
    for en in event_names:
        md = ev_root / f"{_ent_fname(en)}.md"
        related = [e for e in edges if e.get("subj") == en or e.get("obj") == en]
        lines = [
            "---",
            "type: event",
            f"name: {json.dumps(en, ensure_ascii=False)}",
            "---",
            "",
            f"# {en}",
            "",
            "## Causal edges",
        ]
        for e in related[:40]:
            lines.append(
                f"- {e['type']}: {e['subj']} → {e['obj']} "
                f"(from `{e['src_para_id']}`)"
            )
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 边表
    edge_root = EDGES_DIR / case_slug
    edge_root.mkdir(parents=True, exist_ok=True)
    edge_path = edge_root / "edges.jsonl"
    with edge_path.open("w", encoding="utf-8") as f:
        for e in edges:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # 邻接表：实体共现（同段）＋因果一跳（实体名 → para）
    # entity → set(para_id)
    ent_to_paras: dict[str, list[str]] = {
        name: sorted({m["para_id"] for m in slot["mentions"]})
        for name, slot in entities.items()
    }
    # para → 因果可达 para（经边的 subj/obj 实体提及）
    causal_hop: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in edges:
        src_para = str(e.get("src_para_id") or "")
        typ = e.get("type")
        for endpoint in (e.get("subj"), e.get("obj")):
            name = str(endpoint or "").strip()
            if not name or name not in ent_to_paras:
                continue
            for pid in ent_to_paras[name]:
                if pid == src_para:
                    continue
                causal_hop[src_para].append({
                    "to_para_id": pid,
                    "via_entity": name,
                    "edge_type": typ,
                    "subj": e.get("subj"),
                    "obj": e.get("obj"),
                    "path": [
                        src_para,
                        f"{typ}:{e.get('subj')}→{e.get('obj')}",
                        pid,
                    ],
                })
        # 也从 subj 提及段 → obj 提及段
        subj = str(e.get("subj") or "").strip()
        obj = str(e.get("obj") or "").strip()
        if subj in ent_to_paras and obj in ent_to_paras:
            for a in ent_to_paras[subj]:
                for b in ent_to_paras[obj]:
                    if a == b:
                        continue
                    causal_hop[a].append({
                        "to_para_id": b,
                        "via_entity": f"{subj}|{obj}",
                        "edge_type": typ,
                        "subj": subj,
                        "obj": obj,
                        "path": [a, f"{typ}:{subj}→{obj}", b],
                    })

    # 实体共现邻接：同实体其他段
    co_mention: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name, pids in ent_to_paras.items():
        for a in pids:
            for b in pids:
                if a == b:
                    continue
                co_mention[a].append({
                    "to_para_id": b,
                    "via_entity": name,
                    "edge_type": "co_mention",
                    "path": [a, f"mentions:{name}", b],
                })

    adj = {
        "case": case_slug,
        "entity_to_paras": ent_to_paras,
        "para_entities": {k: sorted(set(v)) for k, v in para_entities.items()},
        "co_mention": {k: _dedupe_hops(v) for k, v in co_mention.items()},
        "causal_hop": {k: _dedupe_hops(v) for k, v in causal_hop.items()},
        "n_entities": len(entities),
        "n_edges": len(edges),
        "n_event_notes": len(event_names),
    }
    adj_path = edge_root / "adjacency.json"
    adj_path.write_text(json.dumps(adj, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "case": case_slug,
        "n_entities": len(entities),
        "n_edges": len(edges),
        "n_event_notes": len(event_names),
        "adjacency_path": str(adj_path),
        "edges_path": str(edge_path),
    }


def _dedupe_hops(hops: list[dict[str, Any]], cap: int = 40) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for h in hops:
        key = (str(h.get("to_para_id")), str(h.get("edge_type")), str(h.get("via_entity")))
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
        if len(out) >= cap:
            break
    return out


def load_adjacency(case_slug: str) -> dict[str, Any]:
    path = EDGES_DIR / case_slug / "adjacency.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
