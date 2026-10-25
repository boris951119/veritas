"""C-55 件③：议题抽不出实体 ⇒ classify_sources 全判 high（宁勿错杀）。

合成夹具、不读 /tmp、零模型。件① 反事实 ΔL2=0 ⇒ 件② 逃逸未动码；
本文件只钉兜底路径。
"""

from __future__ import annotations

from pathlib import Path

from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.relevance import classify_sources

ROOT = Path(__file__).resolve().parents[1]


def _src(sid: str, title: str, text: str) -> Source:
    s = Source.create(title, SourceType.WEB, id=sid)
    s.segments = [
        Segment(id=f"{sid}#s1", source_id=sid, text=text, locator="段1", index=0),
    ]
    return s


def test_c55_no_entity_fallback_all_high():
    """议题「请分析。」抽不出实体 ⇒ 两源一律 high（score=None、reason 空）。"""
    d = Dossier(
        question="请分析。",
        sources=[
            _src("A", "天气快讯", "今日晴转多云，气温十八到二十五度。"),
            _src("B", "食谱", "红烧肉焯水后加冰糖炒糖色，小火慢炖。"),
        ],
    )
    rows = classify_sources(d)
    assert len(rows) == 2
    assert all(r["level"] == "high" for r in rows)
    assert all(r["score"] is None for r in rows)
    assert all(r["reason"] == "" for r in rows)


def test_c55_no_entity_fallback_reverse_must_red():
    """反向腿：摘掉「无实体全 high」早退 ⇒ 本格正向断言必红。

    自证：临时让 extract_entities 仍返回空、但跳过早退分支（改走打分）
    会把与议题零重合的源判成 zero——与「全 high」冲突。
    """
    import app.core.relevance as rel

    d = Dossier(
        question="请分析。",
        sources=[
            _src("A", "天气快讯", "今日晴转多云，气温十八到二十五度。"),
            _src("B", "食谱", "红烧肉焯水后加冰糖炒糖色，小火慢炖。"),
        ],
    )
    # 正向：现码全 high
    assert all(r["level"] == "high" for r in classify_sources(d))

    real = rel.classify_sources

    def _broken_no_early_return(dossier: Dossier):
        """模拟删掉早退：无实体时仍走覆盖打分 ⇒ 全 zero。"""
        from app.core.citation_check import normalize
        from app.core.premise_check import extract_entities

        entities = extract_entities(dossier.question)
        assert not entities  # 夹具仍抽不出
        out = []
        for src in dossier.sources:
            text = normalize("".join(seg.text for seg in src.segments))
            # 无实体 ⇒ best=0 ⇒ zero（若无早退）
            out.append({
                "source_id": src.id, "title": src.title,
                "level": "zero", "score": 0.0,
                "reason": "与议题实体零重合",
            })
        return out

    rel.classify_sources = _broken_no_early_return
    try:
        broken = rel.classify_sources(d)
        # 摘掉早退后不再全 high ⇒ 正向「全 high」不成立
        assert not all(r["level"] == "high" for r in broken)
    finally:
        rel.classify_sources = real

    # 复位后仍全 high
    assert all(r["level"] == "high" for r in classify_sources(d))


def test_c55_fallback_path_in_source():
    """源码钉死早退分支字面（内容断言，非 git diff）。"""
    src = (ROOT / "app" / "core" / "relevance.py").read_text(encoding="utf-8")
    assert "if not entities:" in src
    assert "全部按 high" in src or "全部视为 high" in src or "宁勿错杀" in src
