"""金标召全@K、seen_not、focus∩miss、泄漏检查（禁止金标进查询／特征）。"""

from __future__ import annotations

from typing import Any


def gold_para_set(gold: dict[tuple[str, str], set[str]]) -> set[str]:
    return {p for _d, p in gold}


def l2_gold(
    gold: dict[tuple[str, str], set[str]], universe: set[str],
) -> set[str]:
    return {p for _d, p in gold if p in universe}


def measure_arm(
    pick: dict[str, Any],
    *,
    gold: dict[tuple[str, str], set[str]],
    universe: set[str],
    miss_ids: set[str] | None = None,
    k: int,
) -> dict[str, Any]:
    picked_ids = [str(x["para_id"]) for x in (pick.get("picked") or [])][:k]
    picked_set = set(picked_ids)
    l2 = l2_gold(gold, universe)
    hit = sorted(picked_set & l2)
    miss_l2 = sorted(l2 - picked_set)
    focus_miss = sorted(picked_set & (miss_ids or set()))
    return {
        "arm": pick.get("arm"),
        "k": k,
        "n_picked": len(picked_ids),
        "n_l2_gold": len(l2),
        "n_gold_hit": len(hit),
        "recall_at_k": round(len(hit) / len(l2), 4) if l2 else None,
        "gold_hit_ids": hit,
        "seen_not": miss_l2,  # 箱内金标未进 Top-K
        "n_seen_not": len(miss_l2),
        "focus_cap_miss": focus_miss,
        "n_focus_cap_miss": len(focus_miss),
        "picked_ids": picked_ids,
        "selection_used_gold": bool(pick.get("selection_used_gold")),
        "paths_sample": {
            pid: (pick.get("paths") or {}).get(pid, [])[:2]
            for pid in hit[:5]
        },
    }


def leak_check(
    pick: dict[str, Any],
    *,
    gold: dict[tuple[str, str], set[str]],
) -> dict[str, Any]:
    """查询串／路径文本不得含金标 para_id 或长 quote（oracle 臂除外）。"""
    used_gold = bool(pick.get("selection_used_gold"))
    gold_ids = sorted(gold_para_set(gold))
    quotes = sorted({
        q.strip() for qs in gold.values() for q in qs if q and len(q.strip()) >= 24
    })
    # 只查查询串（结果路径天然含 para_id，不算泄漏进特征）
    blob = "\n".join(str(x) for x in (pick.get("queries") or []))
    id_hits = [gid for gid in gold_ids if gid and gid in blob]
    quote_hits = [q[:40] for q in quotes if q and q in blob][:5]
    leaked = (not used_gold) and (bool(id_hits) or bool(quote_hits))
    return {
        "selection_used_gold": used_gold,
        "gold_id_in_query": id_hits[:10],
        "gold_quote_in_query": quote_hits,
        "leaked": leaked,
        "ok": (not leaked) or used_gold,
    }


def relative_deltas(
    rows: dict[str, dict[str, Any]],
    *,
    baseline: str = "q_bm25",
    oracle: str = "oracle",
) -> dict[str, Any]:
    base = rows.get(baseline) or {}
    ora = rows.get(oracle) or {}
    b_hit = int(base.get("n_gold_hit") or 0)
    o_hit = int(ora.get("n_gold_hit") or 0)
    out: dict[str, Any] = {}
    for name, m in rows.items():
        hit = int(m.get("n_gold_hit") or 0)
        out[name] = {
            "delta_vs_q_bm25": hit - b_hit,
            "delta_vs_oracle": hit - o_hit if ora else None,
            "gap_to_oracle": (o_hit - hit) if ora else None,
        }
    return out
