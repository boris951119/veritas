"""并行研判：各写各的历史目录，取消一次不影响另一次。"""

import json
import threading
from pathlib import Path

from app.core.run_cancel import begin_run, end_run, is_cancelled, request_cancel
from app.llm.budget import BudgetGuard, get_active_budget_guard, set_active_budget_guard
from app.workbench_run import run_workbench_case


def test_cancel_one_run_leaves_the_other():
    begin_run("case", "run-a")
    begin_run("case", "run-b")
    try:
        assert request_cancel("case", "run-a") is True
        assert is_cancelled("case", "run-a") is True
        assert is_cancelled("case", "run-b") is False
    finally:
        end_run("case", "run-a")
        end_run("case", "run-b")


def test_budget_guards_do_not_share_usage():
    seen = {}

    def work(name: str, guard: BudgetGuard) -> None:
        set_active_budget_guard(guard)
        guard.record(7)
        seen[name] = get_active_budget_guard().used_tokens

    g1, g2 = BudgetGuard(100), BudgetGuard(100)
    t1 = threading.Thread(target=work, args=("a", g1))
    t2 = threading.Thread(target=work, args=("b", g2))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert seen == {"a": 7, "b": 7}
    assert g1.used_tokens == 7 and g2.used_tokens == 7


def test_two_runs_keep_their_own_reports(tmp_path, monkeypatch):
    monkeypatch.setattr("app.workbench_run.is_live_mode", lambda: False)
    case = tmp_path / "demo"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "question: 默认问题\nsources:\n  - file: a.md\n    type: note\n",
        encoding="utf-8")
    (case / "a.md").write_text("华东仓储吞吐量达到十二万吨。\n", encoding="utf-8")

    errors = []

    def go(question: str, rid: str) -> None:
        try:
            run_workbench_case(case, question=question, run_id=rid)
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=go, args=("问题甲是否成立？", "runA")),
        threading.Thread(target=go, args=("问题乙是否成立？", "runB")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    qa = json.loads((case / "history" / "runA" / "report.json").read_text())["question"]
    qb = json.loads((case / "history" / "runB" / "report.json").read_text())["question"]
    assert qa == "问题甲是否成立？"
    assert qb == "问题乙是否成立？"
    current = json.loads((case / "out_offline" / "report.json").read_text())["question"]
    assert current in {qa, qb}
    assert Path(case / "history" / "runA" / "report.json").is_file()
