"""C-155：消解类型时效性回填的守护格（零 LLM、零网络）。

钉三件事：
① 只补标签——winner／method／rationale／强度 一律不许被这条规则改动；
② 判据可核且保守——双侧时点都要解得出且集合不同才回填，任一解不出／相同／
   有胜方／非 tie ⇒ 一动不动（不许把「没判出来」粉饰成「按时效性消解」）；
③ 关旗同形——``set_enabled(False)`` 时记录逐字段不变（不写 sides_dates 新键）。
"""

from __future__ import annotations

import copy
import json

import pytest

from app.core.arbitration_face import arbitrate_light
from app.core.conflicts import (
    METHOD_TO_RESOLUTION_TYPE, _OFFICIAL_RESOLUTION_TYPES, _stamp,
)
from app.core.evidence import Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType
from app.core.resolution_time_type import (
    apply_tie_time_rule, enabled, set_enabled, side_day_keys, tie_time_signature,
)


def _dossier(day_a: str = "2026-03-05", day_b: str = "2026-07-01") -> Dossier:
    """两结论各挂一条证据，两侧信源时点由 meta 决定（解不出＝不给键）。"""
    d = Dossier(question="C-155 时效性回填夹具")
    specs = [("SRC-A", "CON-A", "EV-A", "doc_a#p1", day_a),
             ("SRC-B", "CON-B", "EV-B", "doc_b#p1", day_b)]
    for i, (src_id, con_id, ev_id, seg_id, day) in enumerate(specs):
        meta = {} if not day else {"publish_time": day}
        src = Source.create(f"信源{i}", SourceType.NOTE, id=src_id, meta=meta)
        src.segments.append(Segment(id=seg_id, source_id=src_id,
                                    text="同一指标的两个说法。", index=1))
        d.sources.append(src)
        con = Conclusion.create(f"结论{con_id}", author="mainstream")
        con.id = con_id
        con.status = "majority"
        d.conclusions.append(con)
        d.evidences.append(EvidenceNode(id=ev_id, conclusion_id=con_id,
                                        quote="同一指标的两个说法。",
                                        segment_ids=[seg_id]))
    return d


def _pair() -> dict:
    return {"id": "CFL-t1", "a_id": "CON-A", "b_id": "CON-B",
            "topic": "口径", "kind": "factual"}


def _res(winner: str = "tie", path: str = "tie") -> dict:
    return {"winner_id": winner, "method": "tie" if winner == "tie" else "arbitration",
            "rationale": "双方各自成立，保留分歧。",
            "decision_path": path,
            "basis": {"decision_path": path, "margin": 0.2, "strength_gap": 0.03,
                      "type_applies": "双方强度差 0.03 ≤ 0.20，无机械胜负",
                      "loser_excluded": "双方均未排除"},
            "restart_condition": "任一方补充新证据后即重启"}


# ---------------------------------------------------------------- ①／② 回填条件

def test_c155_tie_with_differing_dates_becomes_time_type():
    d, pair, res = _dossier(), _pair(), _res()
    assert apply_tie_time_rule(res, pair, d) is True
    assert res["resolution_type"] == "时效性"
    assert set(res["basis"]["sides_dates"]) == {"CON-A", "CON-B"}
    assert res["basis"]["sides_dates"]["CON-A"] == ["20260305"]
    assert "判据＝两侧信源时点不同" in res["basis"]["type_applies"]
    # loser_excluded 不该被重写：原「双方均未排除」本就读得通，改它只增字数
    assert res["basis"]["loser_excluded"] == "双方均未排除"


def test_c155_footprint_small_enough_not_to_evict_other_fields():
    """回填足迹必须小：导出侧单条 ≤800 字硬闸，字数一大就把同条的
    「冲突清单／rationale」挤掉＝为 3.3.2 的标签牺牲 3.3.1 的分面。"""
    d, pair = _dossier(), _pair()
    res = _res()
    before = copy.deepcopy(res)
    apply_tie_time_rule(res, pair, d)
    grew = (len(str(res["basis"]["type_applies"]))
            - len(str(before["basis"]["type_applies"])))
    assert grew <= 80, f"追加文案 {grew} 字＞80：会触发尺寸闸挤掉别的字段"
    assert len(json.dumps(res["basis"]["sides_dates"], ensure_ascii=False)) <= 120


def test_c155_result_stays_within_official_five():
    res = _res()
    apply_tie_time_rule(res, _pair(), _dossier())
    assert res["resolution_type"] in _OFFICIAL_RESOLUTION_TYPES
    assert res["resolution_type"] in (
        set(METHOD_TO_RESOLUTION_TYPE.values()) | {"时效性"})


@pytest.mark.parametrize("name,day_a,day_b,expect", [
    ("同一天不移", "2026-03-05", "2026-03-05", False),
    ("一侧无时点不移", "", "2026-07-01", False),
    ("两侧都无时点不移", "", "", False),
])
def test_c155_no_move_when_tell_absent(name, day_a, day_b, expect):
    d = _dossier(day_a=day_a, day_b=day_b)
    res = _res()
    before = copy.deepcopy(res)
    assert apply_tie_time_rule(res, _pair(), d) is expect, name
    assert res == before, f"{name}：判不到就一个字段都不许动"


