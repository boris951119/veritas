"""C-58：small→big 探针切块／块级 max 回聚合守护；#193／#194。

件① 判据 b 未过 ⇒ 生产打分面零 diff；本文件钉探针侧可复现行为＋挂账格。
合成夹具、不读 /tmp、零模型。
"""

from __future__ import annotations

import importlib
import shutil
from pathlib import Path

from app.agents.second_pass import pick_focus_segments
from app.core.bm25 import expand_query, rank_segments, _tokens
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.material import pack_material, set_exclude_budget_reason, set_material_budget
from scripts.probe_c58_small_to_big import (
    _bm25_score_docs,
    chunk_max_scores,
    split_into_chunks,
)

ROOT = Path(__file__).resolve().parents[1]


def test_c58_split_into_chunks_sentence_then_window():
    """切法钉死：先按句，超 CHUNK_MAX 再定长窗。"""
    text = "甲句。乙句！" + ("丙" * 200)
    chunks = split_into_chunks(text)
    assert chunks[0] == "甲句。"
    assert chunks[1] == "乙句！"
    assert all(len(c) <= 120 for c in chunks[2:])
    assert split_into_chunks(text) == chunks


def _long_seg_keyword_in_third_sentence() -> tuple[Dossier, str, str]:
    """关键词只在第 3 句；前两句与大量垫字稀释整段密度。"""
    s1 = "今日天气晴朗宜出行。"
    s2 = "股市收盘点数小幅波动。"
    s3 = "印度航空AI171空难调查指出燃油开关被切断。"
    pad = "无关填充字句反复出现。" * 60
    text = s1 + s2 + s3 + pad
    chunks = split_into_chunks(text)
    assert len(chunks) >= 3
    assert "印度航空" not in chunks[0]
    assert "印度航空" not in chunks[1]
    assert "印度航空" in chunks[2]
    d = Dossier(question="印度航空 AI171 空难调查结论？")
    src = Source.create("报告", SourceType.WEB, id="D1")
    src.segments.append(Segment(
        id="D1#p1", source_id="D1", text=text, locator="1", index=0))
    d.add_source(src)
    return d, "D1#p1", text


def _per_chunk_scores(dossier: Dossier, text: str) -> list[float]:
    """与 chunk_max_scores 同语料口径，返回该段各块 BM25 分（按切块序）。"""
    chunks = split_into_chunks(text)
    docs = [(f"c{i}", _tokens(ch)) for i, ch in enumerate(chunks)]
    q = expand_query(dossier.question)
    scored = _bm25_score_docs(docs, set(_tokens(q)))
    return [scored.get(f"c{i}", 0.0) for i in range(len(chunks))]


def test_c58_chunk_max_beats_first_and_segment():
    """正向：第 3 句含关键词 ⇒ max＞0 且严格大于首块取法与整段打分。"""
    d, sid, text = _long_seg_keyword_in_third_sentence()
    per = _per_chunk_scores(d, text)
    first = per[0]
    mx = max(per)
    seg = dict(rank_segments(d)).get(sid, 0.0)
    got = chunk_max_scores(d).get(sid, 0.0)
    assert got > 0
    assert first == 0.0 or first < got
    assert got > first  # 取首块 ≠ max
    assert got > seg    # 整段稀释后低于块 max（严格＞）
    assert got == mx


def test_c58_chunk_max_reverse_first_block_knife_must_red():
    """反向腿 K3：源码把 max 改成「取首块」⇒ 正向「max>0 且 >首块」不成立；清 pyc 复位。

    ⚠ 单里写的 `if seg_best.get(sid,0.0)==0.0` 在「首块分==0」夹具上会一直更新到首个正分
    （仍等于 max、0 红）。真「取首块」＝`if sid not in seg_best`。
    """
    import scripts.probe_c58_small_to_big as probe

    path = ROOT / "scripts" / "probe_c58_small_to_big.py"
    raw = path.read_text(encoding="utf-8")
    old = "            if sc > seg_best.get(sid, 0.0):\n                seg_best[sid] = sc"
    new = (
        "            if sid not in seg_best:\n"
        "                seg_best[sid] = sc  # R-C58-2 knife: 取首块"
    )
    assert old in raw, "聚合比较字面漂移，刀失效"

    d, sid, text = _long_seg_keyword_in_third_sentence()
    first = _per_chunk_scores(d, text)[0]
    assert chunk_max_scores(d).get(sid, 0.0) > first

    path.write_text(raw.replace(old, new, 1), encoding="utf-8")
    try:
        pyc = ROOT / "scripts" / "__pycache__"
        if pyc.is_dir():
            shutil.rmtree(pyc)
        importlib.reload(probe)
        broken = probe.chunk_max_scores(d).get(sid, 0.0)
        assert broken == first == 0.0
        # 正向格断言面：got > first 在取首块下不成立
        assert not (broken > first)
    finally:
        path.write_text(raw, encoding="utf-8")
        pyc = ROOT / "scripts" / "__pycache__"
        if pyc.is_dir():
            shutil.rmtree(pyc)
        importlib.reload(probe)
    assert probe.chunk_max_scores(d).get(sid, 0.0) > first


