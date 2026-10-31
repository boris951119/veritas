# -*- coding: utf-8 -*-
"""#38 辅助标注件的离线桩测试格（零 LLM、不真调模型）。

锁四件事：
① 草稿只落注入的 OUT（生产＝/tmp/s4runs），**绝不写仓库 calibration/**；
② 安全闸＝网关非本机直接拒跑（复用 `measure_s4_gates.lock_local` 那一条规则）；
③ 防编造机械核＝支撑片段逐段可在给定引文里定位；定位不到 ⇒ label 记空并标旗；
④ 入账面完整性与来源可追（`labels_self.jsonl` ↔ `candidates_self.jsonl` ↔ 入账回执）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.assist_label_self as al                                   # noqa: E402


# ---------- 夹具：一棵合成案卷树＋候选清单（零 LLM） ----------

_TEXT_WIN = "某研究机构年度报告：装车验证完成，产线良率两千小时稳定。"
_TEXT_OTHER = "行业新闻汇编：试点产线计划 2027 年装车路测。"


def _make_repo(tmp_path: Path):
    case = tmp_path / "cases" / "demo-solid-state" / "out"
    case.mkdir(parents=True)
    report = {
        "question": "固态电池量产路径？",
        "sources": [{"id": "SRC1", "segments": [
            {"id": "SRC1#s1", "source_id": "SRC1", "text": _TEXT_WIN, "locator": "段 1"},
            {"id": "SRC1#s2", "source_id": "SRC1", "text": _TEXT_OTHER, "locator": "段 2"},
        ]}],
        "conclusions": [{"id": "CON-1", "statement": "装车验证已完成", "status": "majority",
                         "confidence": 0.18, "evidence_ids": ["EV-1"]}],
        "evidences": [{"id": "EV-1", "conclusion_id": "CON-1", "quote": _TEXT_WIN,
                       "segment_ids": ["SRC1#s1"], "relation": "correlation", "level": "A",
                       "note": "", "weight": 1.0, "author": "m", "verified": None}],
        "conflicts": [], "rejected": [],
    }
    (case / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    cands = tmp_path / "candidates.jsonl"
    cands.write_text(json.dumps({
        "case": "cases/demo-solid-state", "conclusion_id": "CON-1",
        "statement_sha8": "deadbeef", "score": 0.18, "band": "低", "band_rel": "低",
        "label": "", "labeled_by": ""}, ensure_ascii=False) + "\n", encoding="utf-8")
    return cands


class _Resp:
    def __init__(self, content: str):
        self.content = content
        self.total_tokens = 7


class _FakeClient:
    """桩客户端：第一次回「对＋可定位引文」，第二次回「对＋自造引文」＝该被旗。"""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = 0

    def chat(self, model, messages, json_mode=False):
        self.calls += 1
        return _Resp(self._payloads.pop(0))


class _FakeFactory:
    last = None

    def __init__(self, settings):
        pass

    def create(self):
        return _FakeFactory.last


def _stub_run(tmp_path: Path, monkeypatch, payloads):
    monkeypatch.setattr(al, "_locks", lambda: "网关=stub（测试不碰真模型）")
    monkeypatch.setattr(al, "ROOT", tmp_path)
    monkeypatch.setattr(al, "OUT", tmp_path / "s4runs")
    from app.llm import model_client
    import scripts.measure_s4_gates as m4
    _FakeFactory.last = _FakeClient(payloads)
    monkeypatch.setattr(model_client, "ModelClientFactory", _FakeFactory)
    monkeypatch.setattr(m4, "settings_for", lambda budget: None)
    monkeypatch.setattr(m4, "MODEL", "stub/model")
    return _FakeFactory.last


def _one(payload_json: str, tmp_path, monkeypatch):
    cands = _make_repo(tmp_path)
    client = _stub_run(tmp_path, monkeypatch, [payload_json])
    assert al.run(cands, 0) == 0
    out_dirs = sorted((tmp_path / "s4runs").glob("assist-label-*"))
    assert out_dirs, "草稿目录没建"
    return out_dirs[0], client


# ---------- ② 安全闸：非本机网关拒跑 ----------

def test_b_lock_gate_refuses_cloud_gateway(monkeypatch):
    import scripts.measure_s4_gates as m4

    monkeypatch.setattr(m4, "BASE_URL", "https://cloud.example.com/v1")
    with pytest.raises(SystemExit) as e:
        m4.lock_local()
    assert "拒绝" in str(e.value)


# `lock_local()` 会直接改 os.environ（假密钥／单模型／VERITAS_OCR=0），
# 而 monkeypatch 只回滚它自己设的那些键 ⇒ 必须自己存还，否则后面的用例被污染
# （踩过一次：`test_triage_layer::test_pipeline_ocr_gated_by_settings` 因 VERITAS_OCR=0 泄漏而假红）。
_ENV_KEYS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "VERITAS_MODELS", "VERITAS_OCR",
             "MX_APIKEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
             "AZURE_API_KEY", "MOONSHOT_API_KEY")


def test_b_lock_gate_accepts_local_loopback(monkeypatch):
    import os

    import scripts.measure_s4_gates as m4
    from app.llm import connections

    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    try:
        monkeypatch.setattr(m4, "BASE_URL", "http://127.0.0.1:11434/v1")
        monkeypatch.setattr(connections, "resolve_credentials",
                            lambda model: {"base_url": m4.BASE_URL})
        for key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        gate = m4.lock_local()
        assert "本机" in gate or "单模型" in gate
        assert os.environ["OPENAI_API_KEY"] == "ollama"
        assert os.environ["VERITAS_OCR"] == "0"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------- ①／③ 草稿只落 OUT、可定位才算数 ----------

def test_a_draft_never_written_into_repo_calibration(tmp_path, monkeypatch):
    calib = ROOT / "calibration"
    before = sorted(p.name for p in calib.iterdir())
    payload = json.dumps({"label": "对", "why": "引文原词支撑", "quote": _TEXT_WIN, "sure": True},
                         ensure_ascii=False)
    out_dir, client = _one(payload, tmp_path, monkeypatch)
    assert sorted(p.name for p in calib.iterdir()) == before, "草稿不许进仓库 calibration/"
    assert client.calls == 1
    drafts = (out_dir / "draft_labels.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(drafts) == 1
    row = json.loads(drafts[0])
    assert row["model_label"] == "对" and not row["flag"]
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["signed"] is False
    assert "未经用户抽检签字不得进 calibration/" in summary["note"]
    assert (out_dir / "spot_check_sheet.md").is_file()


def test_c_fabricated_quote_is_flagged_and_not_counted(tmp_path, monkeypatch):
    payload = json.dumps({"label": "对", "why": "看起来没问题",
                          "quote": "这段话案卷里根本没有出现过的一段自造文字",
                          "sure": True}, ensure_ascii=False)
    out_dir, _ = _one(payload, tmp_path, monkeypatch)
    row = json.loads((out_dir / "draft_labels.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["model_label"] == ""
    assert row["flag"].startswith("支撑片段不可定位")
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["n_labeled"] == 0 and summary["n_flagged"] == 1


def test_c_markdown_and_pipe_forms_stay_locatable():
    fed = ["截至2026年8月4日，项目整体完成率**62%**，较计划提前。", "另一段：安排资深工程师赴现场。"]
    ok_cases = [
        "截至2026年8月4日，项目整体完成率**62%**，较计划提前",
        "完成率62%，较计划提前 | 安排资深工程师赴现场",
        "[2] 安排资深工程师赴现场",
    ]
    for q in ok_cases:
        assert al._unlocatable(q, fed) == "", q
    assert al._unlocatable("这段文字在案卷里不存在，纯属自造", fed) != ""


def test_d_think_artifacts_are_stripped():
    raw = "结论正文 " + "/no_" + "think 还有 <thin" + "k> 尾巴"
    s = al._strip_think(raw)
    assert "/no_" not in s and "k>" not in s and "结论正文" in s and "尾巴" in s


def test_z_help_runs_without_key():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/assist_label_self.py"), "--help"],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    assert r.returncode == 0, r.stderr
    assert "--limit" in r.stdout


# ---------- 机械纠偏：「对」要过四道闸 ----------

def test_e_maybe_demote_gates():
    fed = [_TEXT_WIN]
    # 1) sure=false 不得「对」
    assert al._maybe_demote("对", "支撑充分", "装车验证已完成", _TEXT_WIN, fed, False)[0] == "部分"
    # 2) why 自己承认缺口
    lab, why = al._maybe_demote("对", "引文未提及良率归属", "装车验证已完成", _TEXT_WIN, fed, True)
    assert (lab, why) == ("部分", "纠偏:why承认缺口不得标对")
    # 3) 多主体缺一
    lab2, why2 = al._maybe_demote("对", "两客户都写了", "客户B与客户F均提前", _TEXT_WIN, fed, True)
    assert lab2 == "部分" and "缺主体" in why2
    # 4) 判断词无原文支撑
    lab3, why3 = al._maybe_demote("对", "有数据", "客户B无延期风险", _TEXT_WIN, fed, True)
    assert lab3 == "部分" and why3 == "纠偏:判断词无原文支撑"
    # 5) 全过闸 ⇒ 保持「对」
    assert al._maybe_demote("对", "原词支撑", "装车验证已完成", _TEXT_WIN, fed, True)[0] == "对"


def test_f_sheet_is_deterministic_and_carries_sign_fields(tmp_path, monkeypatch):
    payload = json.dumps({"label": "对", "why": "原词", "quote": _TEXT_WIN, "sure": True},
                         ensure_ascii=False)
    cands = _make_repo(tmp_path)
    _stub_run(tmp_path, monkeypatch, [payload, payload])
    import copy
    drafts = [{"case": "cases/x", "conclusion_id": f"CON-{i}", "statement_sha8": "a" * 8,
               "score": 0.1 + i / 100, "statement": "语句", "model_label": "对" if i % 2 else "部分",
               "why": "原词", "quote": _TEXT_WIN, "display_quote": _TEXT_WIN,
               "sure": True, "flag": "", "elapsed_s": 0.1, "n_quotes": 1,
               "n_quote_chars": 30, "dropped_quotes": 0} for i in range(30)]
    counts = {"对": 15, "部分": 15, "错": 0}
    d1, d2 = tmp_path / "s1", tmp_path / "s2"
    d1.mkdir()
    d2.mkdir()
    n1, p1 = al._build_sheet(copy.deepcopy(drafts), d1, counts, 0)
    n2, p2 = al._build_sheet(copy.deepcopy(drafts), d2, counts, 0)
    t1, t2 = p1.read_text(encoding="utf-8"), p2.read_text(encoding="utf-8")
    assert t1 == t2, "同一批草稿两次出表必须逐字相同（可复现抽检）"
    assert n1 == n2 > 0
    assert "labeled_by＝" in t1 and "改标率" in t1
    assert "整批" in t1, "表里必须带「对档改标率 ≤10% ⇒ 整批入账」这条待拍规则"
    assert cands.is_file()


# ---------- ④ 入账面完整性与来源可追（真文件） ----------

def test_g_booked_labels_are_consistent_with_candidates():
    lab_path = ROOT / "calibration" / "labels_self.jsonl"
    cand_path = ROOT / "calibration" / "candidates_self.jsonl"
    if not lab_path.is_file():
        pytest.skip("标定集未入账（#38 未签字时属正常状态）")
    lab = [json.loads(l) for l in lab_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    cand = {(r["case"], r["conclusion_id"], r["statement_sha8"])
            for r in (json.loads(l) for l in
                      cand_path.read_text(encoding="utf-8").splitlines() if l.strip())}
    assert len(lab) >= 60, "达标行数＝判据 b 的硬要求"
    keys = [(r["case"], r["conclusion_id"], r["statement_sha8"]) for r in lab]
    assert len(set(keys)) == len(keys), "重复行"
    assert set(keys) <= cand, "有行不在候选清单里"
    assert all(r["label"] in ("对", "部分", "错") for r in lab)
    assert all(str(r.get("labeled_by", "")).strip() for r in lab)
    assert all(r["case"].startswith(("cases/", "eval/")) for r in lab), "标定集只用自家案例"
    assert len(lab) <= len(cand)


def test_h_receipt_matches_booked_labels_and_discloses_provenance():
    rp = ROOT / "calibration" / "labels_self_receipt.json"
    lab_path = ROOT / "calibration" / "labels_self.jsonl"
    if not (rp.is_file() and lab_path.is_file()):
        pytest.skip("入账回执未落地")
    rec = json.loads(rp.read_text(encoding="utf-8"))
    lab = [json.loads(l) for l in lab_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rec["n_labels"] == len(lab)
    counts = {"对": 0, "部分": 0, "错": 0}
    for r in lab:
        counts[r["label"]] += 1
    assert rec["counts"] == counts, "回执里的分布与标签文件不符"
    src = rec["method"]["src_breakdown"]
    assert sum(src.values()) == rec["n_labels"]
    assert rec["batch_gate"]["gate"] == "PASS"
    # 用户本人追认的三处复原必须留痕（方向＝抬高准确率，不许无痕）
    conf = rec["confirmed_restorations"]
    assert conf["sheet_rows"] and conf["confirmed_by"], "缺用户追认记录"
    for cid in conf["conclusion_ids"]:
        assert any(r["conclusion_id"] == cid for r in lab)
    se = rec["selection_effect"]
    assert se["booked"] + se["excluded"] == se["candidates"], "选择效应账不平"
    assert rec["c24_curve"]["architect_check"]["monotonic"] is False
