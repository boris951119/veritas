"""协作式取消：旗标 + 预算检查点。"""

from __future__ import annotations

import pytest

from app.core.run_cancel import (
    begin_run, check_cancel, end_run, is_cancelled, request_cancel,
)
from app.llm.budget import BudgetGuard, TaskCancelledError


def test_cancel_flag_lifecycle():
    begin_run("case-a")
    assert is_cancelled("case-a") is False
    assert request_cancel("case-a") is True
    assert is_cancelled("case-a") is True
    with pytest.raises(TaskCancelledError):
        check_cancel("case-a")
    end_run("case-a")
    assert is_cancelled("case-a") is False
    assert request_cancel("case-a") is False


def test_budget_guard_honors_cancel_check():
    begin_run("case-b")
    g = BudgetGuard(10_000)
    g.attach_cancel_check(lambda: is_cancelled("case-b"))
    g.ensure_allowed()
    request_cancel("case-b")
    with pytest.raises(TaskCancelledError):
        g.ensure_allowed()
    end_run("case-b")
