"""C-58：small→big 探针切块／块级 max 回聚合守护；#193／#194；C-65（#198／#199）。

件① 判据 b 未过 ⇒ 生产打分面零 diff；本文件钉探针侧可复现行为＋挂账格。
合成夹具、不读 /tmp、零模型。
C-65：夹具两块正分拉开判别力；三颗反向刀改写 tmp 副本（不许碰仓库树）。
"""

from __future__ import annotations

import importlib.util
import types
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
    """关键词出现两次：较长／弱命中块一次、更短更贴题块一次；首块仍 0 分。

    C-65 #198：至少两块有正分且后一块严格高于前一块，
    否则 max／sum／取首个正分三种取法读数撞车＝夹具无判别力。
    """
    s1 = "今日天气晴朗宜出行。"  # 首块：无关键词 ⇒ 0 分
    # 较长／弱命中：有「印度航空」「空难」但缺 AI171／调查／燃油等贴题词
    s2 = "媒体报道称印度航空空难引发关注，各方持续跟踪。"
    # 更短更贴题：后一块严格更高分
    s3 = "印度航空AI171空难调查指出燃油开关被切断。"
    pad = "无关填充字句反复出现。" * 50
    text = s1 + s2 + s3 + pad
    chunks = split_into_chunks(text)
    assert len(chunks) >= 3
    assert "印度航空" not in chunks[0]
    assert "印度航空" in chunks[1]
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


def _first_positive(per: list[float]) -> float:
    for sc in per:
        if sc > 0.0:
            return sc
    raise AssertionError("夹具无正分块")


def _load_mutated_copy(
    name: str, old: str, new: str, tmp_path: Path,
) -> types.ModuleType:
    """C-65 #199：源文件字节复制进 tmp_path 副本 → replace → 独立加载。

    不许对仓库路径 write_text、不许 importlib.reload 真模块、
    不许 rmtree 任何 __pycache__。
    ``name``＝相对仓库根的路径（如 ``scripts/probe_c58_small_to_big.py``）。
    """
    src = ROOT / name
    raw = src.read_text(encoding="utf-8")
    assert old in raw, f"变异针漂移：{name!r} 找不到 old 字面"
    dest = tmp_path / name.replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(raw.replace(old, new, 1), encoding="utf-8")
    mod_name = f"c65_mut_{dest.stem}_{abs(hash(dest)) & 0xFFFF:x}"
    spec = importlib.util.spec_from_file_location(mod_name, dest)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_c58_chunk_max_beats_first_and_segment():
    """正向：块级 max＞0，且与 sum／首个正分／整段打分互相拉开（C-65 #198）。"""
    d, sid, text = _long_seg_keyword_in_third_sentence()
    per = _per_chunk_scores(d, text)
    first = per[0]
    first_pos = _first_positive(per)
    mx = max(per)
    seg = dict(rank_segments(d)).get(sid, 0.0)
    got = chunk_max_scores(d).get(sid, 0.0)

    # 夹具自证：不成立＝改夹具，不许改断言迁就
    assert sum(per) > mx > first_pos > first == 0.0

    assert got > 0
    assert got > first  # 取首块 ≠ max
    assert got > seg    # 整段稀释后低于块 max（严格＞）
    # 三条互相拉开
    assert got == mx
    assert got < sum(per)
    assert got != first_pos


def test_c58_chunk_max_reverse_first_block_knife_must_red(tmp_path):
    """反向腿：源码把 max 改成「取首块」⇒ 正向「max>0 且 >首块」不成立。

    C-65 #199：变异只落 tmp 副本。⚠ 单里写的 `if seg_best.get(sid,0.0)==0.0`
    在「首块分==0」夹具上会一直更新到首个正分（仍等于 max）。
    真「取首块」＝`if sid not in seg_best`。
    """
    old = "            if sc > seg_best.get(sid, 0.0):\n                seg_best[sid] = sc"
    new = (
        "            if sid not in seg_best:\n"
        "                seg_best[sid] = sc  # R-C58-2 knife: 取首块"
    )
    d, sid, text = _long_seg_keyword_in_third_sentence()
    first = _per_chunk_scores(d, text)[0]
    assert first == 0.0
    assert chunk_max_scores(d).get(sid, 0.0) > first

    probe = _load_mutated_copy(
        "scripts/probe_c58_small_to_big.py", old, new, tmp_path)
    broken = probe.chunk_max_scores(d).get(sid, 0.0)
    assert broken == first == 0.0
    assert not (broken > first)
    # 仓库内真模块未动
    assert chunk_max_scores(d).get(sid, 0.0) > first


