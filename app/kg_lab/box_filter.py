"""进盒前粗筛：对融合候选段问「是否可能回答该问」，保留／丢弃。

约束：粗筛提示不读金标；prompt 可审计；本机 Ollama。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.kg_lab.config import SUMMARY_MODEL
from app.kg_lab.ollama_client import generate_json

# 宽召回池 → 目标盒子
DEFAULT_WIDE_K = 40
DEFAULT_BOX_MIN = 7
DEFAULT_BOX_MAX = 15
DEFAULT_SNIPPET_CHARS = 480
DEFAULT_NUM_PREDICT = 220
DEFAULT_BATCH = 4  # 更小批次，降低 JSON 截断／漏条

FILTER_SYSTEM = (
    "你是证据粗筛员。只根据「议题」与「候选段原文」判断该段是否对回答议题有实质帮助。"
    "keep=true 条件：段内含议题所问的事实、原因、时间、对立说法或直接相关背景。"
    "keep=false 条件：仅名人／通稿套话、与议题无关的赛绩罗列、或无法据此作答。"
    "不要用外部知识补全；不要编造。宁可丢掉弱相关，也不要塞满杂质。"
)

FILTER_PROMPT_TMPL = """{system}

议题：
{question}

候选段列表（逐条判定 keep=true/false）：
{candidates_block}

