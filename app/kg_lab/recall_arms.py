"""五对照臂：①纯问句BM25 ②摘要BM25 ③embedding ④RRF ⑤RRF+实体／因果一跳。"""

from __future__ import annotations

from typing import Any

from app.kg_lab.graph import load_adjacency
from app.kg_lab.index_build import KgIndex, keyword_expand_query, rrf_merge
from app.kg_lab.query_expand import rule_paraphrase_questions


def _top_k(
    ranked: list[tuple[str, float]],
    *,
    k: int,
    universe: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sid, score in ranked:
        if sid not in universe:
            continue
        if float(score) <= 0:
            continue
        out.append({"para_id": sid, "score": float(score)})
        if len(out) >= k:
            break
    return out


def arm_q_bm25(
    index: KgIndex, question: str, *, k: int, universe: set[str],
) -> dict[str, Any]:
    ranked = index.bm25_text(question)
    picked = _top_k(ranked, k=k, universe=universe)
    return {
        "arm": "q_bm25",
        "queries": [question],
        "picked": picked,
        "paths": {},
    }


def arm_summary_bm25(
    index: KgIndex, question: str, *, k: int, universe: set[str],
) -> dict[str, Any]:
    # 关键词拓展只来自摘要字段（无金标）
    q2 = keyword_expand_query(question, index.rows)
    ranked = index.bm25_summary(q2)
    picked = _top_k(ranked, k=k, universe=universe)
    return {
        "arm": "summary_bm25",
        "queries": [question, q2] if q2 != question else [question],
        "picked": picked,
        "paths": {},
    }


def arm_embedding(
    index: KgIndex, question: str, *, k: int, universe: set[str],
) -> dict[str, Any]:
    ranked = index.embed_rank(question)
    picked = _top_k(ranked, k=k, universe=universe)
    return {
        "arm": "embedding",
        "queries": [question],
        "picked": picked,
        "paths": {},
    }


def arm_paraphrase(
    index: KgIndex, question: str, *, k: int, universe: set[str],
) -> dict[str, Any]:
    """⑥ 规则改写×N（默认 10）：每条 summary BM25⊕embedding，再 RRF 融合（R2g）。"""
    from app.kg_lab.query_expand import DEFAULT_PARAPHRASE_N
    paras = rule_paraphrase_questions(question, n=DEFAULT_PARAPHRASE_N)
    rankings: list[list[tuple[str, float]]] = []
    per_variant: list[dict[str, Any]] = []
    queries: list[str] = [question]
    for v in paras:
        q_para = v["query"]
        q_exp = keyword_expand_query(q_para, index.rows)
        r_sum = index.bm25_summary(q_exp)
        r_emb = index.embed_rank(q_para)
        rankings.append(r_sum)
        rankings.append(r_emb)
        queries.extend([q_para, q_exp])
        per_variant.append({
            "id": v["id"],
            "rule": v["rule"],
            "query": q_para,
            "expanded": q_exp,
            "top3_summary": [
                {"para_id": sid, "score": float(sc)}
                for sid, sc in r_sum[:3] if sid in universe and float(sc) > 0
            ],
            "top3_embedding": [
                {"para_id": sid, "score": float(sc)}
                for sid, sc in r_emb[:3] if sid in universe and float(sc) > 0
            ],
        })
    fused = rrf_merge(*rankings) if rankings else []
    picked = _top_k(fused, k=k, universe=universe)
    n_p = len(paras)
    return {
        "arm": "paraphrase",
        "queries": queries,
        "picked": picked,
        "paths": {},
        "paraphrase_query": paras[0]["query"] if paras else question,
        "paraphrase_variants": per_variant,
        "n_paraphrases": n_p,
        "fuse": f"rrf_over_{n_p}x(summary_bm25+embedding)",
    }


def _fuse_rrf(
    index: KgIndex, question: str,
) -> tuple[list[tuple[str, float]], list[str], list[dict[str, Any]], int]:
    """原文BM25 ⊕ 扩词摘要BM25 ⊕ embedding ⊕ paraphrase×N。不截断、不读金标。"""
    from app.kg_lab.query_expand import DEFAULT_PARAPHRASE_N

    q2 = keyword_expand_query(question, index.rows)
    r1 = index.bm25_text(question)
    r2 = index.bm25_summary(q2)
    r3 = index.embed_rank(question)
    rankings: list[list[tuple[str, float]]] = [r1, r2, r3]
    queries: list[str] = [question, q2]
    paras = rule_paraphrase_questions(question, n=DEFAULT_PARAPHRASE_N)
    para_meta: list[dict[str, Any]] = []
    for v in paras:
        q_para = v["query"]
        q_exp = keyword_expand_query(q_para, index.rows)
        rankings.append(index.bm25_summary(q_exp))
        rankings.append(index.embed_rank(q_para))
        queries.extend([q_para, q_exp])
        para_meta.append({
            "id": v["id"], "rule": v["rule"],
            "query": q_para, "expanded": q_exp,
        })
    fused = rrf_merge(*rankings)
    return fused, queries, para_meta, len(paras)


def _rrf_payload(
    *,
    arm: str,
    fused: list[tuple[str, float]],
    queries: list[str],
    para_meta: list[dict[str, Any]],
    n_p: int,
    k: int,
    universe: set[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    picked = _top_k(fused, k=k, universe=universe)
    out: dict[str, Any] = {
        "arm": arm,
        "queries": queries,
        "picked": picked,
        "paths": {},
        "n_paraphrases": n_p,
        "paraphrase_variants": para_meta,
        "fuse": (
            f"rrf(text+summary_expand+emb"
            f"+{n_p}x(para_summary+para_emb))"
        ),
        "expand_top_n_live": None,  # 由 keyword_expand_query 默认钉死
    }
    if extra:
        out.update(extra)
    return out


def arm_rrf(
    index: KgIndex, question: str, *, k: int, universe: set[str],
) -> dict[str, Any]:
    """主融合 RRF：原文BM25 ⊕ 扩词摘要BM25 ⊕ embedding ⊕ paraphrase×N(摘要+emb)。

    R3：把规则改写信号收进主融合（默认 expand=16 / paraphrase=1，见 query_expand）。
    不读金标。
    """
    fused, queries, para_meta, n_p = _fuse_rrf(index, question)
    return _rrf_payload(
        arm="rrf_bm25_emb", fused=fused, queries=queries,
        para_meta=para_meta, n_p=n_p, k=k, universe=universe,
    )


def arm_rrf_source_role(
    index: KgIndex,
    question: str,
    *,
    k: int,
    universe: set[str],
    dedupe: bool = True,
    role_prior: bool = True,
    weights: dict[str, float] | None = None,
    fused: list[tuple[str, float]] | None = None,
) -> dict[str, Any]:
    """R4 臂：同一套 RRF 融合后做通稿去重 + 角色 prior，再截 Top-k。

    因果扩圈不开。不读金标。
    """
    from app.kg_lab.source_role import rerank_source_role

    if fused is None:
        fused, queries, para_meta, n_p = _fuse_rrf(index, question)
    else:
        queries, para_meta, n_p = [question], [], 0
    rr = rerank_source_role(
        index.rows, fused, dedupe=dedupe, role_prior=role_prior, weights=weights,
    )
    bits = []
    if dedupe:
        bits.append("press_dedupe")
    if role_prior:
        bits.append("role_prior")
    tag = "+".join(bits) if bits else "rrf"
    return _rrf_payload(
        arm="rrf_source_role",
        fused=rr["ranked"],
        queries=queries,
        para_meta=para_meta,
        n_p=n_p,
        k=k,
        universe=universe,
        extra={
            "fuse_post": tag,
            "source_role": {
                "dedupe": dedupe,
                "role_prior": role_prior,
                "role_weight": rr["role_weight"],
                "substitutions": rr["substitutions"][:12],
                "n_clusters_touched": rr["n_clusters_touched"],
            },
        },
    )


def arm_rrf_hop(
    index: KgIndex,
    question: str,
    *,
    k: int,
    universe: set[str],
    case_slug: str,
    seed_k: int | None = None,
    hop_cap: int = 8,
    hop_quota: int | None = None,
) -> dict[str, Any]:
    """RRF 名单 + 实体／因果一跳：独立 hop 配额写入 Top-k（R1）。

    R0 缺陷：邻居分 +1/+2 对种子 1000−i → non_seed 永不入选、⑤≡④。
    R1 策略：final top-k = RRF 前 (k−hop_quota) ∪  hop 邻居 Top-hop_quota
    （邻居须不在 RRF Top-k 内）。可解释：swapped_out = 被挤掉的 RRF 尾。
    """
    k = max(1, int(k))
    # 默认预留约 1/3 名额给 hop；至少 1（k≥2 时）
    if hop_quota is None:
        hop_quota = max(1, k // 3) if k >= 2 else 0
    hop_quota = max(0, min(int(hop_quota), k))

    base = arm_rrf(index, question, k=k, universe=universe)
    rrf_picked = list(base["picked"])
    rrf_ids = [p["para_id"] for p in rrf_picked]
    rrf_set = set(rrf_ids)
    # 扩圈种子：RRF 前列（默认同配额互补的 seed 窗）
    n_seed_use = seed_k if seed_k is not None else max(1, k - hop_quota)
    n_seed_use = max(1, min(int(n_seed_use), len(rrf_ids)))
    seeds = rrf_ids[:n_seed_use]

    adj = load_adjacency(case_slug)
    co = adj.get("co_mention") or {}
    causal = adj.get("causal_hop") or {}

    # hop 候选：不在 RRF Top-k 内；因果权重大于共现
    hop_score: dict[str, float] = {}
    hop_paths: dict[str, list[Any]] = {}
    hop_via: dict[str, str] = {}  # causal | co_mention

    def _offer(tgt: str, add: float, path: Any, via: str) -> None:
        if tgt not in universe or tgt in rrf_set:
            return
        hop_score[tgt] = hop_score.get(tgt, 0.0) + add
        hop_paths.setdefault(tgt, []).append(path)
        # 保留更强 via 标签
        prev = hop_via.get(tgt)
        if prev != "causal":
            hop_via[tgt] = via

    for sid in seeds:
        for hop in (co.get(sid) or [])[:hop_cap]:
            tgt = str(hop.get("to_para_id") or "")
            _offer(tgt, 1.0, hop.get("path") or [sid, "co_mention", tgt], "co_mention")
        for hop in (causal.get(sid) or [])[:hop_cap]:
            tgt = str(hop.get("to_para_id") or "")
            _offer(tgt, 2.0, hop.get("path") or [sid, "causal", tgt], "causal")

    hop_ranked = sorted(
        hop_score.items(),
        key=lambda x: (-x[1], 0 if hop_via.get(x[0]) == "causal" else 1, x[0]),
    )
    n_hop = min(hop_quota, len(hop_ranked), k)
    n_keep_rrf = k - n_hop
    kept_rrf = rrf_picked[:n_keep_rrf]
    hop_take = hop_ranked[:n_hop]
    swapped_out = [p["para_id"] for p in rrf_picked[n_keep_rrf:]]

    picked: list[dict[str, Any]] = []
    paths: dict[str, list[Any]] = {}
    for p in kept_rrf:
        pid = p["para_id"]
        picked.append({
            "para_id": pid,
            "score": float(p["score"]),
            "source": "rrf",
        })
        paths[pid] = [["seed", pid]]
    hop_added_ids: list[str] = []
    for tgt, sc in hop_take:
        hop_added_ids.append(tgt)
        picked.append({
            "para_id": tgt,
            "score": float(sc),
            "source": "hop",
            "via": hop_via.get(tgt, "hop"),
        })
        paths[tgt] = hop_paths.get(tgt, [[tgt]])

    return {
        "arm": "rrf_plus_hop",
        "queries": base["queries"],
        "picked": picked,
        "paths": paths,
        "n_seeds": len(seeds),
        "seed_ids": seeds,
        "hop_quota": hop_quota,
        "n_hop_added": len(hop_added_ids),
        "hop_added_ids": hop_added_ids,
        "swapped_out_ids": swapped_out,
        "n_hop_candidates": len(hop_ranked),
        "rrf_picked_ids": rrf_ids,
    }


def arm_oracle(
    gold_para_ids: set[str],
    *,
    k: int,
    universe: set[str],
) -> dict[str, Any]:
    """仅对照：点名箱内金标段（算 used_gold）。"""
    ids = sorted(p for p in gold_para_ids if p in universe)[:k]
    return {
        "arm": "oracle",
        "queries": ["(oracle gold-in-box)"],
        "picked": [{"para_id": p, "score": 1.0} for p in ids],
        "paths": {},
        "selection_used_gold": True,
    }


def run_all_arms(
    index: KgIndex,
    question: str,
    *,
    k: int,
    universe: set[str],
    case_slug: str,
    gold_para_ids: set[str] | None = None,
    include_oracle: bool = True,
) -> dict[str, dict[str, Any]]:
    arms = {
        "q_bm25": arm_q_bm25(index, question, k=k, universe=universe),
        "summary_bm25": arm_summary_bm25(index, question, k=k, universe=universe),
        "embedding": arm_embedding(index, question, k=k, universe=universe),
        "paraphrase": arm_paraphrase(index, question, k=k, universe=universe),
        "rrf_bm25_emb": arm_rrf(index, question, k=k, universe=universe),
        "rrf_plus_hop": arm_rrf_hop(
            index, question, k=k, universe=universe, case_slug=case_slug,
        ),
    }
    if include_oracle and gold_para_ids is not None:
        arms["oracle"] = arm_oracle(gold_para_ids, k=k, universe=universe)
    return arms
