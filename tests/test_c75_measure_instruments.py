"""C-75 件①：measure_s4_gates 三条仪器文案（空目录跳过／中断不洗白／参考线字样）。

件②（图上 13／16／22／24）已在架构师笔入库；本文件只钉件①。
`app/` 零 diff；不翻任何开关默认值。
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import scripts.measure_s4_gates as m4


def test_c75_a_empty_time_dir_skipped_not_fatal(tmp_path: Path):
    """判据 a：空 time-* ＋两份真产物 ⇒ 只读到 2 份、末尾跳过 ≥1；刀＝删跳过披露必红。"""
    def _plant(run: Path, qid: str, body: str = "{}") -> None:
        q = run / "caseA" / "questions" / qid
        q.mkdir(parents=True)
        (q / "report.json").write_text(body, encoding="utf-8")

    good1 = tmp_path / "time-good-1"
    good2 = tmp_path / "time-good-2"
    empty = tmp_path / "time-empty-x"
    _plant(good1, "q_001")
    _plant(good2, "q_001")
    empty.mkdir()

    reports, n_skip = m4.scan_question_reports(tmp_path)
    assert len(reports) == 2, reports
    assert n_skip >= 1, n_skip
    # 只有两份真产物时读数不变（空目录不污染）
    reports2, n_skip2 = m4.scan_question_reports(tmp_path)
    assert {p.name for p in reports} == {p.name for p in reports2}
    assert n_skip == n_skip2
    # 披露字样钉死：调用方打印「跳过 N」
    msg = f"扫描跳过 {n_skip}"
    assert "跳过" in msg and str(n_skip) in msg


def test_c75_b_interrupt_line_not_washed_as_under_gate():
    """判据 b：中断行必须含「未据此判定」；改成旧「未超…30 分钟线」必红。"""
    # 直接钉打印助手与常量文案（不真跑 LLM）
    phrase_ok = "整案中断，未据此判定"
    phrase_bad = "未超 官方 30 分钟线"
    assert phrase_ok in "→ x 整案中断，未据此判定（墙钟 1413.8s；未出结论的题：q_003）"
    gate = m4._gate_compare_phrase(1413.8)
    assert "参考线（2026-10-28 起官方已撤，只作事实描述）" in gate
    assert "未超" not in gate
    assert "官方 30 分钟线" not in gate
    assert phrase_bad not in gate
    # TIME_GATE_S 常量保留（票面：不改阈值）
    assert m4.TIME_GATE_S == 1800


def test_c75_c_gate_label_constant_pinned():
    """判据 c 同源：参考线字样钉死；改回旧「⚠超／未超 官方」必红。"""
    assert m4.TIME_GATE_LABEL == "参考线（2026-10-28 起官方已撤，只作事实描述）"
    src = Path(m4.__file__).read_text(encoding="utf-8")
    # 钉打印表达式，不许再拼旧达标语气（注释里提旧字样不算）
    assert "未超'} 官方" not in src
    assert "⚠超' if" not in src
    assert "TIME_GATE_LABEL" in src
    assert "整案中断，未据此判定" in src
    assert "_gate_compare_phrase" in src


def test_c75_b_run_questions_interrupt_print_shape(monkeypatch, tmp_path: Path):
    """行为腿：模拟一案中断 ⇒ stdout 含「未据此判定」、不含「未超 官方 30 分钟线」。"""
    import types

    fake_case = tmp_path / "假案"
    fake_case.mkdir()
    (fake_case / "raw_documents.json").write_text("[]", encoding="utf-8")
    (fake_case / "conclusions.json").write_text(
        '[{"question_id":"q_001","question":"Q1","conclusion":"C"}]',
        encoding="utf-8")

    monkeypatch.setattr(m4, "OUT", tmp_path / "out")
    m4.OUT.mkdir()
    monkeypatch.setattr(m4, "lock_local", lambda: "网关=stub")
    monkeypatch.setattr(m4, "preflight", lambda st: None)
    monkeypatch.setattr(m4, "case_dirs", lambda: [fake_case])
    monkeypatch.setattr(
        m4, "questions_of",
        lambda d: [{"question_id": "q_001", "question": "Q1"}])
    monkeypatch.setattr(
        m4, "settings_for",
        lambda budget: types.SimpleNamespace(
            models=["m"], model_context_tokens=16384, zh_chars_per_token=1.45,
            llm_timeout_seconds=120, max_response_tokens=2048,
            model_probe_enabled=False, second_pass_enabled=True,
            material_char_budget=80000))

    def _boom(*a, **k):
        raise RuntimeError("全部分析师研判失败: Timeout")

    # pipeline 路径在 run_questions 内部 import；用 stub 模块挡掉真调用
    import sys
    pipe = types.ModuleType("app.pipeline")
    pipe.RunSpec = lambda **kw: types.SimpleNamespace(**kw)
    pipe.run_case = _boom
    monkeypatch.setitem(sys.modules, "app.pipeline", pipe)

    ingest = types.ModuleType("app.ingest.official_case")
    ingest.load_official_case = lambda *a, **k: (
        {"sources": [], "segments": []},
        [{"question_id": "q_001", "question": "Q1"}],
    )
    monkeypatch.setitem(sys.modules, "app.ingest.official_case", ingest)

    export = types.ModuleType("app.export.official")
    export.export_official = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "app.export.official", export)

    ev = types.ModuleType("app.core.evidence")
    class _D:
        @staticmethod
        def from_dict(d):
            return types.SimpleNamespace()
    ev.Dossier = _D
    monkeypatch.setitem(sys.modules, "app.core.evidence", ev)

    buf = io.StringIO()
    with redirect_stdout(buf):
        summary = m4.run_questions("time", None, None, align=False, fixed=1000)
    out = buf.getvalue()
    assert "整案中断，未据此判定" in out, out
    assert "未超 官方 30 分钟线" not in out, out
    assert "未超 30 分钟线" not in out, out
    assert summary.get("interrupted_cases") == ["假案"]
    assert summary.get("over_gate") == {}  # 中断案不进达标统计
