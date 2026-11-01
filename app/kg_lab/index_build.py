"""索引：原文∪摘要 BM25 语料表 + 摘要（可+原文窗）embedding + 邻接引用。"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

from app.core.bm25 import _tokens, fuse_rankings  # noqa: PLC2701 — spike 复用分词
from app.core.citation_check import normalize
from app.core.evidence import Dossier
from app.kg_lab.config import ARTIFACTS, EMBED_BATCH_CHARS, EMBED_MODEL
from app.kg_lab.ollama_client import embed
from app.kg_lab.slices import segment_map
from app.kg_lab.summarize import load_summary, summary_blob

_K1 = 1.2
_B = 0.75
# R38：长段嵌入窗配方版本；升级后仅重嵌超长／高拉丁段
EMBED_PACK_VER = 2


def _embed_pack(text: str, summary_text: str = "") -> str:
    """长段：头窗＋数字核窗＋高拉丁窗拼装，避免只吃段首。"""
    summary = (summary_text or "").strip()
    body = (text or "").strip()
    if len(body) <= EMBED_BATCH_CHARS and len(summary) < 40:
        return (body or summary or " ")[:EMBED_BATCH_CHARS]
    if len(body) <= EMBED_BATCH_CHARS:
        blob = (summary + "\n" + body).strip() if len(summary) >= 40 else body
        return (blob or " ")[:EMBED_BATCH_CHARS]
    head = body[:420]
    # 数字／日期核窗
    digit_at = -1
    for m in re.finditer(r"\d{2,}", body):
        digit_at = m.start()
        break
    mid = ""
    if digit_at >= 0:
        lo = max(0, digit_at - 80)
        mid = body[lo: lo + 420]
    # 拉丁最密窗
    best_i, best_n = 0, -1
    step = 200
    for i in range(0, max(1, len(body) - 200), step):
        win = body[i: i + 420]
        n = sum(1 for c in win if ("A" <= c <= "Z") or ("a" <= c <= "z"))
        if n > best_n:
            best_n, best_i = n, i
    lat = body[best_i: best_i + 420] if best_n >= 40 else ""
    parts = [summary[:200] if len(summary) >= 40 else "", head, mid, lat]
    blob = "\n".join(p for p in parts if p)
    return (blob or body[:EMBED_BATCH_CHARS] or " ")[:EMBED_BATCH_CHARS]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / math.sqrt(na * nb)


def build_corpus_rows(
    dossier: Dossier,
    *,
    case_slug: str,
    para_ids: set[str],
) -> list[dict[str, Any]]:
    """每段一行：原文、摘要字段、doc_id；R20 带 publish_time／父标题进检索面。"""
    smap = segment_map(dossier)
    doc_of: dict[str, str] = {}
    title_of: dict[str, str] = {}
    cred_of: dict[str, float | None] = {}
    pub_of: dict[str, str] = {}
    for src in dossier.sources:
        raw_cred = (src.meta or {}).get("source_credibility")
        if isinstance(raw_cred, (int, float)) and not isinstance(raw_cred, bool):
            cred: float | None = float(raw_cred)
        else:
            cred = float(src.credibility) if src.credibility is not None else None
        meta = src.meta or {}
        pub = str(
            meta.get("publish_time")
            or meta.get("published_at")
            or meta.get("published_time")
            or ""
        ).strip()
        for seg in src.segments:
            sid = str(seg.id)
            doc_of[sid] = str(src.id)
            title_of[sid] = str(src.title or "")
            cred_of[sid] = cred
            pub_of[sid] = pub
    rows: list[dict[str, Any]] = []
    for pid in sorted(para_ids):
        if pid not in smap:
            continue
        doc_id = doc_of[pid]
        text = smap[pid].text or ""
        title = title_of.get(pid, "") or ""
        summary = load_summary(case_slug, doc_id, pid) or {}
        stext = summary.get("summary_text") or summary_blob(summary)
        # 父标题进索引（低成本）：title\ntext 作检索面，原文 text 仍单独保留
        titled = (title + "\n" + text).strip() if title else text
        rows.append({
            "doc_id": doc_id,
            "para_id": pid,
            "title": title,
            "publish_time": pub_of.get(pid, ""),
            "source_credibility": cred_of.get(pid),
            "text": text,
            "title_text": titled,
            "summary_text": stext,
            "union_text": (titled + "\n" + stext).strip(),
            "entities": list(summary.get("entities") or []),
            "keywords": list(summary.get("keywords") or []),
        })
    return rows


def _bm25_rank(
    docs: list[tuple[str, list[str]]],
    query: str,
) -> list[tuple[str, float]]:
    n_docs = len(docs)
    if n_docs == 0:
        return []
    df: dict[str, int] = {}
    for _, toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    avgdl = sum(len(toks) for _, toks in docs) / n_docs
    q_terms = set(_tokens(query or ""))
    out: list[tuple[str, float]] = []
    for seg_id, toks in docs:
        dl = len(toks)
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for term in q_terms:
            freq = tf.get(term)
            if not freq:
                continue
            idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * freq * (_K1 + 1.0) / (
                freq + _K1 * (1.0 - _B + _B * dl / avgdl)
            )
        out.append((seg_id, round(score, 6)))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


class KgIndex:
    """箱内索引：可序列化到 artifacts/kg-index/{case}/。"""

    def __init__(self, case_slug: str, rows: list[dict[str, Any]]):
        self.case_slug = case_slug
        self.rows = rows
        self.by_id = {r["para_id"]: r for r in rows}
        # 经典臂保持纯正文，避免父标题搅动已拟合 RRF
        self._docs_text = [(r["para_id"], _tokens(r["text"])) for r in rows]
        self._docs_title_text = [
            (r["para_id"], _tokens(r.get("title_text") or r["text"])) for r in rows
        ]
        self._docs_summary = [
            (r["para_id"], _tokens(r["summary_text"] or "")) for r in rows
        ]
        self._docs_union = [
            (r["para_id"], _tokens(r["union_text"] or "")) for r in rows
        ]
        self.embeddings: dict[str, list[float]] = {}

    def bm25_text(self, query: str) -> list[tuple[str, float]]:
        return _bm25_rank(self._docs_text, query)

    def bm25_title_text(self, query: str) -> list[tuple[str, float]]:
        """父标题＋段：仅给一筛多视图／裁决臂用。"""
        return _bm25_rank(self._docs_title_text, query)

    def bm25_summary(self, query: str) -> list[tuple[str, float]]:
        return _bm25_rank(self._docs_summary, query)

    def bm25_union(self, query: str) -> list[tuple[str, float]]:
        return _bm25_rank(self._docs_union, query)

    def ensure_embeddings(
        self,
        *,
        force: bool = False,
        refresh_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        refresh = set(refresh_ids or ())
        cache_path = ARTIFACTS / self.case_slug / "embeddings.json"
        pack_ver = 0
        if cache_path.is_file() and not force:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            self.embeddings = {k: list(v) for k, v in (data.get("vectors") or {}).items()}
            pack_ver = int(data.get("pack_ver") or 0)
            # 补缺；refresh_ids 强制按新摘要重嵌
        # R38：配方升级 → 只重嵌超长或高拉丁段（勿全库重跑）
        if pack_ver < EMBED_PACK_VER and not force:
            for r in self.rows:
                pid = r["para_id"]
                body = str(r.get("text") or "")
                if len(body) < 900:
                    continue
                n_lat = sum(
                    1 for c in body if ("A" <= c <= "Z") or ("a" <= c <= "z")
                )
                if len(body) >= 1200 or (n_lat / max(len(body), 1)) >= 0.45:
                    refresh.add(pid)
        n_new = 0
        for r in self.rows:
            pid = r["para_id"]
            if pid in self.embeddings and not force and pid not in refresh:
                continue
            blob = _embed_pack(
                str(r.get("text") or ""),
                str(r.get("summary_text") or ""),
            )
            self.embeddings[pid] = embed(blob)
            n_new += 1
            if n_new % 50 == 0:
                print(f"  embed {n_new} new…", flush=True)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps({
                    "case": self.case_slug,
                    "model": EMBED_MODEL,
                    "pack_ver": EMBED_PACK_VER,
                    "dim": len(next(iter(self.embeddings.values()), [])),
                    "n": len(self.embeddings),
                    "vectors": self.embeddings,
                }, ensure_ascii=False), encoding="utf-8")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "case": self.case_slug,
            "model": EMBED_MODEL,
            "pack_ver": EMBED_PACK_VER,
            "dim": len(next(iter(self.embeddings.values()), [])),
            "n": len(self.embeddings),
            "vectors": self.embeddings,
        }, ensure_ascii=False), encoding="utf-8")
        return {
            "n_vectors": len(self.embeddings),
            "n_new": n_new,
            "wall_s": round(time.perf_counter() - t0, 3),
            "model": EMBED_MODEL,
        }

    def embed_rank(self, query: str) -> list[tuple[str, float]]:
        if not self.embeddings:
            self.ensure_embeddings()
        qv = embed((query or " ")[:EMBED_BATCH_CHARS])
        scored = [
            (pid, round(_cosine(qv, vec), 6))
            for pid, vec in self.embeddings.items()
        ]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored

    def save_meta(self) -> Path:
        path = ARTIFACTS / self.case_slug / "corpus_meta.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "case": self.case_slug,
            "n_rows": len(self.rows),
            "para_ids": [r["para_id"] for r in self.rows],
            "n_with_summary": sum(1 for r in self.rows if r.get("summary_text")),
        }
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        # 轻量语料（无向量）
        corp = ARTIFACTS / self.case_slug / "corpus.jsonl"
        with corp.open("w", encoding="utf-8") as f:
            for r in self.rows:
                f.write(json.dumps({
                    "doc_id": r["doc_id"],
                    "para_id": r["para_id"],
                    "n_chars": len(r.get("text") or ""),
                    "summary_text": r.get("summary_text") or "",
                    "entities": r.get("entities") or [],
                    "keywords": r.get("keywords") or [],
                }, ensure_ascii=False) + "\n")
        return path


def keyword_expand_query(
    question: str, rows: list[dict[str, Any]], *, top_n: int | None = None,
) -> str:
    """问句拓展（R2d／R2f／R2g／R2h）：对立口径同义优先 + 摘要词补强 − 通稿噪声过滤。

    top_n 缺省＝query_expand.DEFAULT_EXPAND_TOP_N（可扫参覆盖）。不读金标。
    """
    from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, expand_query_parts
    n = DEFAULT_EXPAND_TOP_N if top_n is None else int(top_n)
    return expand_query_parts(question, rows, top_n=n)["expanded_query"]


def rrf_merge(*rankings: list[tuple[str, float]]) -> list[tuple[str, float]]:
    return fuse_rankings(list(rankings))
