"""C-109：主线一筛进池——系数只活在模块内，出口仅 pool_ids／pool_ranked。

薄适配分析师 ``stage1_pool.fuse_r19`` 进池形：经典 BM25 ⊕ 裁决／证据视图
⊕ 邻块 ⊕ 权威臂 RRF；**不**把 R9／R21／DEFAULT_WEIGHTS 放出模块，
更不进 ``pack_material`` kwargs。

无 embedding／KgIndex 硬依赖（禁百炼；本机 embed 可选，默认关）。
"""

from __future__ import annotations

import os
import re
from typing import Any

from app.core.bm25 import expand_query, fuse_rankings, rank_segments
from app.core.kg_submit_surface import (
    FORBIDDEN_PACK_KEYS,
    audit_forbidden_keys,
    stage1_pool_export,
)
from app.kg_lab.event_frame import extract_event_frame
from app.kg_lab.question_intent import adjudication_queries, classify_intent

_PARA_ORD = re.compile(r"^(?P<doc>.+)#p(?P<n>\d+)$")
_NEIGHBOR_SEED = 40
_DEFAULT_POOL_N = 180
_EMBED_MODEL = "bge-m3:latest"
_OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def kg_stage1_enabled(settings: Any | None = None) -> bool:
    """默认开。``VERITAS_KG_STAGE1=0`` 回退无池（仅密度桥／旧 BM25）。"""
    if settings is not None and hasattr(settings, "kg_stage1"):
        return bool(getattr(settings, "kg_stage1"))
    v = (os.environ.get("VERITAS_KG_STAGE1") or "").strip().lower()
    if v in ("0", "false", "off", "no"):
        return False
    if v in ("1", "true", "on", "yes"):
        return True
    return True


def pool_ids(ranked: list[tuple[str, float]], pool: int) -> list[str]:
    return [pid for pid, sc in ranked[: max(0, int(pool))] if float(sc) > 0]


def _para_neighbors(para_id: str, known: set[str], *, window: int = 1) -> list[str]:
    m = _PARA_ORD.match(para_id or "")
    if not m:
        return []
    doc, n = m.group("doc"), int(m.group("n"))
    out: list[str] = []
    for d in range(1, window + 1):
        for cand in (f"{doc}#p{n - d}", f"{doc}#p{n + d}"):
            if cand in known:
                out.append(cand)
    return out


def _bm25_rank(dossier: Any, query: str) -> list[tuple[str, float]]:
    q = (query or "").strip()
    if len(q) < 2:
        return []
    return list(rank_segments(dossier, query=q))


def _stage1_embed_enabled() -> bool:
    v = (os.environ.get("VERITAS_KG_STAGE1_EMBED") or "").strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    return False  # 默认关；显式 =1 才烧本机 bge（禁百炼）


