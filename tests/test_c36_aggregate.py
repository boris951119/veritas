"""C-36：加权和＋硬门合式、温度单调不变性、同分退化、同源对表。"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from app.core.confidence import (
    _AGG,
    _CAUSATION_BONUS,
    aggregate,
    apply_hard_gates,
    apply_temperature,
    conclude_confidence,
    row_score_of,
)
from app.core.evidence import LEVEL_WEIGHT, EvidenceLevel
from tests.test_confidence import _add, _dossier


# ---------- (a) aggregate 数值钉死 ----------
def test_a_aggregate_numeric_pin():
    """给定四分量 ⇒ 分数逐位；偷改 _AGG 权重必红。"""
    assert _AGG["b"] == 0.10
    assert _AGG["s"] == 0.25
    assert _AGG["c"] == 0.20
    assert _AGG["a"] == 0.15
    assert _AGG["h"] == 0.30
    # 0.10 + 0.25*0.8 + 0.20*0.5 + 0.15*1.0 + 0.30*1.0 = 0.85
    assert aggregate(0.8, 0.5, 1.0, 1.0) == pytest.approx(0.85)
    assert aggregate(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.10)
    assert aggregate(1.0, 1.0, 1.0, 1.0) == pytest.approx(1.0)
    # clip
    assert aggregate(2.0, 2.0, 2.0, 2.0) == 1.0


# ---------- (b) 三道门各一颗有牙＋摘门必红 ----------
def _conf_with_gates(**gate_kwargs):
    """允许测试把 apply_hard_gates 换掉以做摘门自证。"""
    return apply_hard_gates(0.85, **gate_kwargs)


def test_b_g1_citation_gate_has_teeth():
    d, sid = _dossier(0.8)
    _add(d, sid)
    conf_ok, parts_ok = conclude_confidence("CON1", d)
    assert conf_ok == pytest.approx(0.85)
    assert parts_ok["gates"]["G1_citation"]["fired"] is False

    ev = d.evidences_of("CON1")[0]
    ev.quote = "这段引文绝对不在来源段落里_C36_G1_UNIQUE"
    conf_bad, parts_bad = conclude_confidence("CON1", d)
    assert parts_bad["gates"]["G1_citation"]["fired"] is True
    assert conf_bad == pytest.approx(_AGG["g1_cap"])
    assert conf_bad < conf_ok

    # 摘门自证：把 G1 阈值放到 0 ⇒ 永不触发 ⇒ 本格必须能红（用直接调用）
    raw = 0.85
    conf_ungated, g = apply_hard_gates(
        raw, hit_rate=0.0, n_evidence=1, premise_broken=[],
    )
    # 正常有牙
    assert g["G1_citation"]["fired"] is True
    assert conf_ungated == pytest.approx(0.40)
    # 摘掉：阈值放宽到 0（hit_rate < 0 才触发）⇒ 不封顶
    saved = _AGG["g1_hit_rate_min"]
    try:
        _AGG["g1_hit_rate_min"] = 0.0
        conf_loose, g2 = apply_hard_gates(
            raw, hit_rate=0.0, n_evidence=1, premise_broken=[],
        )
        assert g2["G1_citation"]["fired"] is False
        assert conf_loose == pytest.approx(0.85)
        # 反假绿：若有人把本断言改成只看 fired 而忽略阈值，下面必红
        assert conf_loose > conf_ungated
    finally:
        _AGG["g1_hit_rate_min"] = saved


def test_b_g2_no_evidence_gate_has_teeth():
    d, sid = _dossier(0.8)
    conf, parts = conclude_confidence("MISSING", d)
    assert conf == 0.0
    assert parts["gates"]["G2_no_evidence"]["fired"] is True
    # 摘门：若跳过 n_evidence 检查，apply_hard_gates 在 n>0 时不归零
    c_ok, g_ok = apply_hard_gates(
        0.85, hit_rate=1.0, n_evidence=1, premise_broken=[],
    )
    assert g_ok["G2_no_evidence"]["fired"] is False
    assert c_ok == pytest.approx(0.85)
    c_zero, g_zero = apply_hard_gates(
        0.85, hit_rate=1.0, n_evidence=0, premise_broken=[],
    )
    assert g_zero["G2_no_evidence"]["fired"] is True
    assert c_zero == 0.0
    assert c_zero < c_ok  # 摘掉 G2 分支会使 c_zero 变回 0.85 ⇒ 本行红


def test_b_g3_premise_broken_gate_has_teeth():
    d, sid = _dossier(0.8)
    _add(d, sid)
    d.conclusion("CON1").premise_broken = ["CON-UPSTREAM"]
    conf, parts = conclude_confidence("CON1", d)
    assert parts["gates"]["G3_premise_broken"]["fired"] is True
    assert conf == pytest.approx(_AGG["g3_cap"])
    # 摘门：cap 放到 1.0 ⇒ 封顶不生效
    saved = _AGG["g3_cap"]
    try:
        _AGG["g3_cap"] = 1.0
        c_loose, g = apply_hard_gates(
            0.85, hit_rate=1.0, n_evidence=1, premise_broken=["X"],
        )
        assert g["G3_premise_broken"]["fired"] is True
        assert c_loose == pytest.approx(0.85)
        assert c_loose > conf
    finally:
        _AGG["g3_cap"] = saved


# ---------- (c) T 单调变换 ⇒ 排序与 AUC 不变 ----------
def _auc_pairwise(scores: list[float], labels: list[str]) -> float:
    """对 vs 错 AUC（与架构师 0.594542 口径一致：只取对/错对）。"""
    pos = [s for s, y in zip(scores, labels) if y == "对"]
    neg = [s for s, y in zip(scores, labels) if y == "错"]
    if not pos or not neg:
        return float("nan")
    total = 0
    good = 0.0
    for p in pos:
        for n in neg:
            total += 1
            if p > n:
                good += 1.0
            elif p == n:
                good += 0.5
    return good / total


def test_c_temperature_preserves_ranking_and_auc():
    """T 是单调变换 ⇒ 排序与 AUC 逐位不变（钉 ~0.594542 不变性形状）。

    分数须远离 0/1，否则 clip01 会把两端压扁、破坏序与 AUC。
    """
    raw = [0.35 + 0.003 * i for i in range(100)]  # 0.35–0.647，T≤1.3 不触边
    # 分数升序；前 60 标「对」、后 40 标「错」⇒ AUC 明显高于 0.5
    labels = ["错"] * 35 + ["对"] * 5 + ["错"] * 5 + ["对"] * 55  # 大体低分=错、高分=对，夹杂若干
    assert len(labels) == 100
    base_auc = _auc_pairwise(raw, labels)
    mean = sum(raw) / len(raw)
    for tval in (0.7, 0.85, 1.0, 1.15, 1.3):
        scaled = [apply_temperature(s, mean=mean, temperature=tval) for s in raw]
        assert all(0.0 < x < 1.0 for x in scaled)  # 未触 clip
        order_raw = sorted(range(len(raw)), key=lambda i: raw[i])
        order_t = sorted(range(len(scaled)), key=lambda i: scaled[i])
        assert order_raw == order_t
        assert _auc_pairwise(scaled, labels) == pytest.approx(base_auc)
    assert 0.5 < base_auc <= 1.0


def _reverse_pair_count(a: list[float], b: list[float]) -> int:
    """成对逆序数：a[i]<a[j] 但 b[i]>b[j]（或反向）计 1；平局不计。"""
    n = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            da = a[i] - a[j]
            db = b[i] - b[j]
            if da == 0 or db == 0:
                continue
            if (da > 0) != (db > 0):
                n += 1
    return n


def test_c_architect_auc_invariance_pin():
    """T 单调变换不改 AUC／逆序＝**合成数据腿**（零产品触碰；干净克隆可绿）。

    226 行回灌 AUC≈0.601 见 `test_c_face_v2_auc_from_snapshot_or_skip`
    （读仓内 snapshot；无则 skip＋披露原因）——不再去连 .gitignore 内的
    `cases/*/out*/report.json`（#99 同族第二次／R-C36-1）。
    """
    # 自制分数＋标签；远离 0/1，T∈[0.7,1.3] 不触 clip01
    raw = [0.28 + 0.005 * i for i in range(60)]  # 0.28–0.575
    labels = (
        ["错"] * 12 + ["对"] * 3 + ["错"] * 5 + ["对"] * 20
        + ["错"] * 8 + ["对"] * 12
    )
    assert len(labels) == 60
    auc0 = _auc_pairwise(raw, labels)
    assert 0.5 < auc0 <= 1.0
    mean = sum(raw) / len(raw)
    for tval in (0.7, 0.85, 1.0, 1.15, 1.3):
        scaled = [apply_temperature(s, mean=mean, temperature=tval) for s in raw]
        assert all(0.0 < x < 1.0 for x in scaled)
        auc_t = _auc_pairwise(scaled, labels)
        # 逐位 bit-identical（abs=1e-9）
        assert auc_t == pytest.approx(auc0, abs=1e-9)
        # 成对逆序数＝0
        assert _reverse_pair_count(raw, scaled) == 0


def test_c_face_v2_auc_from_snapshot_or_skip():
    """226 行回灌 AUC≈0.601：读仓内 `calibration/face_v2_row_snapshot.jsonl`。

    无 snapshot（干净克隆未带、或尚未跑 score_face）⇒ skip 并披露原因；
    **不**去连未入库的 cases/*/out*/report.json。
    """
    from pathlib import Path
    import json

    snap = Path(__file__).resolve().parents[1] / "calibration" / "face_v2_row_snapshot.jsonl"
    if not snap.is_file():
        pytest.skip(
            "calibration/face_v2_row_snapshot.jsonl 未入库；"
            "226 回灌 AUC 依赖该 snapshot（由 scripts/score_face_v2_report.py "
            "默认写出）或本机 cases/*/out*/report.json（.gitignore 内，"
            "干净克隆不可见）——R-C36-1 披露"
        )
    rows = [json.loads(line) for line in snap.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 226, f"snapshot 行数 {len(rows)} ≠ 226"
    v2 = [float(r["score_v2"]) for r in rows]
    labels = [r["label"] for r in rows]
    auc0 = _auc_pairwise(v2, labels)
    # 同码回灌先验 ≈0.60104；容差覆盖架构师先验 0.594542
    assert auc0 == pytest.approx(0.60104, abs=0.02)


# ---------- (d) 同分退化判不合格（哪怕 ECE=0） ----------
def test_d_constant_prediction_fails_degeneracy():
    from scripts.fit_temperature import degeneracy_check, ece_of
    from scripts.calibrate_confidence import label_accuracy

    # 构造：分数全等于标签准确率均值 ⇒ ECE≈0，但仍是同分退化
    labels = ["对"] * 32 + ["部分"] * 10 + ["错"] * 8
    mean_acc = sum(label_accuracy(y) for y in labels) / len(labels)
    scores = [mean_acc] * len(labels)
    ece = ece_of(scores, labels)
    assert ece == pytest.approx(0.0, abs=1e-9)
    ok, reason = degeneracy_check(scores)
    assert ok is False
    assert any(k in reason for k in ("同分", "退化", "常数", "唯一"))


# ---------- (e) row_score_of ↔ conclude_confidence 同源 ----------
def test_e_row_score_conclude_homology():
    d, sid = _dossier(0.8)
    _add(d, sid)
    conf, parts = conclude_confidence("CON1", d)
    assert row_score_of(parts) == conf
    # 再造一条两证据
    _add(d, sid, cid="CON1")
    conf2, parts2 = conclude_confidence("CON1", d)
    assert row_score_of(parts2) == conf2
    # G1 触发后仍同源
    d.evidences_of("CON1")[0].quote = "not-in-source_C36_homolog"
    conf3, parts3 = conclude_confidence("CON1", d)
    assert parts3["gates"]["G1_citation"]["fired"] is True
    assert row_score_of(parts3) == conf3


# ---------- 冻结面未动 ----------
def test_frozen_level_weight_and_causation_bonus():
    assert _CAUSATION_BONUS == 1.15
    assert LEVEL_WEIGHT[EvidenceLevel.A] == 1.0
    assert LEVEL_WEIGHT[EvidenceLevel.B] == 0.8
    assert LEVEL_WEIGHT[EvidenceLevel.C] == 0.55
    assert LEVEL_WEIGHT[EvidenceLevel.D] == 0.3
