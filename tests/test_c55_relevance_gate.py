"""C-55 件③：议题抽不出实体 ⇒ classify_sources 全判 high（宁勿错杀）。

合成夹具、不读 /tmp、零模型。C-57 顺手清两颗低危：反向腿改真下刀生产早退；
路径格改 AST／行为断言（不再纯字符串在场）。
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.relevance import classify_sources

ROOT = Path(__file__).resolve().parents[1]
_REL = ROOT / "app" / "core" / "relevance.py"


def _src(sid: str, title: str, text: str) -> Source:
    s = Source.create(title, SourceType.WEB, id=sid)
    s.segments = [
        Segment(id=f"{sid}#s1", source_id=sid, text=text, locator="段1", index=0),
    ]
    return s


def _no_entity_dossier() -> Dossier:
    return Dossier(
        question="请分析。",
        sources=[
            _src("A", "天气快讯", "今日晴转多云，气温十八到二十五度。"),
            _src("B", "食谱", "红烧肉焯水后加冰糖炒糖色，小火慢炖。"),
        ],
    )


def test_c55_no_entity_fallback_all_high():
    """议题「请分析。」抽不出实体 ⇒ 两源一律 high（score=None、reason 空）。"""
    rows = classify_sources(_no_entity_dossier())
    assert len(rows) == 2
    assert all(r["level"] == "high" for r in rows)
    assert all(r["score"] is None for r in rows)
    assert all(r["reason"] == "" for r in rows)


def test_c55_no_entity_fallback_ast_early_return():
    """行为＋AST：classify_sources 内存在「if not entities」早退且返回 high。"""
    tree = ast.parse(_REL.read_text(encoding="utf-8"))
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "classify_sources"
    )
    # 找 if not entities: 早退
    found = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        # `if not entities`
        if (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name)
                and test.operand.id == "entities"):
            # 分支内应有 return
            has_return = any(isinstance(x, ast.Return) for x in ast.walk(node))
            assert has_return, "无实体分支必须 return"
            found = True
            break
    assert found, "classify_sources 必须含 if not entities 早退"
    # 行为：现码仍全 high
    assert all(r["level"] == "high" for r in classify_sources(_no_entity_dossier()))


def test_c55_no_entity_fallback_knife_early_return_must_red():
    """反向腿：临时改写源码摘掉早退 ⇒ 正向「全 high」红；清 pyc 后复位绿。

    真下刀生产文件（非 stub 自比）；复位后必须清 __pycache__。
    """
    import shutil
    import importlib
    import app.core.relevance as rel

    raw = _REL.read_text(encoding="utf-8")
    old = """    if not entities:
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
"""
    assert old in raw, "早退块字面漂移，本刀失效需改夹具"
    knife = """    if not entities:
        entities = []  # C-55/C-57 knife：摘掉早退
"""
    d = _no_entity_dossier()
    assert all(r["level"] == "high" for r in classify_sources(d))

    _REL.write_text(raw.replace(old, knife, 1), encoding="utf-8")
    try:
        pyc = ROOT / "app" / "core" / "__pycache__"
        if pyc.is_dir():
            shutil.rmtree(pyc)
        importlib.reload(rel)
        broken = rel.classify_sources(d)
        assert not all(r["level"] == "high" for r in broken)
    finally:
        _REL.write_text(raw, encoding="utf-8")
        pyc = ROOT / "app" / "core" / "__pycache__"
        if pyc.is_dir():
            shutil.rmtree(pyc)
        importlib.reload(rel)

    assert all(r["level"] == "high" for r in rel.classify_sources(d))
