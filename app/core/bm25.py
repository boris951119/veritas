"""纯 Python BM25 段级检索（字符 2-gram 分词，零依赖）。

资料预算装箱器的精排器：输入量大时，按议题对段落做词频×逆文档率
排序，预算内装入最优覆盖。选型理由（见方案文档「规模化路径」）：

- 不用 ES：现场部署是「无开发环境 Windows 机 + U 盘」，JVM 服务与
  「双击就能跑」冲突；本语料量级（几十至几百段）也不需要；
- 不用向量：embedding 端点在用户网关上不保证存在，且打分非确定；
  混合检索留作可插拔口子（与模型画像探测同构）；
- BM25 与机械闸哲学同构：确定性、可解释、可复算——每一段为什么
  排前面，词频与逆文档率可摆上台面。

分词用字符 2-gram（经 citation_check.normalize 归一）：中文检索足够，
IDF 天然压制高频虚词，且不引入 jieba 之类依赖。
"""

from __future__ import annotations

import math

from app.core.citation_check import normalize
from app.core.evidence import Dossier

_K1 = 1.2
_B = 0.75


def _tokens(text: str) -> list[str]:
    t = normalize(text)
    if len(t) < 2:
        return [t] if t else []
    return [t[i:i + 2] for i in range(len(t) - 1)]


def rank_segments(dossier: Dossier) -> list[tuple[str, float]]:
    """全部段落按议题 BM25 分排序 → [(seg_id, score)]，分数降序、
    同分按 id 稳定排序（确定性，全体分析师同料的前提）。"""
    docs: list[tuple[str, list[str]]] = []
    for src in dossier.sources:
        for seg in src.segments:
            docs.append((seg.id, _tokens(seg.text)))
    n_docs = len(docs)
    if n_docs == 0:
        return []
    df: dict[str, int] = {}
    for _, toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    avgdl = sum(len(toks) for _, toks in docs) / n_docs
    query = set(_tokens(dossier.question))
    out: list[tuple[str, float]] = []
    for seg_id, toks in docs:
        dl = len(toks)
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for term in query:
            freq = tf.get(term)
            if not freq:
                continue
            idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * freq * (_K1 + 1.0) / (
                freq + _K1 * (1.0 - _B + _B * dl / avgdl))
        out.append((seg_id, round(score, 6)))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out
