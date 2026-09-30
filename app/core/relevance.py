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
    """每份信源 → {source_id, title, level, score, reason}（原信源序）。"""
    entities = extract_entities(dossier.question)
    out: list[dict] = []
    if not entities:
        # 议题抽不出实体：不做裁决，全部按 high（宁勿错杀）
        for src in dossier.sources:
            out.append({"source_id": src.id, "title": src.title,
                        "level": "high", "score": None, "reason": ""})
        return out
    for src in dossier.sources:
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
            level = "zero"
            reason = (f"与议题实体（{'、'.join(entities[:4])}"
                      f"{'…' if len(entities) > 4 else ''}）零重合")
        out.append({"source_id": src.id, "title": src.title,
                    "level": level, "score": round(best, 3), "reason": reason})
    return out


def _latin_hit(entities: list[str], text: str) -> bool:
    return any(e.lower() in text.lower() for e in entities
               if any(c.isascii() and c.isalpha() for c in e))


def unadopted_sources(dossier: Dossier) -> list[dict]:
    """零相关信源清单（报告「未采信信源」章节用）。"""
    return [s for s in classify_sources(dossier) if s["level"] == "zero"]
