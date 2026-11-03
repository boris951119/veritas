"""C-115：冲突三类＋处置留痕；默认关；禁系数。"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.conflict_trace import (
    CONFLICT_CLASSES,
    DISPOSITIONS,
    apply_conflict_trace,
    conflict_trace_enabled,
    disposition_of_pair,
    normalize_conflict_class,
    summarize_trace,
    trace_fields_complete,
    trace_ledger_collision,
)
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, RelationKind,
    Segment, Source, SourceType,
)
from app.core.fact_ledger import Collision, Fact
from app.core.kg_submit_surface import FORBIDDEN_PACK_KEYS, audit_forbidden_keys


def _collision(entity: str, metric: str, facts: list[Fact]) -> Collision:
    return Collision(entity=entity, metric=metric, facts=facts)


def test_c115_flag_default_on(monkeypatch):
    """C-145a：出厂默认开（路演可见）；显式 env=0 关。"""
    monkeypatch.delenv("VERITAS_CONFLICT_TRACE", raising=False)
    assert Settings().conflict_trace is True
    assert conflict_trace_enabled() is True
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "0")
    assert Settings.from_env().conflict_trace is False
    assert conflict_trace_enabled() is False


def test_c115_flag_off_no_accounting(monkeypatch):
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "0")
    d = Dossier(question="测")
    assert apply_conflict_trace(d, collisions=[], enabled=False) is None
    assert "conflict_trace" not in (d.accounting or {})


def test_c115_hard_enum_three_classes_only():
    assert normalize_conflict_class("same_window") == "same_window"
    assert normalize_conflict_class("cross_day") == "cross_day"
    assert normalize_conflict_class("unknown_time") == "unknown_time"
    assert normalize_conflict_class("第四类") == "unclassified"
    assert normalize_conflict_class("") == "unclassified"
    assert CONFLICT_CLASSES == {"same_window", "cross_day", "unknown_time"}


def test_c115_ledger_no_date_is_unknown_not_dropped():
    """禁「无日期＝非冲突」：缺时点仍留痕，档＝unknown_time。"""
    facts = [
        Fact("甲", "补偿金", 49.4, "49.4万", "s1", "s1#p1", ""),
        Fact("甲", "补偿金", 60.0, "60万", "s2", "s2#p1", ""),
    ]
    row = trace_ledger_collision(_collision("甲", "补偿金", facts), index=1)
    assert row["conflict_class"] == "unknown_time"
    assert row["disposition"] == "undecided"
    assert trace_fields_complete(row)
    assert "非冲突" not in row["reason_short"]


def test_c115_cross_day_keep_same_window_undecided():
    f_old = Fact("甲", "伤亡", 10.0, "10", "s1", "s1#p1", "2024-01-01")
    f_new = Fact("甲", "伤亡", 20.0, "20", "s2", "s2#p1", "2024-06-01")
    cross = trace_ledger_collision(_collision("甲", "伤亡", [f_old, f_new]), index=1)
    assert cross["conflict_class"] == "cross_day"
    assert cross["disposition"] == "keep"

    f_a = Fact("甲", "补偿金", 49.4, "49.4", "s1", "s1#p1", "2024-03-12T10:00:00")
    f_b = Fact("甲", "补偿金", 60.0, "60", "s2", "s2#p1", "2024-03-12T18:00:00")
    same = trace_ledger_collision(_collision("甲", "补偿金", [f_a, f_b]), index=2)
    assert same["conflict_class"] == "same_window"
    assert same["disposition"] == "undecided"


def test_c115_pair_disposition_dissent_and_tie():
    d_win, code, _ = disposition_of_pair({
        "id": "CFL-1", "a_id": "A", "b_id": "B",
        "resolution": {"winner_id": "A", "method": "evidence_weight"},
    })
    assert d_win == "dissent"
    assert code.startswith("resolved:")

    d_tie, code2, _ = disposition_of_pair({
        "id": "CFL-2", "a_id": "A", "b_id": "B",
        "resolution": {"winner_id": "tie", "method": "tie"},
    })
    assert d_tie == "undecided"
    assert code2 == "tie"
    assert DISPOSITIONS == {"keep", "dissent", "undecided"}


def test_c115_apply_writes_trace_no_coeff(monkeypatch):
    monkeypatch.setenv("VERITAS_CONFLICT_TRACE", "1")
    d = Dossier(question="测")
    facts = [
        Fact("甲", "补偿金", 49.4, "49.4万", "s1", "s1#p1", "2024-03-12"),
        Fact("甲", "补偿金", 60.0, "60万", "s2", "s2#p1", "2024-03-12"),
    ]
    cols = [_collision("甲", "补偿金", facts)]
    payload = apply_conflict_trace(d, collisions=cols, enabled=True)
    assert payload is not None
    assert audit_forbidden_keys(payload) == []
    for bad in FORBIDDEN_PACK_KEYS:
        assert bad not in payload
    assert "gold" not in payload and "gold_ids" not in str(payload)
    sm = payload["summary"]
    assert sm["n"] == 1
    assert sm["coverage_rate"] == 1.0
    assert sm["unclassified"] == 0
    assert sm["trace_complete_rate"] == 1.0
    assert d.accounting["conflict_trace"]["summary"]["classified"] == 1


def test_c115_summarize_coverage():
    rows = [
        {"id": "1", "source": "fact_ledger",
         "conflict_class": "same_window", "conflict_class_cn": "同窗对撞",
         "entry": {"entity": "a"}, "disposition": "undecided",
         "disposition_cn": "未决", "reason_code": "pick_side",
         "reason_short": "x"},
        {"id": "2", "source": "fact_ledger",
         "conflict_class": "unclassified", "conflict_class_cn": "未归类",
         "entry": {"entity": "b"}, "disposition": "undecided",
         "disposition_cn": "未决", "reason_code": "unclassified",
         "reason_short": "y"},
    ]
    sm = summarize_trace(rows)
    assert sm["coverage_rate"] == 0.5
    assert sm["unclassified"] == 1
    assert sm["trace_complete"] == 2