只输出 JSON，格式严格为：
{{"decisions":[{{"i":1,"keep":true,"reason":"≤20字"}}, ...]}}
对列表中每一条都要有一条 decision，i 从 1 起与列表编号一致；keep 必须是布尔。
"""


def _snippet(text: str, *, n: int = DEFAULT_SNIPPET_CHARS) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def build_filter_prompt(
    question: str,
    candidates: list[dict[str, Any]],
    *,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
) -> str:
    """可审计 prompt 构造（不含 para_id／金标）。"""
    lines: list[str] = []
    for i, c in enumerate(candidates, start=1):
        snip = _snippet(str(c.get("text") or ""), n=snippet_chars)
        lines.append(f"[{i}] {snip}")
    return FILTER_PROMPT_TMPL.format(
        system=FILTER_SYSTEM,
        question=(question or "").strip(),
        candidates_block="\n".join(lines) if lines else "(无候选)",
    )


def _parse_decisions(
    parsed: dict[str, Any], *, n: int,
) -> list[dict[str, Any]]:
    raw = parsed.get("decisions")
    if not isinstance(raw, list):
        # 容错：单条 {"keep": ...}
        if "keep" in parsed and n == 1:
            return [{"i": 1, "keep": bool(parsed.get("keep")),
                     "reason": str(parsed.get("reason") or "")[:40]}]
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            i = int(item.get("i") or item.get("idx") or 0)
        except (TypeError, ValueError):
            i = 0
        keep = item.get("keep")
        if isinstance(keep, str):
            keep = keep.strip().lower() in {"1", "true", "yes", "y", "keep"}
        else:
            keep = bool(keep)
        out.append({
            "i": i,
            "keep": keep,
            "reason": str(item.get("reason") or "")[:40],
        })
    # 按 i 对齐；缺的默认 keep=True（宁可保留）
    by_i = {d["i"]: d for d in out if d["i"] >= 1}
    aligned: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        d = by_i.get(i)
        if d is None:
            aligned.append({"i": i, "keep": True, "reason": "parse_miss_keep"})
        else:
            aligned.append(d)
    return aligned


def filter_candidate_batch(
    question: str,
    candidates: list[dict[str, Any]],
    *,
    model: str = SUMMARY_MODEL,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
    num_predict: int = DEFAULT_NUM_PREDICT,
) -> list[dict[str, Any]]:
    """一批候选粗筛。candidates 每项需有 text；返回带 keep/reason 的副本。

    解析失败时该批全部 keep=True（披露 parse_fail_keep），禁止静默丢候选。
    """
    if not candidates:
        return []
    prompt = build_filter_prompt(
        question, candidates, snippet_chars=snippet_chars,
    )
    resp = generate_json(
        prompt, model=model, num_predict=num_predict, temperature=0.0,
    )
    parsed = resp.get("parsed") or {}
    decisions = _parse_decisions(parsed, n=len(candidates))
    parse_ok = bool(parsed.get("decisions")) or (
        "keep" in parsed and len(candidates) == 1
    )
    if len(decisions) != len(candidates):
        # 与 zip 截断防护：强制对齐为全 keep
        decisions = [
            {"i": i + 1, "keep": True, "reason": "parse_fail_keep"}
            for i in range(len(candidates))
        ]
        parse_ok = False
    out: list[dict[str, Any]] = []
    for c, d in zip(candidates, decisions):
        row = dict(c)
        row["keep"] = bool(d["keep"]) if parse_ok else True
        row["filter_reason"] = (
            d["reason"] if parse_ok else "parse_fail_keep"
        )
        row["filter_raw_ok"] = parse_ok
        out.append(row)
    return out


def coarse_filter_box(
    question: str,
    ranked_candidates: list[dict[str, Any]],
    *,
    text_by_id: dict[str, str],
    model: str = SUMMARY_MODEL,
    wide_k: int = DEFAULT_WIDE_K,
    box_min: int = DEFAULT_BOX_MIN,
    box_max: int = DEFAULT_BOX_MAX,
    batch_size: int = DEFAULT_BATCH,
) -> dict[str, Any]:
    """宽召回候选 → LLM 粗筛 → 按 RRF 分截到 [box_min, box_max]。

    ranked_candidates: [{"para_id","score",...}, ...] 已按融合分降序。
    不读金标。
    """
    pool = list(ranked_candidates)[: max(1, int(wide_k))]
    enriched: list[dict[str, Any]] = []
    for p in pool:
        pid = str(p["para_id"])
        enriched.append({
            "para_id": pid,
            "score": float(p.get("score") or 0.0),
            "text": text_by_id.get(pid) or "",
            "source": p.get("source"),
        })

    judged: list[dict[str, Any]] = []
    prompts_audit: list[str] = []
    bs = max(1, int(batch_size))
    for i in range(0, len(enriched), bs):
        batch = enriched[i : i + bs]
        prompts_audit.append(build_filter_prompt(question, batch))
        judged.extend(filter_candidate_batch(question, batch, model=model))

    kept = [x for x in judged if x.get("keep")]
    dropped = [x for x in judged if not x.get("keep")]
    # 按原融合分排序；截到 box_max；若 keep 过少则仍全部保留（可 < box_min）
    kept_sorted = sorted(kept, key=lambda x: (-float(x["score"]), x["para_id"]))
    box = kept_sorted[: max(1, int(box_max))] if kept_sorted else []
    # 若一张都没 keep：回退取融合前 box_min（披露 fallback）
    fallback = False
    if not box:
        fallback = True
        box = [
            {**x, "keep": True, "filter_reason": "fallback_all_dropped"}
            for x in enriched[: max(1, int(box_min))]
        ]

    return {
        "arm": "fused_rrf_box_filter",
        "queries": [question],  # 粗筛问句＝原议题；不含金标
        "picked": [
            {
                "para_id": x["para_id"],
                "score": float(x["score"]),
                "keep": True,
                "filter_reason": x.get("filter_reason"),
            }
            for x in box
        ],
        "paths": {},
        "wide_k": wide_k,
        "n_pool": len(pool),
        "n_keep_raw": len(kept),
        "n_drop": len(dropped),
        "box_size": len(box),
        "box_min": box_min,
        "box_max": box_max,
        "fallback_empty_keep": fallback,
        "dropped_ids": [x["para_id"] for x in dropped],
        "keep_ids_raw": [x["para_id"] for x in kept_sorted],
        "decisions": [
            {
                "para_id": x["para_id"],
                "keep": bool(x.get("keep")),
                "reason": x.get("filter_reason"),
                "score": float(x["score"]),
            }
            for x in judged
        ],
        "prompt_audit_first_batch": prompts_audit[0] if prompts_audit else "",
        "n_batches": len(prompts_audit),
        "model": model,
        "selection_used_gold": False,
    }


def box_quality(
    box_ids: list[str],
    *,
    l2_gold: set[str],
) -> dict[str, Any]:
    """筛后盒子：金标覆盖、占比、大小。"""
    box = list(box_ids)
    bset = set(box)
    hit = sorted(bset & l2_gold)
    n_box = len(box)
    n_l2 = len(l2_gold)
    return {
        "box_size": n_box,
        "n_l2_gold": n_l2,
        "n_gold_in_box": len(hit),
        "gold_recall": round(len(hit) / n_l2, 4) if n_l2 else None,
        "gold_precision": round(len(hit) / n_box, 4) if n_box else None,
        "gold_hit_ids": hit,
        "miss_ids": sorted(l2_gold - bset),
    }