def _ollama_embed(text: str) -> list[float]:
    import json
    import urllib.request

    blob = (text or " ")[:800]
    raw = json.dumps(
        {"model": _EMBED_MODEL, "prompt": blob},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{_OLLAMA}/api/embeddings",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60.0) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    vec = data.get("embedding") or []
    return [float(x) for x in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na ** 0.5) / (nb ** 0.5)


def _embed_rerank_head(
    dossier: Any,
    question: str,
    pool_ranked: list[tuple[str, float]],
    *,
    head: int = 48,
) -> list[tuple[str, float]]:
    """对本机 embedding 重排池头（系数仍不出模块）。失败则原样返回。"""
    if not _stage1_embed_enabled() or not pool_ranked:
        return pool_ranked
    try:
        qv = _ollama_embed(question or " ")
    except Exception:
        return pool_ranked
    by_id = {
        seg.id: seg
        for src in dossier.sources
        for seg in src.segments
    }
    head_ids = [pid for pid, _ in pool_ranked[: max(1, int(head))]]
    scored: list[tuple[str, float]] = []
    for pid in head_ids:
        text = str(getattr(by_id.get(pid), "text", "") or "")
        try:
            pv = _ollama_embed(text)
            scored.append((pid, round(_cosine(qv, pv), 6)))
        except Exception:
            scored.append((pid, 0.0))
    scored.sort(key=lambda x: (-x[1], x[0]))
    # 头用 embed 序，尾保持原 RRF 序
    head_set = {pid for pid, _ in scored}
    tail = [(pid, sc) for pid, sc in pool_ranked if pid not in head_set]
    return scored + tail


def fuse_stage1_pool(
    dossier: Any,
    *,
    neighbor_window: int = 1,
    pool_n: int = _DEFAULT_POOL_N,
) -> dict[str, Any]:
    """一筛进池。内部可有多臂分；出口经 ``stage1_pool_export`` 剥系数键。"""
    question = str(getattr(dossier, "question", "") or "")
    frame = extract_event_frame(question)
    intent = classify_intent(question, frame)

    # 经典臂（交卷／@k 参照序）
    classic = [
        (pid, float(sc))
        for pid, sc in rank_segments(dossier)
        if float(sc) > 0
    ]
    known = {
        str(seg.id)
        for src in dossier.sources
        for seg in src.segments
    }

    # 视图臂：裁决用对立选项；否则 expand_query 单臂
    view_ranks: list[list[tuple[str, float]]] = []
    view_meta: list[dict[str, str]] = []
    if intent.adjudication or frame.options:
        for v in adjudication_queries(question, frame):
            qq = str(v.get("query") or "").strip()
            if len(qq) < 4:
                continue
            view_ranks.append(_bm25_rank(dossier, qq))
            view_ranks.append(_bm25_rank(dossier, expand_query(qq)))
            view_meta.append({**v, "intent": intent.kind})
    else:
        exp = expand_query(question)
        if exp and exp != question:
            view_ranks.append(_bm25_rank(dossier, exp))
            view_meta.append({
                "id": "expand", "view": "evidence", "query": exp,
                "intent": intent.kind,
            })

    view_fused = fuse_rankings(view_ranks) if view_ranks else []

    # 邻块伪排序
    seeds = [pid for pid, sc in classic[:_NEIGHBOR_SEED] if float(sc) > 0]
    seeds += [pid for pid, sc in view_fused[:_NEIGHBOR_SEED]]
    nb_rank: list[tuple[str, float]] = []
    seen_nb: set[str] = set()
    added_nb = 0
    if neighbor_window > 0:
        for i, pid in enumerate(seeds):
            for nb in _para_neighbors(pid, known, window=neighbor_window):
                if nb in seen_nb:
                    continue
                seen_nb.add(nb)
                nb_rank.append((nb, 1000.0 - i))
                added_nb += 1

    # 权威／通报臂
    authority_q = " ".join(
        t for t in (
            " ".join(frame.actors[:2]),
            "回应 通报 声明 发布 称 官方",
            " ".join(frame.options[:1]),
        ) if t
    ).strip()
    auth_rank = _bm25_rank(dossier, authority_q) if len(authority_q) >= 4 else []

    # 轻量主张补洞：选项释义／时点命中段注入池头（无多维系数）
    hole_rank: list[tuple[str, float]] = []
    anchors = list(frame.options[:3]) + list(frame.time_cues[:4])
    anchors = [a for a in anchors if len(str(a)) >= 2]
    if anchors:
        by_id = {
            seg.id: seg
            for src in dossier.sources
            for seg in src.segments
        }
        scored: list[tuple[str, float]] = []
        for pid, seg in by_id.items():
            text = str(seg.text or "")
            hits = sum(1 for a in anchors if a and a in text)
            if hits <= 0:
                continue
            scored.append((pid, float(hits) * 10.0 + min(len(text), 200) / 200.0))
        scored.sort(key=lambda x: (-x[1], x[0]))
        hole_rank = scored[:24]

    pool_arms: list[list[tuple[str, float]]] = [classic]
    pool_arms.extend(view_ranks)
    if auth_rank:
        pool_arms.append(auth_rank)
    if nb_rank:
        pool_arms.append(nb_rank)
    if hole_rank:
        pool_arms.append(hole_rank)
    pool_ranked = fuse_rankings(pool_arms) if pool_arms else list(classic)
    pool_ranked = [
        (pid, round(float(sc), 6)) for pid, sc in pool_ranked if float(sc) > 0
    ]
    # 本机 embed 重排池头（默认关；VERITAS_KG_STAGE1_EMBED=1 开）
    pool_ranked = _embed_rerank_head(dossier, question, pool_ranked, head=48)
    submit_ranked = [
        (pid, round(float(sc), 6)) for pid, sc in classic if float(sc) > 0
    ]

    export = stage1_pool_export(pool_ranked, pool_n=int(pool_n))
    # 禁键：出口不得带 coeff／feats／weights
    leaks = audit_forbidden_keys(export)
    if leaks:
        raise ValueError(f"stage1 export forbidden keys: {leaks}")
    for bad in FORBIDDEN_PACK_KEYS:
        if bad in export:
            raise ValueError(f"stage1 top-level forbidden key: {bad}")

    return {
        "export": export,
        "pool_ids": list(export["pool_ids"]),
        "pool_ranked": list(export["pool_ranked"]),
        "submit_ranked": submit_ranked,
        "submit_ids": pool_ids(submit_ranked, int(pool_n)),
        "frame": frame.to_dict() if hasattr(frame, "to_dict") else {},
        "views": view_meta,
        "n_neighbor_added": added_nb,
        "n_hole": len(hole_rank),
        "intent": intent.kind,
        "pool_n": int(pool_n),
    }


def stage1_pool_from_dossier(
    dossier: Any,
    *,
    pool_n: int = _DEFAULT_POOL_N,
) -> dict[str, Any]:
    """主线唯一入口：返回剥系数后的进池面。"""
    return fuse_stage1_pool(dossier, pool_n=pool_n)
