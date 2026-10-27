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

C-70 双轴（VERITAS_RELEVANCE_SOFT_GATE，默认开）：
- s_rel＝上列实体覆盖 best（可复算）；
- s_match＝找相同轴：词集＝extract_entities(议题) ∪ 议题数字原串；
  段分＝命中词数／词集大小（命中＝normalize 后子串包含／latin lower）；
  **篇分＝各段 max**（禁止篇平均）；词集空⇒0；
- score＝W_REL*s_rel + W_MATCH*s_match（改顶部常量即可调权），保留 3 位；
- 资格＝自动路径不再产出 zero（zero 只留人工 exclude）；level 展示档＝
  s_rel>=0.6⇒high，否则 low。分数／s_match／level **不得**进 rank_segments
  与装箱取舍。关开关＝与改前逐字相同（含 level／reason）。
"""

from __future__ import annotations

from app.core.citation_check import normalize
from app.core.evidence import Dossier
from app.core.premise_check import extract_entities

_SHINGLE_COVER = 0.6   # 单实体判定"覆盖"的 2-gram 命中率
_LOW_THRESHOLD = 0.34  # 低于此且未覆盖任一实体 → low（改前路径保留）

# C-70：双轴权重——改这一处即可调权（判据要求钉在模块顶部）
W_REL = 0.5
W_MATCH = 0.5

# C-70：VERITAS_RELEVANCE_SOFT_GATE（默认开＝先试；关＝改前逐字）
_RELEVANCE_SOFT_GATE = True


def set_relevance_soft_gate(on: bool) -> None:
    global _RELEVANCE_SOFT_GATE
    _RELEVANCE_SOFT_GATE = bool(on)


def relevance_soft_gate_enabled() -> bool:
    return bool(_RELEVANCE_SOFT_GATE)


def _coverage(entity: str, text: str) -> float:
    """实体在文本中的 2-gram 覆盖率；外文实体走整串命中。"""
    if any(c.isascii() and c.isalpha() for c in entity):
        return 1.0 if entity.lower() in text.lower() else 0.0
    shingles = [entity[i:i + 2] for i in range(len(entity) - 1)]
    if not shingles:
        return 0.0
    return sum(1 for sh in shingles if sh in text) / len(shingles)


def match_vocab(question: str) -> list[str]:
    """找相同轴词集＝议题实体 ∪ 议题数字原串（去重保序）。"""
    from app.core.numeric_check import extract_nums

    terms = list(extract_entities(question))
    seen = set(terms)
    for num in extract_nums(question or ""):
        raw = str(num.raw or "").strip()
        if raw and raw not in seen:
            terms.append(raw)
            seen.add(raw)
    return terms


def _token_hit(tok: str, text: str) -> bool:
    """命中＝normalize 后子串包含；latin 走 lower（与架构师 55/217 口径对齐）。"""
    if any(c.isascii() and c.isalpha() for c in tok):
        return tok.lower() in text.lower()
    return tok in text or tok.lower() in text.lower()


def match_score_source(src, vocab: list[str]) -> float:
    """篇分 s_match＝各段命中比的最大值；词集空⇒0。禁止篇平均。"""
    if not vocab:
        return 0.0
    best = 0.0
    for seg in src.segments:
        text = normalize(seg.text or "")
        hits = sum(1 for t in vocab if _token_hit(t, text))
        best = max(best, hits / len(vocab))
    return best


def classify_sources(dossier: Dossier) -> list[dict]:
    """每份信源 → {source_id, title, level, score, reason}（原信源序）。

    优先级：人工 override（include/exclude，入链可审计）> 议题实体
    覆盖 > 兜底升档（议题零重合但与资料内对撞主题/高相关信源标题
    词汇重合 → low：同义或关联表述不因措辞不同被错杀）。

    C-70 软闸开：自动路径不产出 zero；另附 s_rel／s_match／score。
    """
    entities = extract_entities(dossier.question)
    if not entities:
        # 议题抽不出实体：不做裁决，全部按 high（宁勿错杀）
        # （C-55 钉在本函数的早退；软闸开时附 s_match，关时与改前逐字同）
        soft = relevance_soft_gate_enabled()
        vocab = match_vocab(dossier.question) if soft else []
        out: list[dict] = []
        for src in dossier.sources:
            row = {"source_id": src.id, "title": src.title,
                   "level": "high", "score": None, "reason": ""}
            if soft:
                row["s_rel"] = None
                row["s_match"] = round(match_score_source(src, vocab), 3)
            out.append(row)
        return out
    if relevance_soft_gate_enabled():
        return _classify_soft(dossier, entities)
    return _classify_legacy(dossier, entities)


def _classify_legacy(dossier: Dossier, entities: list[str]) -> list[dict]:
    """改前路径（软闸关）——输出须与 HEAD 逐字相同。"""
    out: list[dict] = []
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


def _classify_soft(dossier: Dossier, entities: list[str]) -> list[dict]:
    """C-70 软闸：自动路径不产出 zero；分数只出标签／文案／披露。"""
    vocab = match_vocab(dossier.question)
    out: list[dict] = []
    for src in dossier.sources:
        s_match = match_score_source(src, vocab)
        if src.relevance_override == "include":
            out.append({
                "source_id": src.id, "title": src.title,
                "level": "high", "score": 1.0,
                "reason": "人工强制纳入（入链可审计）",
                "s_rel": 1.0, "s_match": round(s_match, 3),
            })
            continue
        if src.relevance_override == "exclude":
            out.append({
                "source_id": src.id, "title": src.title,
                "level": "zero", "score": None,
                "reason": "人工强制排除（入链可审计）",
                "s_rel": None, "s_match": round(s_match, 3),
            })
            continue
        text = normalize("".join(seg.text for seg in src.segments))
        scores = [_coverage(e, text) for e in entities]
        best = max(scores) if scores else 0.0
        best_entity = entities[scores.index(best)] if scores else ""
        s_rel = float(best)
        score = round(W_REL * s_rel + W_MATCH * s_match, 3)
        # 资格：不再自动 zero；展示档只看 s_rel
        if s_rel >= _SHINGLE_COVER:
            level, reason = "high", ""
        elif s_rel > 0 or _latin_hit(entities, text):
            level = "low"
            reason = f"仅与议题实体「{best_entity}」弱相关（覆盖 {best:.0%}）"
        else:
            level = "low"
            if s_match > 0:
                reason = ("议题实体零重合，但找相同轴有共同数字/专名"
                          f"（s_match={s_match:.0%}）——进候选但标降权")
            else:
                reason = (f"与议题实体（{'、'.join(entities[:4])}"
                          f"{'…' if len(entities) > 4 else ''}）零重合"
                          "且无共同数字/专名——进候选但标降权")
        out.append({
            "source_id": src.id, "title": src.title,
            "level": level, "score": score, "reason": reason,
            "s_rel": round(s_rel, 3), "s_match": round(s_match, 3),
        })
    return out


def _latin_hit(entities: list[str], text: str) -> bool:
    return any(e.lower() in text.lower() for e in entities
               if any(c.isascii() and c.isalpha() for c in e))


def unadopted_sources(dossier: Dossier) -> list[dict]:
    """零相关信源清单（报告「未采信信源」章节用；软闸开时通常只剩人工排除）。"""
    return [s for s in classify_sources(dossier) if s["level"] == "zero"]


def relevance_aggregate(dossier: Dossier) -> dict:
    """聚合披露计数（件⑥）：人工排除／议题零重合无共同词／低相关档。

    文案禁用「漏检率／召回率／覆盖率」。
    """
    rows = classify_sources(dossier)
    n_human = 0
    n_zero_overlap = 0
    n_low = 0
    for r in rows:
        if r["level"] == "zero" and "人工强制排除" in str(r.get("reason") or ""):
            n_human += 1
        if r["level"] == "low":
            n_low += 1
            s_rel = r.get("s_rel")
            s_match = r.get("s_match")
            if (s_rel is not None and float(s_rel) == 0.0
                    and s_match is not None and float(s_match) == 0.0):
                n_zero_overlap += 1
            elif s_rel is None and not relevance_soft_gate_enabled():
                # 关闸路径无 s_* 键：用 reason 里的「零重合」近似（聚合只在开闸时用）
                pass
    return {
        "n_human_exclude": n_human,
        "n_zero_overlap_no_match": n_zero_overlap,
        "n_low": n_low,
        "line": (f"人工排除 {n_human} 份；议题零重合且无共同数字/专名 "
                 f"{n_zero_overlap} 份；低相关档 {n_low} 份（进候选但标降权）"),
    }
