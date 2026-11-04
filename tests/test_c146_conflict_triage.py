"""C-146：冲突分流轴（oral_misread／date_offset／true_oppose／other）。

只贴标签、不改判：disposition／conflict_class／置信／归并／采信一律不许动，
故本文件的核心是反事实格（改后剥掉 triage 键必须与改前逐字节相同）。
关＝VERITAS_CONFLICT_TRACE=0；C-145a 起出厂开（本文件两处都量到）。
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.c146_triage_fixtures import (
    build_rows, dossier_with_segments, ledger_cases, pair_cases,
)
from app.config import Settings
from app.core.conflict_trace import (
    CONFLICT_CLASSES,
    TRIAGE_CLASS_CN,
    TRIAGE_CLASSES,
    TRIAGE_REQUIRED_KEYS,
    apply_conflict_trace,
    summarize_trace,
    trace_fields_complete,
    trace_ledger_collision,
    triage_fields_complete,
)
from app.core.evidence import Conclusion, Dossier
from app.core.fact_ledger import Collision, Fact
from app.core.kg_submit_surface import FORBIDDEN_PACK_KEYS, audit_forbidden_keys

SNAPSHOT = Path(__file__).resolve().parent / "c146_pre_triage_snapshot.json"
FIXTURE_ROWS = build_rows()


_ROW_BY_NAME = dict(
    zip([n for n, *_ in ledger_cases()] + [n for n, *_ in pair_cases()],
        FIXTURE_ROWS))


def _row(name: str) -> dict:
    return _ROW_BY_NAME[name]


def test_c146_triage_enum_four_only_and_orthogonal():
    assert TRIAGE_CLASSES == {
        "oral_misread", "date_offset", "true_oppose", "other",
    }
    # 正交：分流轴不许吃掉 C-115 三档，也不许添第四时间档
    assert not (set(TRIAGE_CLASSES) & set(CONFLICT_CLASSES))
    assert CONFLICT_CLASSES == {"same_window", "cross_day", "unknown_time"}
    assert set(TRIAGE_CLASS_CN) == set(TRIAGE_CLASSES)


def test_c146_date_offset_defaults_to_time_band_with_reason():
    r = _row("date_offset")
    assert r["triage_class"] == "date_offset"
    assert r["triage_reason_code"] == "cross_day_time_band"
    # 默认倾向时间档＋披露理由：理由句要说清「按时间档」且不冒充「资料无冲突」
    assert "时间档" in r["triage_reason_short"]
    assert "不等于资料无冲突" in r["triage_reason_short"]
    assert "非冲突" not in json.dumps(r, ensure_ascii=False)
    # 处置仍＝C-115 的跨日保留（两侧留为演变），分流没改成「未决」或「消解」
    assert r["conflict_class"] == "cross_day"
    assert r["disposition"] == "keep"


def test_c146_oral_misread_four_arms_each_fire():
    expect = {
        "oral_hedge": "hedge_number",
        "oral_scale": "scale_misread",
        "oral_not_quantity": "metric_not_quantity",
        "oral_single_segment": "single_segment_two_numbers",
        "pair_identical": "pair_statement_identical",
        "pair_subject_mismatch": "pair_subject_mismatch",
        "pair_topic_disjoint": "pair_topic_disjoint",
    }
    for name, code in expect.items():
        r = _row(name)
        assert r["triage_class"] == "oral_misread", (name, r["triage_class"])
        assert r["triage_reason_code"] == code, (name, r["triage_reason_code"])
        assert isinstance(r["triage_evidence"], dict) and r["triage_evidence"]


def test_c146_oral_misread_hedge_evidence_carries_tokens():
    r = _row("oral_hedge")
    assert r["triage_evidence"]["hedge_tokens"] == ["before:约"]
    assert r["triage_evidence"]["rel_gap"] <= 0.25


def test_c146_true_oppose_fires_and_keeps_undecided():
    for name, code in (
        ("true_oppose", "distinct_values_same_window"),
        ("true_oppose_unknown_time", "distinct_values_unknown_time"),
        ("pair_polarity_opposite", "pair_polarity_opposite"),
        ("pair_disjoint_numbers", "pair_disjoint_numbers"),
    ):
        r = _row(name)
        assert r["triage_class"] == "true_oppose", (name, r["triage_class"])
        assert r["triage_reason_code"] == code
        # 「真对立进留痕 disposition」＝处置字段必须齐全且合法
        assert r["disposition"] in {"keep", "dissent", "undecided"}
        assert trace_fields_complete(r)


def test_c146_other_is_not_inflated_into_true_oppose():
    for name, code in (
        ("pair_undetermined", "pair_mechanically_undetermined"),
        ("pair_unreadable", "pair_statement_unreadable"),
    ):
        r = _row(name)
        assert r["triage_class"] == "other"
        assert r["triage_class_cn"] == "判不出（其他）"
        assert r["triage_reason_code"] == code
        assert "其他" in r["triage_reason_short"]
    # 「判不出」不许被 summary 计进真对立，也不许从分母里消失
    sm = summarize_trace([_row("pair_undetermined"), _row("pair_unreadable")])
    assert sm["by_triage"]["other"] == 2 and sm["by_triage"]["true_oppose"] == 0
    assert sm["by_triage"]["oral_misread"] == 0


def test_c146_counterfactual_stripped_rows_equal_pre_triage_tip():
    """分流没吃掉任何既有字段：剥五键后与改前 tip 输出逐字节相同。

    两侧都必须取到数（14 行），空比空不算「相同」。
    """
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    before = snap["rows"]
    assert len(before) == snap["n_rows"] == len(FIXTURE_ROWS) == 14
    after = [
        {k: v for k, v in row.items() if k not in TRIAGE_REQUIRED_KEYS}
        for row in FIXTURE_ROWS
    ]
    assert after == before
    # 反事实生效的旁证：现算行确实带五键（否则上面等式是空对空）
    assert all(TRIAGE_REQUIRED_KEYS <= set(row) for row in FIXTURE_ROWS)


def test_c146_disposition_table_not_rewritten_by_triage():
    """处置仍＝C-115 原规则（跨日保留、其余未决／按裁决），与分流档无关。"""
    expect_disposition = {
        "date_offset": "keep",           # cross_day
        "oral_hedge": "undecided",       # same_window
        "oral_scale": "undecided",
        "oral_not_quantity": "undecided",
        "oral_single_segment": "undecided",
        "true_oppose": "undecided",
        "true_oppose_unknown_time": "undecided",
    }
    for name, disp in expect_disposition.items():
        assert _row(name)["disposition"] == disp, name
    # 同一时间档里既有 oral_misread 也有 true_oppose ⇒ 档没被分流改写
    same_window = [n for n in expect_disposition if _row(n)["conflict_class"] == "same_window"]
    classes = {_row(n)["triage_class"] for n in same_window}
    assert classes == {"oral_misread", "true_oppose"}


def test_c146_summary_counts_triage_and_sums_to_denominator():
    sm = summarize_trace(FIXTURE_ROWS)
    by = sm["by_triage"]
    assert set(by) == set(TRIAGE_CLASSES)
    assert sum(by.values()) == sm["n"] == len(FIXTURE_ROWS)
    assert sm["triaged"] + sm["untriaged"] == sm["n"]
    assert sm["triage_complete_rate"] == 1.0
    # 既有四键（n／classified／coverage_rate／trace_complete_rate）不改语义
    assert sm["by_class"]["cross_day"] == 1
    assert sm["by_class"]["unclassified"] == 7  # 结论对无对撞可挂＝未归类（C-115 原样）


def test_c146_legacy_rows_without_triage_are_untriaged_not_broken():
    """齐全率两套互不吃：旧行（无 triage 键）仍算 trace_complete，只记未分流。"""
    legacy = summarize_trace([{
        "id": "1", "source": "fact_ledger",
        "conflict_class": "same_window", "conflict_class_cn": "同窗对撞",
        "entry": {"entity": "a"}, "disposition": "undecided",
        "disposition_cn": "未决", "reason_code": "pick_side",
        "reason_short": "x",
    }])
    assert legacy["trace_complete"] == 1
    assert legacy["untriaged"] == 1
    assert legacy["by_triage"] == {
        "date_offset": 0, "oral_misread": 0, "other": 0, "true_oppose": 0,
    }
    assert legacy["triage_complete_rate"] == 0.0
    assert triage_fields_complete(legacy["by_triage"]) is False


def test_c146_apply_writes_axis_and_no_forbidden(monkeypatch):
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "1")
    d = dossier_with_segments()
    cols = [c for _n, c, _s in ledger_cases()]
    payload = apply_conflict_trace(d, collisions=cols, enabled=True)
    assert payload is not None
    assert payload["triage_classes"] == sorted(TRIAGE_CLASSES)
    assert "正交" in payload["triage_axes"]
    assert audit_forbidden_keys(payload) == []
    for bad in FORBIDDEN_PACK_KEYS:
        assert bad not in payload
    flat = json.dumps(payload, ensure_ascii=False)
    assert "金标" not in flat and "gold" not in flat
    by = payload["summary"]["by_triage"]
    # 案卷带段文本 ⇒ build_conflict_trace 把它喂给分流，约数腿才咬得住
    assert by["oral_misread"] == 4 and by["date_offset"] == 1
    assert by["true_oppose"] == 2 and by["other"] == 0
    assert sum(by.values()) == payload["summary"]["n"] == 7


def test_c146_hedge_leg_degrades_without_segment_texts(monkeypatch):
    """段文本取不到＝约数腿自动失效，条目不丢、也不静默换档名。"""
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "1")
    d = Dossier(question="无段文本")
    cols = [c for _n, c, _s in ledger_cases()]
    payload = apply_conflict_trace(d, collisions=cols, enabled=True)
    by = payload["summary"]["by_triage"]
    assert by["oral_misread"] == 3  # 少掉的正是 hedge 那一条
    assert by["true_oppose"] == 3
    assert payload["summary"]["n"] == 7
    codes = {r["id"]: r["triage_reason_code"] for r in payload["records"]}
    assert codes["LEDGER-0002"] == "distinct_values_same_window"


def test_c146_production_path_catches_keyword_misread(monkeypatch):
    """真接线旁证：自己扫卷的对撞也分出档，且「关键词被当指标」亮出口。"""
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "1")
    d = dossier_with_segments()
    payload = apply_conflict_trace(d, collisions=None, enabled=True)
    recs = payload["records"]
    assert recs, "现算必须取到行（空列表不算通过）"
    by = payload["summary"]["by_triage"]
    assert sum(by.values()) == payload["summary"]["n"] == len(recs)
    codes = [r["triage_reason_code"] for r in recs]
    assert "metric_not_quantity" in codes  # 「在岗需求分析师」这类量名闸外的碎片
    assert all(r["triage_class"] in TRIAGE_CLASSES for r in recs)
    assert all(trace_fields_complete(r) and triage_fields_complete(r)
               for r in recs)


def test_c146_flag_off_writes_no_key(monkeypatch):
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "0")
    assert Settings.from_env().conflict_trace is False
    d = Dossier(question="关旗")
    assert apply_conflict_trace(d, collisions=[], enabled=False) is None
    assert "conflict_trace" not in (d.accounting or {})


def test_c146_knife_triage_out_of_enum_raises(monkeypatch):
    """第四档不许自由发明：越界当场抛，不静默落 other。"""
    import pytest

    fact_a = Fact("甲", "补偿金", 10.0, "10万", "s1", "s1#p1", "2024-01-01")
    fact_b = Fact("甲", "补偿金", 20.0, "20万", "s2", "s2#p1", "2024-01-01")
    col = Collision(entity="甲", metric="补偿金", facts=[fact_a, fact_b])
    row = trace_ledger_collision(col, index=1)
    assert row["triage_class"] == "true_oppose"
    from app.core.conflict_trace import _triage_row

    with pytest.raises(ValueError):
        _triage_row("semantic_judgement", "x", "y", {})


def test_c146_export_detail_declares_four_classes(monkeypatch, tmp_path):
    """回放面字段说明里必须点名分流四档（路演读的就是这一面）。"""
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "1")
    from app.export.official import export_official

    q = {"question_id": "q_001", "question": "测"}
    d = Dossier(question="导出面")
    c = Conclusion.create("结论甲", author="mainstream")
    c.status = "majority"
    c.confidence = 0.6
    d.conclusions.append(c)
    paths = export_official([(q, d)], tmp_path / "out")
    j = json.loads(paths["conflict_trace"].read_text(encoding="utf-8"))
    detail = j["detail"]
    assert "triage_class" in detail
    for name in sorted(TRIAGE_CLASSES):
        assert name in detail