def test_c58_chunk_max_reverse_no_split_knife_must_red(tmp_path):
    """反向腿：split 退化成整段一块 ⇒ 正向「max>整段」红。C-65 #199：tmp 副本。"""
    needle = '    raw = text or ""\n    if not raw.strip():\n        return []\n'
    insert = (
        '    raw = text or ""\n'
        '    if not raw.strip():\n'
        '        return []\n'
        '    return [raw]  # R-C58-2 knife: 不分块\n'
    )
    d, sid, _text = _long_seg_keyword_in_third_sentence()
    good = chunk_max_scores(d).get(sid, 0.0)
    seg = dict(rank_segments(d)).get(sid, 0.0)
    assert good > seg

    probe = _load_mutated_copy(
        "scripts/probe_c58_small_to_big.py", needle, insert, tmp_path)
    broken = probe.chunk_max_scores(d).get(sid, 0.0)
    seg2 = dict(rank_segments(d)).get(sid, 0.0)
    assert not (broken > seg2)
    assert chunk_max_scores(d).get(sid, 0.0) > dict(rank_segments(d)).get(sid, 0.0)


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


def test_c58_194_default_knife_must_red(monkeypatch, tmp_path):
    """反向：把默认从「1」改成「0」⇒ #194 正向格必红。C-65 #199：tmp 副本。"""
    monkeypatch.delenv("VERITAS_SECOND_PASS_FALLBACK", raising=False)
    old = 'os.environ.get("VERITAS_SECOND_PASS_FALLBACK", "1")'
    new = 'os.environ.get("VERITAS_SECOND_PASS_FALLBACK", "0")'
    d = Dossier(question="印度航空 AI171 空难事故调查结论是什么？")
    src = Source.create("调查报告", SourceType.WEB, id="DOC1")
    src.segments.append(Segment(
        id="DOC1#p1", source_id="DOC1",
        text="印度航空 AI171 航班空难调查指出燃油开关被切断是关键因素。",
        index=0))
    d.add_source(src)
    assert pick_focus_segments(d, limit=2)

    sp = _load_mutated_copy(
        "app/agents/second_pass.py", old, new, tmp_path)
    # 副本在调用时才读 os.environ 默认（实测：未设 env ⇒ 空列表）
    assert sp.pick_focus_segments(d, limit=2) == []
    # 仓库真模块未动
    assert pick_focus_segments(d, limit=2)


def test_c65_knife_writes_refuse_repo_tree(monkeypatch, tmp_path):
    """C-65 #199 行为型守护：仓库 ROOT 内 Path.write_text 必拒；
    在此 patch 下 helper 仍能造两份变异副本并跑出预期读数。
    """
    import pathlib

    real_write = pathlib.Path.write_text
    root_res = ROOT.resolve()

    def guarded(self: Path, data, encoding=None, errors=None, newline=None):
        resolved = self if self.is_absolute() else (Path.cwd() / self)
        resolved = resolved.resolve()
        try:
            resolved.relative_to(root_res)
        except ValueError:
            return real_write(
                self, data, encoding=encoding, errors=errors, newline=newline)
        raise RuntimeError(f"refused write inside ROOT: {resolved}")

    monkeypatch.setattr(pathlib.Path, "write_text", guarded)

    # 证明：直接写仓库必炸
    try:
        (ROOT / "scripts" / "probe_c58_small_to_big.py").write_text(
            "should-not", encoding="utf-8")
        raise AssertionError("写仓库应被拒")
    except RuntimeError as exc:
        assert "refused write inside ROOT" in str(exc)

    # 两份变异副本（探针取首块 + second_pass 默认 0）必须成功
    old_max = (
        "            if sc > seg_best.get(sid, 0.0):\n"
        "                seg_best[sid] = sc"
    )
    new_first = (
        "            if sid not in seg_best:\n"
        "                seg_best[sid] = sc  # c65 guard"
    )
    probe = _load_mutated_copy(
        "scripts/probe_c58_small_to_big.py", old_max, new_first, tmp_path)
    d, sid, text = _long_seg_keyword_in_third_sentence()
    first = _per_chunk_scores(d, text)[0]
    assert probe.chunk_max_scores(d).get(sid, 0.0) == first == 0.0

    old_fb = 'os.environ.get("VERITAS_SECOND_PASS_FALLBACK", "1")'
    new_fb = 'os.environ.get("VERITAS_SECOND_PASS_FALLBACK", "0")'
    sp = _load_mutated_copy(
        "app/agents/second_pass.py", old_fb, new_fb, tmp_path)
    d2 = Dossier(question="印度航空 AI171 空难事故调查结论是什么？")
    src = Source.create("调查报告", SourceType.WEB, id="DOC1")
    src.segments.append(Segment(
        id="DOC1#p1", source_id="DOC1",
        text="印度航空 AI171 航班空难调查指出燃油开关被切断是关键因素。",
        index=0))
    d2.add_source(src)
    assert sp.pick_focus_segments(d2, limit=2) == []

    # tmp 落在仓库外（当场打印真路径，不许推断）
    print(f"tmp_path_resolved={tmp_path.resolve()}")
    assert not str(tmp_path.resolve()).startswith(str(root_res))