def test_c155_winner_record_is_never_relabeled():
    """有胜方＝不是「双方均保留」，即使时点不同也不许落成时效性。"""
    d, pair = _dossier(), _pair()
    res = _res(winner="CON-A", path="llm_arbitration")
    res["resolution_type"] = "其他"
    assert apply_tie_time_rule(res, pair, d) is False
    assert res["resolution_type"] == "其他"


def test_c155_non_tie_path_untouched():
    d, pair = _dossier(), _pair()
    res = _res(winner="CON-A", path="strength")
    res["resolution_type"] = "语义可信度"
    assert apply_tie_time_rule(res, pair, d) is False
    assert res["resolution_type"] == "语义可信度"
    assert "sides_dates" not in res["basis"]


def test_c155_never_touches_winner_method_rationale_strength():
    """①的正面钉：只动 resolution_type 与 basis 两条文案，其余逐字段相等。"""
    d, pair = _dossier(), _pair()
    res = _res()
    before = copy.deepcopy(res)
    apply_tie_time_rule(res, pair, d)
    for key in ("winner_id", "method", "rationale", "restart_condition",
                "decision_path"):
        assert res[key] == before[key], key
    b0, b1 = before["basis"], res["basis"]
    for key in ("decision_path", "margin", "strength_gap"):
        assert b1[key] == b0[key], key
    moved = {k for k in b1 if b1[k] != b0.get(k)}
    assert moved == {"sides_dates", "type_applies"}, moved


def test_c155_idempotent_second_call_does_not_double_sentence():
    d, pair = _dossier(), _pair()
    res = _res()
    apply_tie_time_rule(res, pair, d)
    once = copy.deepcopy(res)
    assert apply_tie_time_rule(res, pair, d) is True
    assert res["basis"]["type_applies"] == once["basis"]["type_applies"]
    assert res == once


# ---------------------------------------------------------------- 关旗同形

def test_c155_flag_off_leaves_record_byte_identical():
    d, pair = _dossier(), _pair()
    res = _res()
    res["resolution_type"] = METHOD_TO_RESOLUTION_TYPE["tie"]
    before = copy.deepcopy(res)
    set_enabled(False)
    try:
        assert enabled() is False
        assert apply_tie_time_rule(res, pair, d) is False
        assert tie_time_signature(d, "CON-A", "CON-B") is None
    finally:
        set_enabled(True)
    assert res == before, "关旗＝逐字段同改前，且不许写 sides_dates 新键"
    assert enabled() is True, "旗位必须复位，别把测试污染成常开"


def test_c155_default_is_on_and_env_can_switch(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("VERITAS_RESOLUTION_TYPE_TIME", raising=False)
    assert Settings.from_env().resolution_type_time is True
    monkeypatch.setenv("VERITAS_RESOLUTION_TYPE_TIME", "0")
    assert Settings.from_env().resolution_type_time is False
    monkeypatch.setenv("VERITAS_RESOLUTION_TYPE_TIME", "1")
    assert Settings.from_env().resolution_type_time is True


def test_c155_config_json_key_switches(monkeypatch, tmp_path):
    from app.config import Settings

    monkeypatch.delenv("VERITAS_RESOLUTION_TYPE_TIME", raising=False)
    cfg = tmp_path / "config.json"
    cfg.write_text('{"resolution_type_time": false}', encoding="utf-8")
    assert Settings.from_json(cfg).resolution_type_time is False


# ---------------------------------------------------------------- 接线（真函数）

def test_c155_stamp_wires_the_rule():
    """``_stamp`` 走真路：tie 分支结束后类型应已回填。"""
    from app.core.conflicts import Resolution

    d = _dossier()

    class _P:
        a_id, b_id = "CON-A", "CON-B"

    res = Resolution(winner_id="tie", method="tie", rationale="保留分歧")
    _stamp(res, _P(), d, "tie", {}, [])
    assert res.resolution_type == "时效性"
    assert res.basis["sides_dates"]["CON-B"] == ["20260701"]


def test_c155_light_arbitration_shares_the_same_rule():
    """C-148 轻裁（双方保留）与 _stamp 同一条腿，不另起判据。"""
    from app.core.conflicts import ConflictPair

    d = _dossier()
    pair = ConflictPair(id="CFL-l1", a_id="CON-A", b_id="CON-B",
                        topic="口径", description="同一指标两种说法")
    route_row = {"triage_class": "date_offset", "triage_reason_code": "rc",
                 "triage_reason_short": "时点不同", "route": "light_program"}
    res = arbitrate_light(pair, d, {}, route_row)
    assert res.resolution_type == "时效性"
    assert res.winner_id == "tie", "轻裁仍不判谁错"


def test_c155_pipeline_anchors_both_setter_sites():
    """接线锚定格（本仓惯例＝源码锚点，不是行为格）：两条管线入口都要把
    Settings 落到模块旗。少一处＝那条入口下关旗失效（默认开改不动）。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "pipeline.py").read_text(
        encoding="utf-8")
    assert src.count("resolution_type_time") >= 2, "run_case 与 run_official_case 各一处"
    assert src.count("set_res_type_time(bool(getattr") >= 2


def test_c155_side_day_keys_uses_repo_normalizer():
    d = _dossier(day_a="2026-03", day_b="2026-07-01")
    keys = side_day_keys(d, "CON-A")
    # 仓内口径＝月粒度得 202603（6 位），不许回退成 4 位年；日粒度 8 位
    assert keys == ["202603"], keys
    assert side_day_keys(d, "CON-B") == ["20260701"]
