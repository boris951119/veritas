"""R19：一筛进池 —— 交卷保经典序；进池用经典⊕多视图⊕邻块 RRF。

主目标：抬高金标进池 20／50；刘翔 @7 不回退（submit_ranked＝纯经典）。
二筛仍只做盒内去重／重排。
"""

from __future__ import annotations

import re
from typing import Any

from app.kg_lab.event_frame import extract_event_frame
from app.kg_lab.index_build import KgIndex, keyword_expand_query, rrf_merge
from app.kg_lab.query_expand import rule_paraphrase_questions
from app.kg_lab.query_views import all_query_views
from app.kg_lab.recall_arms import _fuse_rrf

_VIEW_SCAN = 120
_NEIGHBOR_SEED = 40
_PARA_ORD = re.compile(r"^(?P<doc>.+)#p(?P<n>\d+)$")


def _para_neighbors(para_id: str, known: set[str], *, window: int = 1) -> list[str]:
    m = _PARA_ORD.match(para_id or "")
    if not m:
        return []
    doc, n = m.group("doc"), int(m.group("n"))
    out = []
    for d in range(1, window + 1):
        for cand in (f"{doc}#p{n - d}", f"{doc}#p{n + d}"):
            if cand in known:
                out.append(cand)
    return out


def _view_rankings(
    index: KgIndex, question: str, *, use_llm_views: bool,
) -> tuple[list[list[tuple[str, float]]], list[dict[str, str]], list[str]]:
    """一筛偏召回。裁决型：对立选项＋证据臂；非裁决：保留多视图。"""
    from app.kg_lab.question_intent import adjudication_queries, classify_intent

    frame = extract_event_frame(question)
    intent = classify_intent(question, frame)
    if intent.adjudication:
        views = adjudication_queries(question, frame)
        # 裁决型仍可加 LLM 证据改写，但默认规则即可
        if use_llm_views:
            for v in all_query_views(question, use_llm=True, frame=frame):
                if v["view"] in {"evidence", "conclusion"} and not any(
                    v["query"] == x["query"] for x in views
                ):
                    views.append(v)
    else:
        views = all_query_views(question, use_llm=use_llm_views, frame=frame)
    rankings: list[list[tuple[str, float]]] = []
    queries: list[str] = []
    view_meta: list[dict[str, str]] = []
    for v in views:
        if v["id"] == "raw":
            continue
        qq = v["query"]
        q_exp = keyword_expand_query(qq, index.rows)
        # 视图臂用父标题＋段；不改经典臂的纯正文 BM25
        rankings.append(index.bm25_title_text(qq))
        rankings.append(index.bm25_summary(q_exp))
        if not intent.adjudication or v["view"] in {"evidence", "conclusion"}:
            rankings.append(index.embed_rank(qq))
        queries.extend([qq, q_exp])
        view_meta.append({**v, "intent": intent.kind})
    return rankings, view_meta, queries


def fuse_r19(
    index: KgIndex,
    question: str,
    *,
    use_llm_views: bool = False,
    neighbor_window: int = 1,
    classic_paraphrase_n: int | None = None,
    classic_head: int = 15,
) -> dict[str, Any]:
    """submit＝经典 RRF；pool＝经典⊕视图⊕邻块 RRF。"""
    del classic_paraphrase_n
    frame = extract_event_frame(question)
    classic, classic_queries, _pm, _n = _fuse_rrf(index, question)
    classic_pos = {
        pid: i for i, (pid, sc) in enumerate(classic) if float(sc) > 0
    }

    view_ranks, view_meta, view_queries = _view_rankings(
        index, question, use_llm_views=use_llm_views,
    )
    view_fused = rrf_merge(*view_ranks) if view_ranks else []

    known = {str(r.get("para_id") or "") for r in index.rows if r.get("para_id")}
    # 邻块伪排序：种子＝经典前段＋视图前段
    seeds = [pid for pid, _ in classic[:_NEIGHBOR_SEED] if float(_) > 0]
    seeds += [pid for pid, _ in view_fused[:_NEIGHBOR_SEED]]
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

    # 官方／机构回应臂（通义：高相似靠角色权威）
    authority_q = " ".join(
        t for t in (
            " ".join(frame.actors[:2]),
            "回应 通报 声明 发布 称",
            " ".join(frame.options[:1]),
        ) if t
    ).strip()
    auth_rank = index.bm25_text(authority_q) if len(authority_q) >= 4 else []

    # 进池：经典 + 各视图臂 + 权威臂 + 邻块（多臂对跨案进池更稳；交卷仍用纯经典）
    pool_arms: list[list[tuple[str, float]]] = [classic]
    pool_arms.extend(view_ranks)
    if auth_rank:
        pool_arms.append(auth_rank)
    if nb_rank:
        pool_arms.append(nb_rank)
    pool_ranked = rrf_merge(*pool_arms) if pool_arms else list(classic)

    # 交卷／@k：纯经典，不受填池搅动
    submit_ranked = [(pid, round(float(sc), 6)) for pid, sc in classic if float(sc) > 0]

    # R23：主张／时点短锚补洞——只动 pool，不改 submit
    from app.kg_lab.stage1_claim_holes import fill_stage1_claim_holes

    hole = fill_stage1_claim_holes(
        [(pid, float(sc)) for pid, sc in pool_ranked if float(sc) > 0],
        list(index.rows),
        question,
        bm25_text=index.bm25_text,
        head_keep=10,
        max_inject=8,
    )
    pool_ranked = list(hole["pool_ranked"])

    # 披露：视图独有进前 50 的段数
    classic_top = {pid for pid, _ in classic[:50] if float(_) > 0}
    n_view_fill = sum(
        1 for pid, sc in pool_ranked[:_VIEW_SCAN]
        if float(sc) > 0 and pid not in classic_top
    )

    return {
        "ranked": submit_ranked,
        "pool_ranked": [(pid, round(float(sc), 6)) for pid, sc in pool_ranked if float(sc) > 0],
        "frame": frame.to_dict(),
        "views": view_meta,
        "n_classic_paraphrase": len(rule_paraphrase_questions(question, n=1)),
        "n_neighbor_added": added_nb,
        "n_view_fill": n_view_fill,
        "n_claim_injected": int(hole.get("n_injected") or 0),
        "n_claim_injected_in_pool20": int(hole.get("n_injected_in_pool20") or 0),
        "claim_hole": {
            "applied": bool(hole.get("applied")),
            "clock": list((hole.get("claim") or {}).get("clock") or []),
            "side_a": list((hole.get("claim") or {}).get("side_a") or []),
            "side_b": list((hole.get("claim") or {}).get("side_b") or []),
        },
        "classic_head": classic_head,
        "classic_top_in_pool20": sum(
            1 for pid, _ in pool_ranked[:20] if classic_pos.get(pid, 10**9) <= 20
        ),
        "queries": list(classic_queries) + list(view_queries),
    }


def pool_ids(ranked: list[tuple[str, float]], pool: int) -> list[str]:
    return [pid for pid, sc in ranked[:pool] if float(sc) > 0]


# 兼容旧名
def _view_fused(index: KgIndex, question: str, *, use_llm_views: bool):
    ranks, meta, queries = _view_rankings(index, question, use_llm_views=use_llm_views)
    fused = rrf_merge(*ranks) if ranks else []
    return fused, meta, queries