def test_c58_chunk_max_reverse_no_split_knife_must_red():
    """反向腿 K3b：split 退化成整段一块 ⇒ 正向「max>整段」红；清 pyc 复位。"""
    import scripts.probe_c58_small_to_big as probe

    path = ROOT / "scripts" / "probe_c58_small_to_big.py"
    raw = path.read_text(encoding="utf-8")
    needle = '    raw = text or ""\n    if not raw.strip():\n        return []\n'
    insert = (
        '    raw = text or ""\n'
        '    if not raw.strip():\n'
        '        return []\n'
        '    return [raw]  # R-C58-2 knife: 不分块\n'
    )
    assert needle in raw
    d, sid, _text = _long_seg_keyword_in_third_sentence()
    good = chunk_max_scores(d).get(sid, 0.0)
    seg = dict(rank_segments(d)).get(sid, 0.0)
    assert good > seg

    path.write_text(raw.replace(needle, insert, 1), encoding="utf-8")
    try:
        pyc = ROOT / "scripts" / "__pycache__"
        if pyc.is_dir():
            shutil.rmtree(pyc)
        importlib.reload(probe)
        broken = probe.chunk_max_scores(d).get(sid, 0.0)
        seg2 = dict(rank_segments(d)).get(sid, 0.0)
        # 退化成段级：块 max 不再严格大于整段
        assert not (broken > seg2)
    finally:
        path.write_text(raw, encoding="utf-8")
        pyc = ROOT / "scripts" / "__pycache__"
        if pyc.is_dir():
            shutil.rmtree(pyc)
        importlib.reload(probe)
    assert probe.chunk_max_scores(d).get(sid, 0.0) > dict(rank_segments(d)).get(sid, 0.0)


def test_c58_193_excluded_reason_matches_score():
    """钉 reason 与 BM25 分数符号对应：零分→预算截断；有分未装→BM25 排序未入预算。

    这条守护钉的是 reason 与 BM25 分数符号的对应关系，
    依据＝六案 18 题交叉表 16300/5185，见 Qoder 复放记录。
    """
    set_exclude_budget_reason("预算截断")

    # —— 零分未装入 ⇒ 预算截断 ——
    d = Dossier(question="回款坏账风险如何评估？")
    hot = Source.create("热", SourceType.REPORT, id="HOT")
    hot.segments.append(Segment(
        id="HOT#s1", source_id="HOT",
        text="客户回款逾期严重，坏账风险上升。", index=0))
    cold = Source.create("冷", SourceType.REPORT, id="COLD")
    cold.segments.append(Segment(
        id="COLD#s1", source_id="COLD",
        text=("xyz " * 40), index=0))
    d.add_source(hot)
    d.add_source(cold)
    scores = dict(rank_segments(d))
    assert scores.get("COLD#s1", 0.0) == 0.0, scores
    assert scores.get("HOT#s1", 0.0) > 0.0, scores
    set_material_budget(40)
    pack = pack_material(d)
    by = {e["seg_id"]: e["reason"] for e in pack["excluded"]}
    assert "COLD#s1" in by
    assert by["COLD#s1"] == "预算截断", by

    # —— 有分未装入 ⇒ BM25 排序未入预算 ——
    d2 = Dossier(question="回款与坏账风险？")
    for sid in ("A", "B"):
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid,
            text=f"客户{sid}回款逾期，坏账计提增加。" + ("详。" * 30),
            index=0))
        d2.add_source(src)
    set_material_budget(80)
    pack2 = pack_material(d2)
    assert pack2["selected"]
    scores2 = dict(rank_segments(d2))
    assert pack2["excluded"], "预算须挤出至少一段有分段落"
    for e in pack2["excluded"]:
        assert scores2.get(e["seg_id"], 0.0) > 0.0, e
        assert e["reason"] == "BM25 排序未入预算", e


def test_c58_194_fallback_default_on_without_env(monkeypatch):
    """#194：不设 VERITAS_SECOND_PASS_FALLBACK 时回退必须开。"""
    monkeypatch.delenv("VERITAS_SECOND_PASS_FALLBACK", raising=False)
    d = Dossier(question="印度航空 AI171 空难事故调查结论是什么？")
    src = Source.create("调查报告", SourceType.WEB, id="DOC1")
    src.segments.append(Segment(
        id="DOC1#p1", source_id="DOC1",
        text="印度航空 AI171 航班空难调查指出燃油开关被切断是关键因素。",
        locator="段1", index=0))
    d.add_source(src)
    focus = pick_focus_segments(d, limit=2)
    assert focus, "默认必须开回退"
    assert all(f.get("focus_via") == "bm25_pack_fallback" for f in focus)


def test_c58_194_default_knife_must_red(monkeypatch):
    """反向：把默认从「1」改成「0」⇒ #194 正向格必红；清 pyc 后复位。"""
    import app.agents.second_pass as sp

    monkeypatch.delenv("VERITAS_SECOND_PASS_FALLBACK", raising=False)
    path = ROOT / "app" / "agents" / "second_pass.py"
    raw = path.read_text(encoding="utf-8")
    old = 'os.environ.get("VERITAS_SECOND_PASS_FALLBACK", "1")'
    new = 'os.environ.get("VERITAS_SECOND_PASS_FALLBACK", "0")'
    assert old in raw
    d = Dossier(question="印度航空 AI171 空难事故调查结论是什么？")
    src = Source.create("调查报告", SourceType.WEB, id="DOC1")
    src.segments.append(Segment(
        id="DOC1#p1", source_id="DOC1",
        text="印度航空 AI171 航班空难调查指出燃油开关被切断是关键因素。",
        index=0))
    d.add_source(src)
    assert pick_focus_segments(d, limit=2)

    path.write_text(raw.replace(old, new, 1), encoding="utf-8")
    try:
        pyc = ROOT / "app" / "agents" / "__pycache__"
        if pyc.is_dir():
            shutil.rmtree(pyc)
        importlib.reload(sp)
        assert sp.pick_focus_segments(d, limit=2) == []
    finally:
        path.write_text(raw, encoding="utf-8")
        pyc = ROOT / "app" / "agents" / "__pycache__"
        if pyc.is_dir():
            shutil.rmtree(pyc)
        importlib.reload(sp)
    assert sp.pick_focus_segments(d, limit=2)
