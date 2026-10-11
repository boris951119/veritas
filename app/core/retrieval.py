"""检索边界与向量插口。

默认只走 BM25（可加多路问法）。向量/重排不在默认链上：
请求 embedding 且未注册实现时，明确退回字面检索，不假装已启用。
"""

from __future__ import annotations

import os
from typing import Callable

# (question, queries) -> [(seg_id, score)] | None
SemanticSearch = Callable[[str, list[str]], list[tuple[str, float]] | None]

_SEMANTIC_SEARCH: SemanticSearch | None = None

_DEFAULT_NOTE = (
    "检索为字面 BM25，命中词表时在原问上补充同义词。"
    "词表外的说法仍可能未进入本次材料；未进入不等于已审完全库。"
    "假引文与无源数字仍会被闸拦住。向量重排未启用。"
)


def register_semantic_search(fn: SemanticSearch | None) -> None:
    """向量检索插口。未注册时任何混合请求都退回 BM25。"""
    global _SEMANTIC_SEARCH
    _SEMANTIC_SEARCH = fn


def semantic_search(question: str, queries: list[str]) -> list[tuple[str, float]] | None:
    if _SEMANTIC_SEARCH is None:
        return None
    return _SEMANTIC_SEARCH(question, queries)


def requested_mode() -> str:
    raw = (os.environ.get("VERITAS_RETRIEVER") or "bm25").strip().lower()
    return raw or "bm25"


def retrieval_record(query_rewrite: dict | None = None) -> dict:
    """写入报告账本的检索说明。不调用模型。"""
    requested = requested_mode()
    hook = _SEMANTIC_SEARCH is not None
    used = "bm25"
    fallback = False
    if requested in ("embedding", "hybrid", "vector", "semantic"):
        if hook:
            used = requested
        else:
            fallback = True
    qr = query_rewrite or {}
    n_var = len(qr.get("variants") or [])
    head = "检索为字面 BM25"
    if used != "bm25":
        head = f"检索为字面 BM25 + {used}"
    if n_var:
        head += f"，并合并 {n_var} 条补全问句"
    if fallback:
        head += "（已请求向量检索，未接入实现，已退回字面检索）"
    if used == "bm25":
        tail = (
            "。命中词表时在原问上补充同义词；词表外的说法仍可能未进入本次材料；"
            "未进入不等于已审完全库。假引文与无源数字仍会被闸拦住。向量重排未启用。"
        )
    else:
        tail = "。向量通道已接入，与字面检索合并；未进入不等于已审完全库。"
    return {
        "kind": "retrieval",
        "mode": used,
        "requested": requested,
        "semantic_hook": hook,
        "fallback": fallback,
        "n_variants": n_var,
        "note": head + tail,
    }


def retrieval_note(accounting: dict | None) -> str:
    rec = (accounting or {}).get("retrieval") or {}
    note = str(rec.get("note") or "").strip()
    return note or _DEFAULT_NOTE
