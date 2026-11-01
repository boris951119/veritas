"""C-69 树10-①：日期键名统一读点＋对撞三档（零模型、合成夹具）。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.config import Settings
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, Segment, Source, SourceType,
)
from app.core.fact_ledger import (
    Collision, Fact, extract_facts, facts_block, find_collisions,
    ledger_time_class_enabled, set_ledger_time_class,
)
from app.core.skills import detect_skills
from app.core.temporal_check import (
    set_source_time_unified, source_date, source_time_unified,
)


def _src(sid: str, text: str, **meta) -> Source:
    s = Source.create(sid, SourceType.REPORT, id=sid)
    s.meta.update(meta)
    s.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text, index=0))
    return s


@pytest.fixture(autouse=True)
def _reset_flags():
    set_source_time_unified(False)
    set_ledger_time_class(False)
    yield
    set_source_time_unified(False)
    set_ledger_time_class(False)


# ---- 件⑥ a：只有 publish_time → 开关开有归一日，关则空 ----
def test_c69_a_publish_time_only_respects_switch():
    """刀：开关开却读不到 publish_time（改回只认 published_at）⇒ Fact.date 空＝红。"""
    d = Dossier(question="Q")
    d.add_source(_src(
        "S1", "华东集团回款率40%。",
        publish_time="2026-03-15T10:00:00+08:00"))
    set_source_time_unified(False)
    assert all(not f.date for f in extract_facts(d))
    set_source_time_unified(True)
    facts = extract_facts(d)
    assert facts and all(f.date == "20260315" for f in facts), facts


# ---- 件⑥ b：两键都有且不同 → 取 published_at ----
def test_c69_b_published_at_wins_over_publish_time():
    """刀：优先级写成 publish_time 优先 ⇒ date 变 20260101＝红。"""
    s = _src(
        "S1", "华东集团回款率40%。",
        published_at="2026-05-20T12:00:00Z",
        publish_time="2026-01-01T00:00:00Z")
    set_source_time_unified(True)
    assert source_date(s) == "20260520"


# ---- 件⑥ c：同日不同时戳 → same_window（原始串刀必须红）----
def test_c69_c_same_day_different_clock_is_same_window():
    """同日 10:00 与 22:00 ⇒ time_class=same_window；原始串判据＝cross_day。"""
    import scripts.probe_c69_time_ledger as probe

    f1 = Fact("华东", "回款率", 0.4, "40%", "A", "A#s1",
              "2026-03-15T10:00:00+08:00")
    f2 = Fact("华东", "回款率", 0.5, "50%", "B", "B#s1",
              "2026-03-15T22:00:00+08:00")
    c = Collision(entity="华东", metric="回款率", facts=[f1, f2])
    # 属性用归一日
    assert c.time_class == "same_window", c.time_class
    # 探针纯函数对照
    assert probe.classify_time_class([f1.date, f2.date]) == "same_window"
    assert probe.raw_time_class([f1.date, f2.date]) == "cross_day"


def test_c69_c_knife_raw_string_criterion_must_red():
    """判据 c 的牙：若 time_class 改用原始串比较 ⇒ 本格红。"""
    f1 = Fact("华东", "回款率", 0.4, "40%", "A", "A#s1",
              "2026-03-15T10:00:00+08:00")
    f2 = Fact("华东", "回款率", 0.5, "50%", "B", "B#s1",
              "2026-03-15T22:00:00+08:00")
    c = Collision(entity="华东", metric="回款率", facts=[f1, f2])
    # 模拟"原始串判据"：直接比 f.date 原串
    raws = [f.date for f in c.facts]
    raw_class = ("unknown_time" if any(not r for r in raws)
                 else ("same_window" if len(set(raws)) == 1 else "cross_day"))
    assert raw_class == "cross_day"
    assert c.time_class == "same_window"
    assert c.time_class != raw_class  # 归一牙：两判据必须分歧


# ---- 件⑥ d：缺日期 → unknown_time ----
def test_c69_d_missing_date_is_unknown_time():
    """刀：缺日期却标 same_window／cross_day ⇒ 红。"""
    f1 = Fact("华东", "回款率", 0.4, "40%", "A", "A#s1", "20260315")
    f2 = Fact("华东", "回款率", 0.5, "50%", "B", "B#s1", "")
    c = Collision(entity="华东", metric="回款率", facts=[f1, f2])
    assert c.time_class == "unknown_time"


# ---- 件⑥ e：开关全关 facts_block 与改前逐字相同 ----
def test_c69_e_switches_off_facts_block_byte_equal():
    """刀：关开关时仍走新文案（含「时序演变」）⇒ 红。"""
    d = Dossier(question="Q")
    d.add_source(_src("A", "客户B回款率40%。", published_at="2026-01-01"))
    d.add_source(_src("B", "客户B回款率50%。", published_at="2026-06-01"))
    set_source_time_unified(False)
    set_ledger_time_class(False)
    baseline = facts_block(d)
    assert "采信哪一方" in baseline
    assert "时序演变" not in baseline
    assert "时点不明，未据此排序" not in baseline
    # 再开再关必须回到同一串
    set_ledger_time_class(True)
    _ = facts_block(d)
    set_ledger_time_class(False)
    assert facts_block(d) == baseline


def test_c69_e_switches_off_three_json_sha_stable(tmp_path):
    """判据 b：开关全关时同一合成案卷两跑 evidence／report／confidence sha 逐位不变。

    （用 export_official＋固定 id；pipeline 每次新建 Conclusion 会漂 uuid，
    那不是本单开关引入的漂移。）
    """
    from app.export.official import export_official

    set_source_time_unified(False)
    set_ledger_time_class(False)
    # 本格测的是「关臂」路径（显式压 0），与生产默认开无关

    d = Dossier(question="客户B的回款情况如何？")
    d.add_source(_src("S1", "客户B回款率40%。",
                      publish_time="2026-03-15T10:00:00+08:00"))
    con = Conclusion.create("客户B回款率约四成", author="stub", id="CON-fixed")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        con.id, "客户B回款率40%", ["S1#s1"],
        id="EV-fixed", level=EvidenceLevel.A))

    def _shas(out: Path) -> dict[str, str]:
        paths = export_official(
            [({"question_id": "Q1", "question": d.question}, d)], out)

        # export 键：evidence／conclusions／confidence；判据 b 写 report.json＝案卷面
        report = out / "report.json"
        d.to_json(report)
        names = {
            "evidence": paths["evidence"],
            "confidence": paths["confidence"],
            "report": report,
        }
        return {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in names.items()}

    h1 = _shas(tmp_path / "a")
    h2 = _shas(tmp_path / "b")
    assert h1 == h2, (h1, h2)


# ---- 件⑥ f：三档不删条目 ----
def test_c69_f_time_class_does_not_drop_rows():
    """刀：facts_block 过滤掉 cross_day／unknown ⇒ 行数变少＝红。"""
    d = Dossier(question="Q")
    # 跨日
    d.add_source(_src("A", "华东回款率40%。",
                      publish_time="2026-01-01T00:00:00Z"))
    d.add_source(_src("B", "华东回款率50%。",
                      publish_time="2026-06-01T00:00:00Z"))
    # 不明（无时点）
    d.add_source(_src("C", "华南回款率30%。"))
    d.add_source(_src("D", "华南回款率35%。"))
    set_source_time_unified(True)
    set_ledger_time_class(True)
    cols = find_collisions(d)
    assert len(cols) >= 2
    block = facts_block(d)
    # 每条对撞都应出现（[:8] 封顶内）
    for c in cols[:8]:
        assert c.metric in block
    assert block.count("\n- ") == min(8, len(cols))


# ---- 件⑥ g：as_of trigger 走统一读点 ----
def test_c69_g_as_of_trigger_uses_unified_reader():
    """只有 publish_time：开⇒触发 as_of_discipline；关⇒不触发。"""
    d = Dossier(question="Q")
    d.add_source(_src(
        "S1", "客户B回款率40%。",
        publish_time="2026-03-15T10:00:00+08:00"))
    set_source_time_unified(False)
    names_off = {s.name for s in detect_skills(d)}
    assert "as_of_discipline" not in names_off
    set_source_time_unified(True)
    names_on = {s.name for s in detect_skills(d)}
    assert "as_of_discipline" in names_on


# ---- 判据 d：默认值（Boyu 10-28 拍＝一直开着）----
def test_c69_d_defaults_are_on():
    """刀：把 Settings 两旗默认翻成 False ⇒ 本格红。"""
    s = Settings()
    assert s.source_time_unified is True
    assert s.ledger_time_class is True
    # 模块旗与 Settings 对齐（autouse 会先压关；本格单独拉回默认开）
    set_source_time_unified(True)
    set_ledger_time_class(True)
    assert source_time_unified() is True
    assert ledger_time_class_enabled() is True


# ---- 真引用（§5 第 26 条）----
def test_c69_true_ref_probe_pure_fns():
    """import scripts.probe_c69_time_ledger 并调用 classify_time_class／day_norm。"""
    import scripts.probe_c69_time_ledger as probe

    assert probe.day_norm("2026-03-15T10:00:00Z") == "20260315"
    assert probe.classify_time_class(
        ["2026-03-15T10:00:00Z", "2026-03-15T22:00:00Z"]) == "same_window"
    assert probe.raw_time_class(
        ["2026-03-15T10:00:00Z", "2026-03-15T22:00:00Z"]) == "cross_day"
    assert probe.classify_time_class(["20260315", ""]) == "unknown_time"


# ---- R-C69-1 件②：不许静默 except（K7 牙）----
def test_c69_r1_fact_ledger_scan_no_silent_except():
    """刀：_scan 再包 try/except 退回改前内联 ⇒ 本格红。"""
    import inspect

    from app.core import fact_ledger

    src = inspect.getsource(fact_ledger._scan)
    assert "except Exception" not in src
    assert "source_date" in src and "source_time_unified" in src


# ---- R-C69-1 件①：月粒度时点（K10 牙）----
def test_c69_r1_month_granularity_published_at_nonempty_on():
    """刀：ON 臂仍要求 ≥8 位才返回 ⇒ 2026-03 变空＝红。"""
    s = _src("S1", "华东集团回款率40%。", published_at="2026-03")
    set_source_time_unified(True)
    assert source_date(s) == "202603"


def test_c69_r1_month_beats_year_no_skip_key():
    """刀：不足 8 位就跳到 year ⇒ 得 2025＝红；必须钉在 published_at＝202603。"""
    s = _src("S1", "华东集团回款率40%。",
             published_at="2026-03", year="2025")
    set_source_time_unified(True)
    assert source_date(s) == "202603"
    assert source_date(s) != "2025"


# ---- R-C69-1 件③：arbiter 接线牙（K6）----
def test_c69_r1_arbiter_dates_of_uses_unified_reader():
    """只有 publish_time：开闸后仲裁提示词须含归一日；摘掉 arbiter 接线 ⇒ 本格红。"""
    from types import SimpleNamespace

    from app.agents.arbiter import Coordinator
    from app.core.conflicts import ConflictPair

    class _Cap:
        def __init__(self):
            self.calls = []

        def chat(self, model, messages, json_mode=False):
            self.calls.append(messages)
            return SimpleNamespace(content='{"winner":"tie","rationale":"测"}')

    d = Dossier(question="Q")
    d.add_source(_src(
        "S1", "客户B回款率40%。",
        publish_time="2026-03-15T10:00:00+08:00"))
    d.add_source(_src(
        "S2", "客户B回款率50%。",
        publish_time="2026-06-01T00:00:00Z"))
    ca = Conclusion.create("甲说四成", author="a", id="CON-A")
    cb = Conclusion.create("乙说五成", author="b", id="CON-B")
    d.conclusions.extend([ca, cb])
    d.add_evidence(EvidenceNode.create(
        ca.id, "客户B回款率40%", ["S1#s1"], id="EV-A", level=EvidenceLevel.A))
    d.add_evidence(EvidenceNode.create(
        cb.id, "客户B回款率50%", ["S2#s1"], id="EV-B", level=EvidenceLevel.A))
    pair = ConflictPair(
        id="P1", a_id="CON-A", b_id="CON-B", topic="回款率", description="对立")

    set_source_time_unified(True)
    cap = _Cap()
    Coordinator(cap, "m").arbitrate(d, pair, rebuts={})
    blob = "\n".join(
        str(m.get("content") or "")
        for msgs in cap.calls for m in msgs if isinstance(m, dict))
    assert "20260315" in blob, blob
    assert "20260601" in blob, blob


# ---- R-C69-1 件④：三态计数合成格（K8）----
def test_c69_r1_official_three_state_counts(tmp_path):
    """三篇＝完整 ISO／2026-09／无键 ⇒ 开＝1/1/1；关＝detail 与改前逐字同。"""
    import json

    from app.ingest.official_case import load_official_case

    def _doc(doc_id: str, publish_time=None) -> dict:
        text = "这是一段足够长的正文内容用于过闸。"
        row = {
            "doc_id": doc_id,
            "title": doc_id,
            "content": text,
            "paragraphs": [{
                "para_id": f"{doc_id}#p1",
                "char_start": 0,
                "char_end": len(text),
            }],
        }
        if publish_time is not None:
            row["publish_time"] = publish_time
        return row

    case = tmp_path / "syn"
    case.mkdir()
    (case / "raw_documents.json").write_text(
        json.dumps([
            _doc("d_full", "2026-03-15T10:00:00+08:00"),
            _doc("d_month", "2026-09"),
            _doc("d_miss"),  # 无键
        ], ensure_ascii=False),
        encoding="utf-8")

    set_source_time_unified(False)
    d_off = load_official_case(case)
    note_off = next(
        n for n in d_off.ingest_notes if n.get("kind") == "official_publish_time")
    assert note_off["detail"] == (
        "publish_time 无法作为完整日期使用、已留空：2 篇（未推断日期）")
    assert "n_full_iso" not in note_off

    set_source_time_unified(True)
    d_on = load_official_case(case)
    note_on = next(
        n for n in d_on.ingest_notes if n.get("kind") == "official_publish_time")
    assert note_on.get("n_full_iso") == 1
    assert note_on.get("n_present_non_iso") == 1
    assert note_on.get("n_key_missing") == 1
    assert "完整 ISO 1" in note_on["detail"]
    assert "在场但非完整 ISO 1" in note_on["detail"]
    assert "键缺失 1" in note_on["detail"]


# ---- R-C69-1 件⑤：pipeline 两旗接线牙（K9）----
def test_c69_r1_pipeline_wiring_flags_reach_modules(tmp_path):
    """Settings 开两旗 → run_case 后模块旗必须 True；摘掉 pipeline 传旗 ⇒ 本格红。"""
    from types import SimpleNamespace

    from app.pipeline import RunDeps, RunSpec, run_case

    class _Stub:
        def chat(self, model, messages, json_mode=False):
            return SimpleNamespace(content="""```json
{"conclusions": [
  {"statement": "客户B回款率约四成",
   "evidence": [{"quote": "客户B回款率40%",
                 "segment_id": "S1#s1",
                 "relation": "correlation", "level": "A", "note": "测"}]}
]}
```""")

    s = Settings()
    s.source_time_unified = True
    s.ledger_time_class = True
    d = Dossier(question="客户B的回款情况如何？")
    d.add_source(_src(
        "S1", "客户B回款率40%。材料填充。" * 5,
        publish_time="2026-03-15T10:00:00+08:00"))
    # 跑前强制关，证明是 pipeline 传旗把它打开
    set_source_time_unified(False)
    set_ledger_time_class(False)
    run_case(
        RunSpec(dossier=d, out_dir=tmp_path / "out", settings=s, probe=False),
        RunDeps(client=_Stub()),
    )
    assert source_time_unified() is True
    assert ledger_time_class_enabled() is True


# ---- R-C69-2 件①：no_silent_except 行为腿（K11）----
def test_c69_r2_no_silent_except_raises_on_import_failure():
    """开关开时 _scan 遇 temporal_check 真失败必须上抛，不许静默退回内联。

    刀：把 import 包回 except (ImportError, ValueError) 并静默退回改前内联 ⇒ 本格红（K11）。
    """
    import sys

    from app.core import fact_ledger

    set_source_time_unified(True)
    d = Dossier(question="Q")
    d.add_source(_src(
        "S1", "华东集团回款率40%。",
        published_at="2026-03-15T10:00:00+08:00"))

    real = sys.modules.get("app.core.temporal_check")

    class _Boom:
        def __getattr__(self, name):
            raise ImportError("c69-r2 injected: temporal_check unavailable")

    sys.modules["app.core.temporal_check"] = _Boom()  # type: ignore[assignment]
    try:
        with pytest.raises(ImportError, match="c69-r2 injected"):
            fact_ledger._scan(d)
    finally:
        if real is not None:
            sys.modules["app.core.temporal_check"] = real
        else:
            sys.modules.pop("app.core.temporal_check", None)


# ---- R-C69-2 件②：ON 臂只有 meta.year（K12）----
def test_c69_r2_source_date_year_only_on_arm():
    """只有 meta.year（无 published_at／publish_time）⇒ source_date 取到该值。

    刀：摘掉 ON 臂优先级链的 year 那一档 ⇒ 本格红（K12）。
    """
    s = _src("S1", "华东集团回款率40%。", year="2024")
    assert "published_at" not in s.meta
    assert "publish_time" not in s.meta
    set_source_time_unified(True)
    assert source_date(s) == "2024"


# ---- R-C69-2 件③：cross_day 正向＋时序演变文案（K13）----
def test_c69_r2_cross_day_positive_and_ledger_phrase():
    """两条 Fact 都是 8 位且不同日 ⇒ cross_day；ledger_time_class 开时文案含「时序演变」。

    刀：把同日也判成 cross_day（或把跨日判成 same_window）⇒ 本格红（K13）。
    """
    f_a = Fact("华东", "回款率", 0.4, "40%", "A", "A#s1", "20260315")
    f_b = Fact("华东", "回款率", 0.5, "50%", "B", "B#s1", "20260601")
    cross = Collision(entity="华东", metric="回款率", facts=[f_a, f_b])
    assert cross.time_class == "cross_day", cross.time_class

    # 同日对照：本格自己钉住，防「同日也判 cross_day」绕过（K13 另一向）
    f_c = Fact("华东", "回款率", 0.4, "40%", "C", "C#s1", "20260315")
    f_d = Fact("华东", "回款率", 0.5, "50%", "D", "D#s1", "20260315")
    same = Collision(entity="华东", metric="回款率", facts=[f_c, f_d])
    assert same.time_class == "same_window", same.time_class

    d = Dossier(question="Q")
    d.add_source(_src(
        "A", "华东回款率40%。",
        published_at="2026-03-15T10:00:00+08:00"))
    d.add_source(_src(
        "B", "华东回款率50%。",
        published_at="2026-06-01T00:00:00Z"))
    set_source_time_unified(True)
    set_ledger_time_class(True)
    block = facts_block(d)
    assert "时序演变" in block, block
    cols = [c for c in find_collisions(d) if c.metric.endswith("回款率") or "回款率" in c.metric]
    assert cols and any(c.time_class == "cross_day" for c in cols), [
        (c.entity, c.metric, c.time_class) for c in find_collisions(d)]
