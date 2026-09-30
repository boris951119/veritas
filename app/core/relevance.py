"""信源相关性分层（零 LLM）：异构资料里混进无关内容时的保守处理。

风险不对称：错杀关键资料是单点故障，多带一份噪声只是浪费几行提示词
——所以分层判据从严、零相关永不删除：

- high    正常注入；
- low     照常注入，标记「低相关：仅必要时引用」（提示词内降权）；
- zero    **不进分析师提示词**，但在报告「未采信信源」章节披露名字
          与理由——丢弃必须可见，绝不静默。

打分口径：议题实体（premise_check 同款抽取，含中英）与信源全文的
2-gram 覆盖 + 外文整串命中；议题抽不出实体时全部视为 high（不裁决）。
这是检索式 rerank 的零 LLM 替代：慢而笨，但每个分数可复算、可解释；
语义 rerank 留作大语料时的可插拔升级位（分数只记录、丢弃仍走披露）。
"""

from __future__ import annotations

from app.core.citation_check import normalize
from app.core.evidence import Dossier
from app.core.premise_check import extract_entities

_SHINGLE_COVER = 0.6   # 单实体判定"覆盖"的 2-gram 命中率
_LOW_THRESHOLD = 0.34  # 低于此且未覆盖任一实体 → low


def _coverage(entity: str, text: str) -> float:
    """实体在文本中的 2-gram 覆盖率；外文实体走整串命中。"""
    if any(c.isascii() and c.isalpha() for c in entity):
        return 1.0 if entity.lower() in text.lower() else 0.0
    shingles = [entity[i:i + 2] for i in range(len(entity) - 1)]
    if not shingles:
        return 0.0
    return sum(1 for sh in shingles if sh in text) / len(shingles)


def classify_sources(dossier: Dossier) -> list[dict]:
    """每份信源 → {source_id, title, level, score, reason}（原信源序）。

    优先级：人工 override（include/exclude，入链可审计）> 议题实体
    覆盖 > 兜底升档（议题零重合但与资料内对撞主题/高相关信源标题
    词汇重合 → low：同义或关联表述不因措辞不同被错杀）。"""
    entities = extract_entities(dossier.question)
    out: list[dict] = []
    if not entities:
        # 议题抽不出实体：不做裁决，全部按 high（宁勿错杀）
        for src in dossier.sources:
            out.append({"source_id": src.id, "title": src.title,
                        "level": "high", "score": None, "reason": ""})
        return out
    base = []
    for src in dossier.sources:
        if src.relevance_override == "include":
            base.append((src, 1.0, "high", "人工强制纳入（入链可审计）"))
            continue
        if src.relevance_override == "exclude":
            base.append((src, None, "zero", "人工强制排除（入链可审计）"))
            continue
        text = normalize("".join(seg.text for seg in src.segments))
        scores = [_coverage(e, text) for e in entities]
        best = max(scores) if scores else 0.0
        best_entity = entities[scores.index(best)] if scores else ""
        if best >= _SHINGLE_COVER:
            level, reason = "high", ""
        elif best > 0 or _latin_hit(entities, text):
            level = "low"
            reason = f"仅与议题实体「{best_entity}」弱相关（覆盖 {best:.0%}）"
        else:
            level, reason = "zero", None  # 兜底检查后再定
        base.append((src, best, level, reason))
    # 兜底升档词汇：对撞主题（实体+指标）与高相关信源标题——议题措辞
    # 与资料措辞不同（同义/关联）时，靠「资料彼此的词汇」机械桥接
    bridge_vocab: list[str] = []
    try:
        from app.core.fact_ledger import find_collisions

        for c in find_collisions(dossier):
            # 实体与指标各自成词（拼接整串过严：「回款率」应独立桥接）
            if c.entity:
                bridge_vocab.append(c.entity)
            if c.metric:
                bridge_vocab.append(c.metric)
    except Exception:
        pass
    bridge_vocab += [t for (_s, _b, lv, _r), t in
                     zip(base, (s.title for s in dossier.sources)) if lv == "high"
                     and t and len(t) >= 2]
    for i, (src, best, level, reason) in enumerate(base):
        if level != "zero" or reason is not None:
            continue  # 已定（含人工排除）
        text = normalize("".join(seg.text for seg in src.segments))
        hit = next((tok for tok in bridge_vocab
                    if _coverage(tok, text) >= _SHINGLE_COVER), None)
        if hit is not None:
            base[i] = (src, best, "low",
                       f"议题实体零重合，但与资料内主题「{hit}」词汇重合"
                       "（疑似同义/关联表述）——兜底降权纳入")
    for src, best, level, reason in base:
        out.append({"source_id": src.id, "title": src.title,
                    "level": level, "score": (round(best, 3)
                                              if best is not None else None),
                    "reason": reason or (f"与议题实体（{'、'.join(entities[:4])}"
                                         f"{'…' if len(entities) > 4 else ''}）零重合"
                                         if level == "zero" else "")})
    return out


def _latin_hit(entities: list[str], text: str) -> bool:
    return any(e.lower() in text.lower() for e in entities
               if any(c.isascii() and c.isalpha() for c in e))


def unadopted_sources(dossier: Dossier) -> list[dict]:
    """零相关信源清单（报告「未采信信源」章节用）。"""
    return [s for s in classify_sources(dossier) if s["level"] == "zero"]
