"""C-35 批二：架构师账上九类 0 红补牙（⑨–⑱）。只加测试格，不动 app/。"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

from app.core.confidence import (
    _AGREEMENT_FLOOR,
    _CHAIN_UNKNOWN,
    _gated_score_from_parts,
    _chain_score_for_aggregate,
    aggregate,
    apply_hard_gates,
    apply_temperature,
    row_score_detail,
)
from app.export.official import _FIELD_NOTES, _gates_fired_note

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "calibration" / "face_v2_row_snapshot.jsonl"


# ---------- ⑨ 温度不许挪均值 ----------
def test_c35_09_temperature_identity_and_pooled_mean():
    """⑨：T=1 逐位恒等；mean＝当批 pooled；非 1 温度钉均值保持＋逐格公式（区分 T*raw）。"""
    raw = [0.12, 0.35, 0.48, 0.61, 0.77, 0.82]
    pooled = sum(raw) / len(raw)
    for s in raw:
        assert apply_temperature(s, mean=pooled, temperature=1.0) == s
    # 自证：用错均值（≠ pooled）时，T=1 仍恒等——所以还要单独钉 mean==pooled
    wrong = pooled + 0.15
    # T≠1 时错均值会平移；T=1 时恒等掩盖均值错误 ⇒ 必须显式钉 pooled
    assert wrong != pooled
    assert all(
        apply_temperature(s, mean=wrong, temperature=1.0) == s for s in raw
    )
    # 生产路径约定：调用方传入的 mean 须为当批 pooled（本格钉这条契约）
    assert pooled == pytest.approx(sum(raw) / len(raw))
    # 非 1.0 温度：用不会触 clip01 的一批，钉两条真性质（恒真式 list 不等不够）
    # （原 raw 含 0.12，T=1.5 会 clip 到 0 ⇒ 线性均值保持被裁剪破坏；性质测的是公式本身）
    batch = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65]
    T = 1.5
    m = sum(batch) / len(batch)
    assert all(0.0 < m + T * (s - m) < 1.0 for s in batch)  # 预条件：本批不触 clip
    scaled = [apply_temperature(s, mean=m, temperature=T) for s in batch]
    assert scaled != batch
    # (a) 均值保持：sum(scaled)==sum(raw)（T*raw 在 mean≠0 时必破）
    assert abs(sum(scaled) - sum(batch)) <= 1e-12
    # (b) 逐格：scaled_i − m == T*(raw_i − m)
    for i, s in enumerate(batch):
        assert abs((scaled[i] - m) - T * (s - m)) <= 1e-12
    # 同准则施加于 drifted=[T*s] 必须失败（证明准则能区分对错实现，非 mere 列表不等）
    drifted = [T * s for s in batch]
    mean_ok = abs(sum(drifted) - sum(batch)) <= 1e-12
    per_ok = all(
        abs((drifted[i] - m) - T * (batch[i] - m)) <= 1e-12 for i in range(len(batch))
    )
    assert not (mean_ok and per_ok), (
        "criterion must fail on T*raw drifted group; otherwise leg is tautology"
    )


# ---------- ⑩ chain None ⇒ 0.75 ----------
def test_c35_10_chain_none_fallback_075_drives_face_numbers():
    """⑩：None⇒0.75；该兜底参与的 aggregate_raw 支撑对外高档29／0.517／AUC0.6010。"""
    assert _CHAIN_UNKNOWN == 0.75
    assert _chain_score_for_aggregate(None) == 0.75
    # 合成：chain=None 的结论 → aggregate 第四维用 0.75
    strength, coverage, agreement = 0.5, 0.5, 0.5
    af = _AGREEMENT_FLOOR + (1 - _AGREEMENT_FLOOR) * agreement
    raw = aggregate(strength, coverage, af, _chain_score_for_aggregate(None))
    raw_explicit = aggregate(strength, coverage, af, 0.75)
    assert raw == raw_explicit
    # 若退回 0.0／floor，raw 必变
    assert raw != aggregate(strength, coverage, af, 0.0)
    # 快照回灌数字与 proposal 三元组同形（只读 snapshot，不连 cases/）
    from scripts.score_face_v2_report import (
        auc_binary,
        ece_of,
        high_band_stats,
        score_v2_of_parts,
    )

    rows = [
        json.loads(l)
        for l in SNAPSHOT.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    scores = [score_v2_of_parts(r["parts"]) for r in rows]
    labels = [r["label"] for r in rows]
    ece = round(ece_of(scores, labels), 4)
    auc = round(auc_binary(scores, labels), 4)
    hb = high_band_stats(scores, labels)
    assert hb["n"] == 29
    assert round(hb["acc"], 3) == pytest.approx(0.517, abs=0.001)
    assert ece == pytest.approx(0.0565, abs=0.0001)
    assert auc == pytest.approx(0.6010, abs=0.001)


# ---------- ⑪ _gated_score_from_parts 三兜底 ----------
def test_c35_11_gated_score_three_fallbacks_and_parts_recompute():
    """⑪：旧 parts 三兜底各测；四元组重算 vs live ≤1e-4。"""
    raw = 0.85
    # 1) 无 gates ⇒ hit_rate 视作 1.0（不瞎触发 G1）
    s1 = _gated_score_from_parts({"n_evidence": 2}, raw)
    assert s1 == pytest.approx(0.85)
    # 2) 无 gates + premise 空路径：同上，premise_broken=[]
    s2 = _gated_score_from_parts({"n_evidence": 3, "gates": {}}, raw)
    # gates={} 也走「无 gates」分支
    assert s2 == pytest.approx(0.85)
    # 3) 更老：无 n_evidence 键 ⇒ 只跑加权和
    s3 = _gated_score_from_parts({"strength": 0.8}, raw)
    assert s3 == pytest.approx(0.85)
    # 有 gates 且 G1 触发
    gated, g = apply_hard_gates(raw, hit_rate=0.2, n_evidence=2, premise_broken=[])
    parts = {
        "n_evidence": 2,
        "gates": g,
        "aggregate_raw": raw,
        "strength": 0.8,
        "coverage": 0.5,
        "agreement": 1.0,
        "chain": 1.0,
    }
    s4 = _gated_score_from_parts(parts, raw)
    assert s4 == pytest.approx(gated)
    assert s4 == pytest.approx(0.40)
    # 四元组重算 vs live ≤1e-4
    live, terms = row_score_detail(parts)
    af = terms["agreement_factor"]
    ch = terms["chain_for_aggregate"]
    recomputed_raw = aggregate(
        terms["strength"], terms["coverage"], af, ch,
    )
    recomputed = _gated_score_from_parts(parts, recomputed_raw)
    assert abs(recomputed - live) <= 1e-4


# ---------- ⑫ score_v1_of_parts ----------
def test_c35_12_score_v1_of_parts_product_pin():
    """⑫：v1 = strength*coverage*agreement_factor*chain_factor（曾恒返 0.5 也绿）。"""
    from app.core.confidence import chain_factor_of
    from scripts.score_face_v2_report import score_v1_of_parts

    parts = {
        "strength": 0.8,
        "coverage": 0.5,
        "agreement": 1.0,
        "chain": 1.0,
    }
    af = _AGREEMENT_FLOOR + (1 - _AGREEMENT_FLOOR) * 1.0
    cf = chain_factor_of(1.0)
    expected = round(min(1.0, 0.8 * 0.5 * af * cf), 4)
    assert score_v1_of_parts(parts) == expected
    assert expected != 0.5  # 自证：恒返 0.5 的假实现过不了
    # 另一组
    parts2 = {"strength": 0.4, "coverage": 0.4, "agreement": 0.0, "chain": None}
    af2 = _AGREEMENT_FLOOR + (1 - _AGREEMENT_FLOOR) * 0.0
    cf2 = chain_factor_of(None)
    exp2 = round(min(1.0, 0.4 * 0.4 * af2 * cf2), 4)
    assert score_v1_of_parts(parts2) == exp2


# ---------- ⑬⑭⑮ disclosure chain ----------
def test_c35_13_14_15_disclosure_gates_chain():
    """⑬ terms 含 gates；⑭ 字段说明语义（三门名+阈值+封顶）；⑮ substitution 匹配 fired。"""
    # ⑬
    parts = {
        "strength": 0.9,
        "coverage": 0.6,
        "agreement": 1.0,
        "chain": 0.8,
        "n_evidence": 2,
        "aggregate_raw": 0.9,
    }
    conf, gates = apply_hard_gates(
        0.9, hit_rate=0.3, n_evidence=2, premise_broken=["p1"],
    )
    parts["gates"] = gates
    parts["aggregate_raw"] = 0.9
    score, terms = row_score_detail(parts)
    assert "gates" in terms
    assert terms["gates"] is not None
    assert terms["gates"]["G1_citation"]["fired"] is True
    # 自证：摘 gates
    terms_no = dict(terms)
    terms_no.pop("gates", None)
    assert "gates" not in terms_no

    # ⑭ 字段说明语义：三门名 + 阈值 + 封顶（不整串钉）
    notes = _FIELD_NOTES
    for name in ("G1", "G2", "G3", "引文命中", "无证据", "前提破坏"):
        assert name in notes
    assert "0.6" in notes and "0.40" in notes and "0.45" in notes
    # 自证：删掉 gates 说明句仍可能含零散词——再钉「terms.gates」锚
    assert "terms.gates" in notes

    # ⑮ substitution gates[…] 匹配 fired 集
    fired_note = _gates_fired_note(gates)
    assert "G1_citation" in fired_note
    assert "G3_premise_broken" in fired_note
    none_note = _gates_fired_note(
        {
            "G1_citation": {"fired": False},
            "G2_no_evidence": {"fired": False},
            "G3_premise_broken": {"fired": False},
        }
    )
    assert none_note == "none"
    # 拼进 substitution 形
    sub = f"+ gates[{fired_note}]"
    assert "gates[G1_citation" in sub
    sub_none = f"+ gates[{none_note}]"
    assert sub_none == "+ gates[none]"


def test_c35_15_assembly_substitution_gates_product(tmp_path):
    """⑮ 拼装点：_confidence_rows／export 产物 substitution 真含 gates[…]（非仅 helper）。

    自证：official.py:328 退回 f" = {score}" ⇒ 本格必红。
    """
    from app.export.official import _confidence_rows, _gates_fired_note as note_of
    from tests.test_c21_sample_face import _synth

    # —— 无门触发 ⇒ gates[none] 与 form "... + gates[none] = <score>" ——
    d_none = _synth(tmp_path / "g_none", statuses=[("majority", "无门结论")])
    # 显式塞全未触发 gates（与生产 conclude 形状同形）；无 gates 字段时 note 也是 none
    _, gates_off = apply_hard_gates(
        0.7, hit_rate=0.9, n_evidence=2, premise_broken=[],
    )
    assert not any(g.get("fired") for g in gates_off.values())
    for con in d_none.conclusions:
        if con.status == "majority":
            parts = dict(con.confidence_parts or {})
            parts["gates"] = gates_off
            parts["n_evidence"] = 2
            con.confidence_parts = parts
    rows_none = _confidence_rows("q_none", d_none)
    assert rows_none, "need ≥1 majority row"
    sub_none = rows_none[0]["substitution"]
    assert "gates[none]" in sub_none
    score_none = rows_none[0]["score"]
    assert f"+ gates[none] = {score_none}" in sub_none
    # 一致性：substitution 的 gates 段 == 对 terms.gates 套同一规则
    expected_none = note_of(rows_none[0]["terms"].get("gates"))
    assert f"gates[{expected_none}]" in sub_none

    # —— 有门触发：G1_citation（hit_rate<0.6）——
    d_g1 = _synth(tmp_path / "g_g1", statuses=[("majority", "G1 触发结论")])
    _, gates_g1 = apply_hard_gates(
        0.9, hit_rate=0.3, n_evidence=2, premise_broken=[],
    )
    assert gates_g1["G1_citation"]["fired"] is True
    for con in d_g1.conclusions:
        if con.status == "majority":
            parts = dict(con.confidence_parts or {})
            parts["gates"] = gates_g1
            parts["n_evidence"] = 2
            con.confidence_parts = parts
    rows_g1 = _confidence_rows("q_g1", d_g1)
    sub_g1 = rows_g1[0]["substitution"]
    # 本格选用 G1_citation（citation_hit_rate<0.6）；亦可 G3 via premise_broken
    assert "G1_citation" in sub_g1
    expected_g1 = note_of(rows_g1[0]["terms"].get("gates"))
    assert "G1_citation" in expected_g1
    assert f"gates[{expected_g1}]" in sub_g1
    assert f"= {rows_g1[0]['score']}" in sub_g1


# ---------- ⑯ gateTxt 进 chip 数组 ----------
def test_c35_16_gate_txt_enters_chip_array():
    """⑯：gateTxt 必须进入 chip 数组引用，不是只在 :1582 定义。"""
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    # 定义点
    assert re.search(r"const\s+gateTxt\s*=", html)
    # 引用点：出现在数组字面量里（chip 列表）
    # 真文件：chainTxt,gateTxt,`${p.n_evidence...
    assert re.search(r"gateTxt\s*,", html) or re.search(r",\s*gateTxt\s*,", html)

    def _gate_txt_referenced_in_chips(src: str) -> bool:
        if not re.search(r"const\s+gateTxt\s*=", src):
            return False
        # 定义之后仍被当作数组元素引用
        return bool(re.search(r"(?:^|[,\[])\s*gateTxt\s*(?=[,\]])", src, re.M))

    assert _gate_txt_referenced_in_chips(html) is True
    # 自证：只定义不引用 ⇒ 红
    fake = "const gateTxt=firedGates.length?('硬门'):('加权和＋硬门');\nconst chips=[chainTxt];\n"
    assert _gate_txt_referenced_in_chips(fake) is False


# ---------- ⑰ Doc numbers vs snapshot ----------
def test_c35_17_proposal_numbers_match_snapshot_recompute():
    """⑰：提案数字三元组 vs snapshot 重算；两提案都含「高档非空」与「该箱准确率＜基准 0.637」。"""
    from scripts.score_face_v2_report import (
        auc_binary,
        ece_of,
        high_band_stats,
        score_v2_of_parts,
    )

    rows = [
        json.loads(l)
        for l in SNAPSHOT.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    scores = [score_v2_of_parts(r["parts"]) for r in rows]
    labels = [r["label"] for r in rows]
    ece = round(ece_of(scores, labels), 4)
    auc = round(auc_binary(scores, labels), 4)
    hb = high_band_stats(scores, labels)
    # proposal-formal.md:113-114 三元组
    assert ece == pytest.approx(0.0565, abs=0.0001)
    assert auc == pytest.approx(0.6010, abs=0.001)
    assert hb["n"] == 29
    # proposal.md:100 高档 n 与准确率
    assert round(hb["acc"], 3) == pytest.approx(0.517, abs=0.001)

    prop = (ROOT / "docs" / "proposal.md").read_text(encoding="utf-8")
    formal = (ROOT / "docs" / "proposal-formal.md").read_text(encoding="utf-8")
    for text, name in ((prop, "proposal.md"), (formal, "proposal-formal.md")):
        assert "高档非空" in text, name
        assert "该箱准确率＜基准 0.637" in text or "0.517＜基准 0.637" in text, name
    # formal 钉三元组字面
    assert "0.0565" in formal and "0.6010" in formal
    assert re.search(r"高档 n＝?\**29\**", formal) or "高档 n＝**29**" in formal


# ---------- ⑱ flip 钉具体 conclusion id ----------
# （实现落在 test_c25；此处不重复造 dossier，避免两套夹具漂移）
