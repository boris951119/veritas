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
from collections import defaultdict

from app.core.citation_check import normalize
from app.core.evidence import Dossier

_K1 = 1.2
_B = 0.75
_RRF_K = 60

# 议题过短（仅公司名）时补上财务/情报常用探针，避免 BM25 被噪声段带偏
_PROBE_TERMS = (
    "营业收入 归母净利润 净利润 同比 分红 现金红利 占比 增长率 "
    "营收 扣非 每股 利用小时 装机 改性化率 复合增长"
)

# 命中任一词，就把同组其余词补进原问。只覆盖词表，不声称开放同义。
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("停工", "停产"),
    ("资金链", "流动性"),
    ("应收账款", "回款"),
    ("净利润", "归母净利润"),
    ("营业收入", "营收"),
    ("分红", "现金红利", "派息"),
    ("倒闭", "破产"),
)

# R-C52-1 归因：_DOSSIER_GATED_GROUPS 与 looks_financial 在本批无净贡献
# （关门控⇒批1 L2 54＝+1；关财务判定恒真⇒55＝+2 但属污染旁路，不追）。
# 已摘掉门控专题词表；财务探针只按「短议题」触发。词表冻结：以后扩同义
# 只能走案卷自动抽取且启用前检查命中，禁止手写贴专题词。


def synonym_terms(question: str, *, corpus: str = "") -> list[str]:
    """原问已出现的词，补上同组里还没出现的说法。

    只走 _SYNONYM_GROUPS（R-C52-1 已摘门控专题表）。corpus 非空时，
    扩展词必须已在 corpus 出现——防外部词表硬塞。
    """
    q = question or ""
    extra: list[str] = []
    seen: set[str] = set()
    for group in _SYNONYM_GROUPS:
        if not any(term in q for term in group):
            continue
        for term in group:
            if term in q or term in seen:
                continue
            if corpus and term not in corpus:
                continue
            seen.add(term)
            extra.append(term)
    return extra


def looks_financial(question: str) -> bool:
    """兼容保留：R-C52-1 后恒假（财务探针改由 expand_query 短议题门槛触发）。

    归因：本批关掉（恒真）反而 +2，属污染旁路；摘判定后统一走非财务装箱问句。
    """
    return False


def _tokens(text: str) -> list[str]:
    t = normalize(text)
    if len(t) < 2:
        return [t] if t else []
    return [t[i:i + 2] for i in range(len(t) - 1)]


def expand_query(question: str, *, corpus: str = "") -> str:
    """原问 + 词表同义词；仅短议题（公司名）追加财务探针。

    C-52／R-C52-1：长题一律不打财务探针（归因后摘掉 looks_financial 分支）。
    """
    q = (question or "").strip()
    if not q:
        return _PROBE_TERMS
    parts = [q]
    syn = " ".join(synonym_terms(q, corpus=corpus))
    if syn:
        parts.append(syn)
    # 短议题（公司名）仍打探针；长题不再按财务判定补探针
    if len(q) < 16:
        parts.append(_PROBE_TERMS)
    return " ".join(parts)


def strip_finance_probe_tail(text: str) -> str:
    """去掉 expand_query 追加的财务探针尾（识别特征＝探针首词「营业收入」）。"""
    q = (text or "").strip()
    if not q or "营业收入" not in q:
        return q
    # 探针块以「营业收入」起头；切掉该标记及其后全部探针词
    head, _sep, _tail = q.partition("营业收入")
    return head.rstrip(" ，,;；")


def fuse_rankings(rankings: list[list[tuple[str, float]]],
                  *, k: int = _RRF_K) -> list[tuple[str, float]]:
    """多路排序互惠融合（RRF）。只合并各路 score>0 的命中，稳定按 id 破同分。"""
    if not rankings:
        return []
    if len(rankings) == 1:
        return list(rankings[0])
    fused: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        rank = 0
        for seg_id, score in ranking:
            if score <= 0:
                continue
            fused[seg_id] += 1.0 / (k + rank + 1)
            rank += 1
    out = [(sid, round(sc, 6)) for sid, sc in fused.items()]
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


def rank_segments(dossier: Dossier,
                  query: str | None = None,
                  queries: list[str] | None = None) -> list[tuple[str, float]]:
    """全部段落按查询 BM25 分排序 → [(seg_id, score)]，分数降序、
    同分按 id 稳定排序（确定性，全体分析师同料的前提）。
    query 缺省用案卷议题（经 expand_query）；queries 多路时做 RRF 融合。"""
    if queries:
        cleaned = [str(q).strip() for q in queries if str(q).strip()]
        if len(cleaned) > 1:
            return fuse_rankings([
                rank_segments(dossier, query=q) for q in cleaned])
        if len(cleaned) == 1:
            query = cleaned[0]
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
    raw = query if query is not None else dossier.question
    qtext = expand_query(raw) if query is None else raw
    q_terms = set(_tokens(qtext))
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
                freq + _K1 * (1.0 - _B + _B * dl / avgdl))
        out.append((seg_id, round(score, 6)))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out
