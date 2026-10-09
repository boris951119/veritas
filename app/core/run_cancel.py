"""工作台研判协作式取消（零 LLM）。

旗标按案例名登记；POST /api/cancel 置位后，BudgetGuard.ensure_allowed
与管线阶段检查点抛 TaskCancelledError，尽快停掉后续 LLM 调用。
当前正在飞行的那一次网关请求仍会跑完，下一检查点才中断。
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_flags: dict[str, bool] = {}


def begin_run(case: str) -> None:
    key = (case or "").strip()
    if not key:
        return
    with _lock:
        _flags[key] = False


def request_cancel(case: str) -> bool:
    """置取消旗标。返回是否找到在跑任务（有登记即 True）。"""
    key = (case or "").strip()
    if not key:
        return False
    with _lock:
        if key not in _flags:
            return False
        _flags[key] = True
        return True


def is_cancelled(case: str) -> bool:
    key = (case or "").strip()
    if not key:
        return False
    with _lock:
        return bool(_flags.get(key))


def end_run(case: str) -> None:
    key = (case or "").strip()
    if not key:
        return
    with _lock:
        _flags.pop(key, None)


def check_cancel(case: str) -> None:
    """检查点：已取消则抛 TaskCancelledError。"""
    from app.llm.budget import TaskCancelledError

    if is_cancelled(case):
        raise TaskCancelledError("任务已被用户取消（协作式取消检查点）")
