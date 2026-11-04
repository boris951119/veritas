"""C-158：加分 4.1 因果面（三档判定机械派生＋等级带到因果面）。零 LLM、零网络。

钉四条：
① 三档判定只从已有结构化字段派生，填满卡也不许无据升档（不许硬编）；
② 判到「仅相关」时理由必须点名缺哪几项，升档条件＝真缺项清单；
③ 导出面每行判定／理由／升档条件／等级在场，且等级沿用同一 `level_official_of`；
④ 四要素仍为空＝本刀没造内容（这是预期，不是失败）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.causal_claim import (
    VERDICT_CORRELATION, VERDICT_DIRECT, VERDICT_INDIRECT, VERDICT_VALUES,
    verdict_of,
)
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, RelationKind, Segment,
    Source, SourceType,
)
from app.export.official import _FIELD_NOTES, export_official, level_official_of

_FULL = {
    "intervention": "涂覆界面缓冲层",
    "outcome": "中试良率提升",
    "population": "全固态电芯产线",
    "counterfactual": "若不涂覆则良率仍不足百分之四十",
}


def _ev(**kw) -> EvidenceNode:
    base = dict(id="EV-1", conclusion_id="CON-A", quote="涂覆后良率上升",
                segment_ids=["doc_001#p1"],
                relation=RelationKind.CORRELATION, level=EvidenceLevel.B)
    base.update(kw)
    return EvidenceNode(**base)


# ------------------------------------------------------------------ ① 三档派生

def test_verdict_direct_needs_full_card_and_kept_causation():
    ev = _ev(relation=RelationKind.CAUSATION, declared_relation="causation",
             causal_claim=dict(_FULL), mechanism_completeness="direct",
             design_tier="quasi")
    out = verdict_of(ev)
    assert out["因果判定"] == VERDICT_DIRECT
    assert out["判定理由"] and out["升档条件"] == "已达标，无需升档"


def test_verdict_indirect_names_missing_link():
    ev = _ev(relation=RelationKind.CAUSATION, declared_relation="causation",
             causal_claim=dict(_FULL), mechanism_completeness="indirect",
             missing_links=["mediator"])
    out = verdict_of(ev)
    assert out["因果判定"] == VERDICT_INDIRECT
    assert "缺中介" in out["判定理由"], out["判定理由"]


def test_verdict_empty_card_is_correlation_not_invented():
    ev = _ev(relation=RelationKind.CORRELATION, declared_relation="causation",
             degraded_reason="缺主张卡要素：intervention、outcome、population、counterfactual")
    out = verdict_of(ev)
    assert out["因果判定"] == VERDICT_CORRELATION
    assert "intervention" in out["判定理由"]
    assert "补齐主张卡缺项" in out["升档条件"]
    # 四要素没填＝判不到高档，这是「无依据不硬编」的正身
    assert out["因果判定"] != VERDICT_DIRECT


def test_verdict_never_upgrades_merely_by_filling_card():
    """卡填满但自述 correlation_only ⇒ 仍是仅相关（升档要机制自述，不是字数）。"""
    ev = _ev(relation=RelationKind.CAUSATION, declared_relation="causation",
             causal_claim=dict(_FULL), mechanism_completeness="correlation_only")
    assert verdict_of(ev)["因果判定"] == VERDICT_CORRELATION


def test_verdict_undeclared_correlation_reads_undeclared():
    ev = _ev(relation=RelationKind.CORRELATION)
    out = verdict_of(ev)
    assert out["因果判定"] == VERDICT_CORRELATION
    assert "未声明因果关系" in out["判定理由"]


def test_verdict_values_are_closed_set():
    combos = [
        _ev(),
        _ev(relation=RelationKind.CAUSATION, declared_relation="causation"),
        _ev(causal_claim=dict(_FULL), mechanism_completeness="indirect",
            relation=RelationKind.CAUSATION, declared_relation="causation"),
        _ev(missing_links=["temporal", "contrast"],
            mechanism_completeness="indirect",
            relation=RelationKind.CAUSATION, declared_relation="causation",
            causal_claim=dict(_FULL)),
    ]
    assert {verdict_of(e)["因果判定"] for e in combos} <= set(VERDICT_VALUES)
    assert VERDICT_VALUES == ("直接因果", "间接传导", "仅相关")


# ------------------------------------------------------------------ ③ 导出面

def _dossier_with_causation_row() -> tuple[Dossier, dict]:
    d = Dossier(question="C-158 因果面夹具")
    src = Source.create("官方通报", SourceType.WEB, id="SRC-1",
                        meta={"doc_id": "doc_001", "official": True,
                              "publish_time": "2026-08-26"})
    src.segments.append(Segment(id="doc_001#p1", source_id="SRC-1",
                                text="涂覆后中试良率上升。", index=1,
                                locator="doc_001#p1"))
    d.sources.append(src)
    con = Conclusion.create("涂覆界面缓冲层使中试良率提升", author="mainstream")
    con.id = "CON-A"
    con.status = "majority"
    d.conclusions.append(con)
    ev = _ev(relation=RelationKind.CORRELATION, declared_relation="causation",
             level=EvidenceLevel.A,
             degraded_reason="缺主张卡要素：intervention、outcome、population、counterfactual")
    d.evidences.append(ev)
    return d, {"question_id": "q_001", "question": "良率提升的原因是什么"}


def test_export_rows_carry_verdict_level_and_no_invented_card(tmp_path):
    d, question = _dossier_with_causation_row()
    export_official([(question, d)], tmp_path)
    rows = json.loads((tmp_path / "causal_evidence.json").read_text(
        encoding="utf-8"))
    assert len(rows) == 1
    r = rows[0]
    assert r["因果判定"] == VERDICT_CORRELATION
    assert r["判定理由"].strip() and r["升档条件"].strip()
    assert r["证据等级"] == "A"
    assert r["证据等级_官方"] == level_official_of("A"), "等级名必须走同一个函数"
    assert "LEVEL_WEIGHT" in r["等级参与加权"]
    # ④ 本刀不造内容：四要素仍为空
    for k in ("intervention", "outcome", "population", "counterfactual"):
        assert r[k] == "", f"{k} 被硬编了＝必须红"


def test_field_notes_document_the_three_way_and_no_new_judgement():
    assert "因果判定｜判定理由｜升档条件" in _FIELD_NOTES
    assert "verdict_of" in _FIELD_NOTES
    assert "等级参与加权" in _FIELD_NOTES
    assert "不新造判定" in _FIELD_NOTES, "边界句必须在场（判据只读已有字段）"


def test_probe_ruler_reads_same_face(tmp_path):
    """判尺腿与导出面同源：脚本读的键与代码写的键必须同名（防口径漂）。"""
    from scripts.probe_c158_causal_face import score_rows

    d, question = _dossier_with_causation_row()
    export_official([(question, d)], tmp_path)
    rows = json.loads((tmp_path / "causal_evidence.json").read_text(
        encoding="utf-8"))
    sc = score_rows(rows)
    assert sc["n_rows"] == 1
    assert sc["因果判定在场"] == 1 and sc["判定理由非空"] == 1
    assert sc["三档分布"][VERDICT_CORRELATION] == 1
    assert sc["四要素任一非空"] == 0, "判尺也必须看到「没填」"
    assert Path(__file__).resolve().parents[1].exists()
