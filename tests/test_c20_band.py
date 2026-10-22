"""C-20：band／band_rel 呈现层——判据 a–k＋第二轮 l1–l4／m1–m4（固定 id 合成案卷）。"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import statistics
from pathlib import Path

import pytest

from app.core.confidence import (
    _BAND_HIGH,
    _BAND_MID,
    _BAND_REL_EPS,
    band_count_dict,
    band_of,
    band_rel_cuts,
    band_rel_of,
    band_rel_rule_of,
    conclude_confidence,
    row_score_of,
)
from app.core.evidence import Conclusion, EvidenceLevel, EvidenceNode
from app.core.hashchain import HashChain
from app.export.official import export_official
from app.ingest.official_case import load_official_case
from app.pipeline import render_report_md
from scripts.score_official import score_submission
from tests.test_confidence import _add, _dossier
from tests.test_official_roundtrip import _para, _write_docs

ROOT = Path(__file__).resolve().parents[1]
SLOT_NOTE = "议题槽位未齐，未发起模型研判"
SCORES_A = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
_BANDS3 = {"高", "中", "低"}
_BANDS4 = {"高", "中", "低", "不可分"}


def _parts_for_score(score: float) -> dict:
    """反解 v2 加权和：构造 parts 使 row_score_of(parts) 逐位等于 target（agreement=1）。

    可表达下界＝0.25（af=1 且 s=c=h=0）；上界＝1.0。C-36 后不再有 strength≈score 的乘性捷径。
    """
    t = float(score)
    if t < 0.25 - 1e-12:
        raise ValueError(f"v2 加权和在 agreement=1 下无法表达 score<{0.25}: {t}")
    # t = 0.25 + 0.25*s + 0.20*c + 0.30*h  (af=1)
    if t <= 0.50 + 1e-12:
        s = (t - 0.25) / 0.25
        return {"strength": s, "coverage": 0.0, "agreement": 1.0, "chain": 0.0}
    if t <= 0.80 + 1e-12:
        h = (t - 0.50) / 0.30
        return {"strength": 1.0, "coverage": 0.0, "agreement": 1.0, "chain": h}
    c = (t - 0.80) / 0.20
    return {"strength": 1.0, "coverage": c, "agreement": 1.0, "chain": 1.0}


def _synth_dossier(tmp_path: Path, *, n_majority: int = 3, parts_list=None,
                   extra_conclusions: list | None = None):
    """固定 id 合成案卷；默认 3 条 majority，parts 可逐条覆盖。"""
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    content = "能量密度显著高于液态锂离子电池，客户回款率下降。"
    case = _write_docs(tmp_path, [{
        "doc_id": "doc_1",
        "title": "t",
        "publish_time": "2024-01-02",
        "content": content,
        "source_credibility": 0.5,
        "content_url": "",
        "paragraphs": [_para("para_9", 0, len(content))],
    }])
    dossier = load_official_case(case)
    # v2 加权和下这些分量会落到 0.25／0.30／0.40…（高档空）；旧乘性默认 0.4/0.5/… 在 v2 会误进高档
    defaults = [
        {"strength": 0.0, "coverage": 0.0, "agreement": 1.0, "chain": 0.0},  # 0.25
        {"strength": 0.2, "coverage": 0.0, "agreement": 1.0, "chain": 0.0},  # 0.30
        {"strength": 0.6, "coverage": 0.0, "agreement": 1.0, "chain": 0.0},  # 0.40
        {"strength": 0.0, "coverage": 0.0, "agreement": 1.0, "chain": 0.0},  # 0.25
        {"strength": 0.4, "coverage": 0.0, "agreement": 1.0, "chain": 0.0},  # 0.35
    ]
    plist = list(parts_list) if parts_list is not None else defaults[:n_majority]
    for i, parts in enumerate(plist[:n_majority], start=1):
        cid = f"CON-{i}"
        con = Conclusion.create(f"结论{i}", author="m", id=cid)
        con.confidence_parts = dict(parts)
        con.confidence = row_score_of(parts)
        dossier.conclusions.append(con)
        dossier.add_evidence(EvidenceNode.create(
            cid, "能量密度显著高于液态锂离子电池", ["para_9"],
            level=EvidenceLevel.B, id=f"EV-{i}"))
    for j, spec in enumerate(extra_conclusions or [], start=1):
        cid = spec.get("id") or f"CON-X{j}"
        con = Conclusion.create(spec.get("statement") or f"异议{j}",
                                author="d", id=cid)
        con.status = spec.get("status") or "dissent"
        parts = dict(spec.get("parts") or {})
        con.confidence_parts = parts
        con.confidence = row_score_of(parts)
        dossier.conclusions.append(con)
    return dossier


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strip_band_keys(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        d = {k: v for k, v in r.items()
             if k not in ("band", "band_rule", "band_rel", "band_rel_rule")}
        out.append(d)
    return out


# ---------- a ----------
def test_a_band_of_boundaries():
    assert band_of(1.0) == "高"
    assert band_of(0.8) == "高"
    assert band_of(0.7999) == "中"
    assert band_of(0.5) == "中"
    assert band_of(0.4999) == "低"
    assert band_of(0.0) == "低"
    assert _BAND_HIGH == 0.8 and _BAND_MID == 0.5


def test_a_band_rel_fixed_list_and_small_sample():
    cuts = band_rel_cuts(SCORES_A)
    assert cuts is not None
    lo, hi = cuts
    assert lo == pytest.approx(0.372, abs=1e-9)
    assert hi == pytest.approx(0.636, abs=1e-9)
    assert round(lo, 4) == 0.372 and round(hi, 4) == 0.636
    assert band_rel_of(SCORES_A, 0.90) == "高"
    assert band_rel_of(SCORES_A, 0.50) == "中"
    assert band_rel_of(SCORES_A, 0.40) == "中"
    assert band_rel_of(SCORES_A, 0.30) == "低"
    assert band_rel_of(SCORES_A, 0.10) == "低"
    bands = {band_rel_of(SCORES_A, s) for s in SCORES_A}
    assert bands == {"高", "中", "低"}
    assert band_rel_of([0.5], 0.5) == "低"
    with pytest.raises(statistics.StatisticsError):
        statistics.quantiles([0.5], n=100, method="inclusive")


# ---------- b ----------
def test_b_export_rows_self_consistent(tmp_path):
    d = _synth_dossier(tmp_path / "b", n_majority=3)
    paths = export_official(
        [({"question_id": "q1", "question": "能量密度是否占优？"}, d)],
        tmp_path / "b_out",
    )
    rows = json.loads(paths["confidence"].read_text(encoding="utf-8"))
    assert len(rows) == 3
    scores = [float(r["score"]) for r in rows]
    for r in rows:
        for k in ("band", "band_rule", "band_rel", "band_rel_rule"):
            assert k in r
        assert r["band"] in _BANDS3
        assert r["band_rel"] in _BANDS4
        assert r["band"] == band_of(float(r["score"]))
        assert r["band_rel"] == band_rel_of(scores, float(r["score"]))
        assert "quantiles n=100 method=inclusive" in r["band_rel_rule"]
        assert f"pooled 样本数={len(scores)}" in r["band_rel_rule"]


# ---------- c ----------
def test_c_empty_high_band_visible(tmp_path):
    d = _synth_dossier(tmp_path / "c0", n_majority=3)
    md = render_report_md(d, HashChain(), [])
    assert "高置信（≥0.8）：0 条" in md
    assert "本案卷 3 条" in md
    assert "相对档 band_rel" in md


def test_c_high_band_via_parts_not_conclude(tmp_path):
    parts = [{"strength": 1.0, "coverage": 1.0, "agreement": 1.0, "chain": 1.0},
             {"strength": 0.4, "coverage": 0.5, "agreement": 1.0, "chain": 1.0},
             {"strength": 0.3, "coverage": 0.5, "agreement": 1.0, "chain": 1.0}]
    assert row_score_of(parts[0]) == 1.0
    d = _synth_dossier(tmp_path / "c1", n_majority=3, parts_list=parts)
    md = render_report_md(d, HashChain(), [])
    assert "高置信（≥0.8）：0 条" not in md
    assert re.search(r"高置信（≥0\.8）：[1-9]\d* 条", md)


def test_c_band_rel_high_nonempty(tmp_path):
    d = _synth_dossier(tmp_path / "c2", n_majority=3)
    md = render_report_md(d, HashChain(), [])
    m = re.search(r"相对档 band_rel[^：]*：高：(\d+) 条", md)
    assert m and int(m.group(1)) >= 1


# ---------- d ----------
def test_d_judgment_unchanged_sha_and_score(tmp_path):
    d = _synth_dossier(tmp_path / "d", n_majority=3)
    paths = export_official(
        [({"question_id": "q1", "question": "能量密度是否占优？"}, d)],
        tmp_path / "d_out",
    )
    conf = json.loads(paths["confidence"].read_text(encoding="utf-8"))
    stripped = _strip_band_keys(conf)
    paths2 = export_official(
        [({"question_id": "q1", "question": "能量密度是否占优？"}, d)],
        tmp_path / "d_out2",
    )
    conf2 = json.loads(paths2["confidence"].read_text(encoding="utf-8"))
    a = json.dumps(_strip_band_keys(conf), ensure_ascii=False, sort_keys=True)
    b = json.dumps(_strip_band_keys(conf2), ensure_ascii=False, sort_keys=True)
    assert hashlib.sha256(a.encode()).hexdigest() == hashlib.sha256(b.encode()).hexdigest()
    for r in stripped:
        assert "band" not in r and "band_rel" not in r

    # 结构守护：评分器形参／全文均不含 confidence（换分 0 的机械根）
    params = inspect.signature(score_submission).parameters
    assert "confidence" not in params
    src = (ROOT / "scripts" / "score_official.py").read_text(encoding="utf-8")
    assert src.count("confidence") == 0


# ---------- e ----------
def test_e_formula_numeric_nails():
    """五个 C-36 v2 加权和实测值写死；偷改 _AGG／_CAUSATION_BONUS／摘 clip 钳位必须红。"""
    # af=1, chain=1, cov=0.5 → raw = 0.10+0.25*st+0.20*0.5+0.15+0.30 = 0.65+0.25*st
    d, sid = _dossier(0.8)
    _add(d, sid)
    conf, parts = conclude_confidence("CON1", d)
    assert conf == 0.85
    assert parts["strength"] == 0.8
    assert parts["coverage"] == 0.5
    assert parts["agreement"] == 1.0
    assert parts["chain"] == 1.0

    d, sid = _dossier(0.8)
    _add(d, sid)
    _add(d, sid, cid="CON1")
    conf, parts = conclude_confidence("CON1", d)
    assert conf == 0.8783  # 0.10+0.25*0.8+0.20*0.6417+0.15+0.30
    assert parts["strength"] == 0.8
    assert parts["coverage"] == 0.6417
    assert parts["agreement"] == 1.0
    assert parts["chain"] == 1.0

    from app.core.evidence import RelationKind
    d, sid = _dossier(0.8)
    _add(d, sid, relation=RelationKind.CAUSATION, note="接口缺失导致进度滞后")
    conf, parts = conclude_confidence("CON1", d)
    assert conf == 0.88  # strength 0.92
    assert parts["strength"] == 0.92
    assert parts["coverage"] == 0.5
    assert parts["agreement"] == 1.0
    assert parts["chain"] == 1.0

    d, sid = _dossier(0.9)
    _add(d, sid)
    conf, parts = conclude_confidence("CON1", d)
    assert conf == 0.875
    assert parts["strength"] == 0.9
    assert parts["coverage"] == 0.5
    assert parts["agreement"] == 1.0
    assert parts["chain"] == 1.0

    d, sid = _dossier(0.3)
    _add(d, sid)
    conf, parts = conclude_confidence("CON1", d)
    assert conf == 0.725
    assert parts["strength"] == 0.3
    assert parts["coverage"] == 0.5
    assert parts["agreement"] == 1.0
    assert parts["chain"] == 1.0

    # l4④／K6：clip01 钳位
    assert row_score_of({
        "strength": 2.0, "coverage": 3.0, "agreement": 1.0, "chain": 1.0,
    }) == 1.0


# ---------- g ----------
def test_g_band_from_score_not_dossier_confidence(tmp_path):
    # v2：score 走 parts 重算，不读 dossier_confidence；选可表达低分 0.25
    parts = {"strength": 0.0, "coverage": 0.0, "agreement": 1.0, "chain": 0.0}
    assert row_score_of(parts) == 0.25
    d = _synth_dossier(tmp_path / "g", n_majority=1, parts_list=[parts])
    d.conclusions[0].confidence = 0.95
    paths = export_official(
        [({"question_id": "q1", "question": "问"}, d)],
        tmp_path / "g_out",
    )
    row = json.loads(paths["confidence"].read_text(encoding="utf-8"))[0]
    assert row["score"] == 0.25
    assert row["dossier_confidence"] == 0.95
    assert row["band"] == "低"


# ---------- h ----------
def test_h_confcolor_aligned_with_band_constants():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert len(re.findall(r">=\.2", html)) == 0
    assert len(re.findall(r">=\.8", html)) == 1
    assert html.count("function confColor") == 1
    assert html.count("confColor") == 4
    hi = str(_BAND_HIGH).lstrip("0") if _BAND_HIGH < 1 else str(_BAND_HIGH)
    mid = str(_BAND_MID).lstrip("0") if _BAND_MID < 1 else str(_BAND_MID)
    assert hi == ".8" and mid == ".5"
    assert f">={hi}" in html and f">={mid}" in html
    m = re.search(
        r"function confColor\(c\)\{return c>=\.(\d+)\?\"var\(--good\)\":"
        r"c>=\.(\d+)\?\"var\(--warn\)\":\"var\(--bad\)\"\}",
        html,
    )
    assert m
    assert float("0." + m.group(1)) == _BAND_HIGH
    assert float("0." + m.group(2)) == _BAND_MID
    # l4②：renderSynth 兜底支 bandMain／bandRel
    assert html.count("bandMain") == 2
    assert html.count("bandRel") == 2
    assert "档" in html and "相对" in html


# ---------- i ----------
def test_i_early_exit_still_prints_bands_and_slot_compare(tmp_path):
    d = _synth_dossier(tmp_path / "i", n_majority=0)
    d.accounting = {"confidence_note": SLOT_NOTE, "elapsed_s": 0.1,
                    "n_calls": 0, "tokens": 0}
    assert d.accounting["confidence_note"] == SLOT_NOTE
    md = render_report_md(d, HashChain(), [])
    assert "高置信（≥0.8）：0 条" in md
    assert "本案卷 0 条" in md
    assert "相对档 band_rel" in md
    assert "高：0 条 · 中：0 条 · 低：0 条" in md
    assert "不可分：0 条" in md
    paths = export_official(
        [({"question_id": "q1", "question": "问"}, d)],
        tmp_path / "i_out",
    )
    conflict = json.loads(paths["conflict_resolution"].read_text(encoding="utf-8"))
    assert any("本次 1 题因槽位未齐未调用分析师" in str(x)
               for x in conflict.get("omissions") or [])
    pipe = (ROOT / "app" / "pipeline.py").read_text(encoding="utf-8")
    assert pipe.count(SLOT_NOTE) >= 1
    official = (ROOT / "app" / "export" / "official.py").read_text(encoding="utf-8")
    assert f'== "{SLOT_NOTE}"' in official or f"== '{SLOT_NOTE}'" in official


# ---------- j ----------
def test_j_single_score_formula_site():
    official = (ROOT / "app" / "export" / "official.py").read_text(encoding="utf-8")
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    conf = (ROOT / "app" / "core" / "confidence.py").read_text(encoding="utf-8")
    assert official.count("chain_factor_of(") == 0
    assert official.count("_AGREEMENT_FLOOR") == 0
    assert server.count("row_score_of(") >= 1
    assert len(re.findall(r"def row_score_of\b", conf)) == 1


# ---------- f（l1：合成产物，不许读 cases/*/out*）----------
def test_f_server_payload_injects_band_without_touching_report(tmp_path):
    from app.server import _dossier_payload

    d = _synth_dossier(tmp_path / "case_src", n_majority=3)
    out = tmp_path / "case" / "out"
    out.mkdir(parents=True)
    report = out / "report.json"
    d.to_json(report)
    sha_before = _sha(report)
    payload = _dossier_payload(out)
    assert _sha(report) == sha_before
    cons = (payload.get("dossier") or {}).get("conclusions") or []
    assert cons
    for c in cons:
        assert c.get("band") in _BANDS4 or c.get("band") in _BANDS3
        assert c.get("band_rel") in _BANDS4
    acc = payload.get("accounting") or {}
    assert "band_counts" in acc and "band_rel_counts" in acc and "band_n" in acc
    assert acc["band_n"] == len(cons)
    assert '"band"' not in report.read_text(encoding="utf-8")
    assert "band" not in json.loads(report.read_text(encoding="utf-8")).get(
        "conclusions", [{}])[0]


# ---------- k ----------
def test_k_pack_material_still_two_and_rule_note_four_sites():
    pipe = (ROOT / "app" / "pipeline.py").read_text(encoding="utf-8")
    web = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert pipe.count("pack_material(") == 2
    assert web.count("置信度是规则分，不是命中率") == 3
    assert pipe.count("不是命中率") == 2
    assert pipe.count("规则分，不是命中率") == 1


def test_field_notes_mention_thresholds_and_empty_high():
    from app.export.official import _FIELD_NOTES
    assert "0.8" in _FIELD_NOTES and "官方" in _FIELD_NOTES
    assert "0.5" in _FIELD_NOTES and "我方设定" in _FIELD_NOTES
    # C-21 把跑次死数 0/40／0/57／max≈0.55 清掉；高档常空改写为结构性结论句
    assert "0/40" not in _FIELD_NOTES and "0/57" not in _FIELD_NOTES
    assert "max≈0.55" not in _FIELD_NOTES
    assert "v1 连乘" in _FIELD_NOTES or "结构性" in _FIELD_NOTES
    assert ("无样本可判" in _FIELD_NOTES) or ("仍无法回答" in _FIELD_NOTES)
    assert "dossier_confidence" in _FIELD_NOTES
    assert "本案卷" in _FIELD_NOTES
    assert "不可分" in _FIELD_NOTES
    assert "score≤0" in _FIELD_NOTES or "score<=0" in _FIELD_NOTES


# ---------- l4① pooled 两题 ----------
def test_l4_pooled_across_two_questions(tmp_path):
    # v2 可表达下界 0.25；用 0.25／0.30／0.40 保持「pooled=低/中 vs q2-only=中/高」语义
    d1 = _synth_dossier(
        tmp_path / "p1", n_majority=3,
        parts_list=[_parts_for_score(0.9)] * 3)
    d2 = _synth_dossier(
        tmp_path / "p2", n_majority=3,
        parts_list=[_parts_for_score(0.25), _parts_for_score(0.30),
                    _parts_for_score(0.40)])
    paths = export_official(
        [({"question_id": "q1", "question": "题一"}, d1),
         ({"question_id": "q2", "question": "题二"}, d2)],
        tmp_path / "pooled_out",
    )
    rows = json.loads(paths["confidence"].read_text(encoding="utf-8"))
    assert len(rows) == 6
    rule = rows[0]["band_rel_rule"]
    assert "pooled 样本数=6" in rule
    q2 = [r for r in rows if r["question_id"] == "q2"]
    scores_q2 = [float(r["score"]) for r in q2]
    pooled = [float(r["score"]) for r in rows]
    row030 = next(r for r in q2 if abs(float(r["score"]) - 0.30) < 1e-9)
    row040 = next(r for r in q2 if abs(float(r["score"]) - 0.40) < 1e-9)
    assert row030["band_rel"] == "低"
    assert row040["band_rel"] == "中"
    # 只用 q2 三行算切点 ⇒ 与 pooled 不同
    assert band_rel_of(scores_q2, 0.30) == "中"
    assert band_rel_of(scores_q2, 0.40) == "高"
    assert band_rel_of(scores_q2, 0.30) != row030["band_rel"]
    assert band_rel_of(pooled, 0.30) == row030["band_rel"]


# ---------- l4③ 首屏只数 majority ----------
def test_l4_report_counts_majority_only(tmp_path):
    d = _synth_dossier(
        tmp_path / "maj", n_majority=3,
        extra_conclusions=[{
            "status": "dissent",
            "parts": {"strength": 1.0, "coverage": 1.0,
                      "agreement": 1.0, "chain": 1.0},
        }])
    assert row_score_of(d.conclusions[-1].confidence_parts) == 1.0
    assert sum(1 for c in d.conclusions if c.status == "majority") == 3
    md = render_report_md(d, HashChain(), [])
    assert "本案卷 3 条" in md
    assert "高置信（≥0.8）：0 条" in md


# ---------- m1 退化六面 ----------
def test_m1_band_rel_degeneration_six_faces():
    assert _BAND_REL_EPS == 1e-9
    # ① demo 案卷 7 条
    s1 = [0, 0, 0, 0, 0, 0.1925, 0.2414]
    assert [band_rel_of(s1, x) for x in s1] == (
        ["低"] * 5 + ["高", "高"])
    # ② 全 0.0×7
    s2 = [0.0] * 7
    assert [band_rel_of(s2, x) for x in s2] == ["低"] * 7
    # ③ 两条 0.0
    s3 = [0.0, 0.0, 0.3]
    assert band_rel_of(s3, 0.0) == "低"
    assert band_rel_of(s3, 0.3) == "高"
    # ④ 全 0.9×4
    s4 = [0.9] * 4
    assert [band_rel_of(s4, x) for x in s4] == ["不可分"] * 4
    # ⑤ 官方退化格（中美AI q_002）
    s5 = [0.3167] * 9 + [0.3166, 0.2533]
    assert [band_rel_of(s5, x) for x in s5] == (
        ["不可分"] * 9 + ["低", "低"])
    # ⑥ 单条样本
    assert band_rel_of([0.5], 0.5) == "低"


# ---------- m2／m4 披露＋渲染 ----------
def test_m4_band_rel_rule_discloses_degeneration():
    rule4 = band_rel_rule_of([0.9] * 4)
    assert "切点重合" in rule4 and "不可分" in rule4
    assert "4" in rule4
    rule1 = band_rel_rule_of([0.5])
    assert rule1 == (
        "quantiles n=100 method=inclusive；pooled 样本数=1；"
        "样本<2 整档记为低；来源＝我方本次分布"
    )


def test_m2_render_prints_indiscriminable_tail(tmp_path):
    d = _synth_dossier(tmp_path / "m2", n_majority=0)
    md = render_report_md(d, HashChain(), [])
    assert "· 不可分：0 条" in md
    pipe = (ROOT / "app" / "pipeline.py").read_text(encoding="utf-8")
    assert "不可分：{rel_c.get('不可分', 0)} 条" in pipe or "不可分：" in pipe


# ---------- m3 非退化面不变式 ----------
def test_m3_nondegenerate_surface_unchanged():
    assert band_rel_of(SCORES_A, 0.90) == "高"
    assert band_rel_of(SCORES_A, 0.50) == "中"
    assert band_rel_of(SCORES_A, 0.40) == "中"
    assert band_rel_of(SCORES_A, 0.30) == "低"
    assert band_rel_of(SCORES_A, 0.10) == "低"
    rel = band_count_dict(SCORES_A, absolute=False)
    assert set(rel) == {"高", "中", "低", "不可分"}
    assert rel["不可分"] == 0
    abs_c = band_count_dict(SCORES_A, absolute=True)
    assert set(abs_c) == {"高", "中", "低"}
    assert "不可分" not in abs_c
