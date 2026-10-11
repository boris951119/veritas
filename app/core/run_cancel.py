"""工作台研判协作式取消（零 LLM）。

旗标按 run_id 登记，并挂在案例名下。POST /api/cancel 不带 run_id 时
取消该案例当前全部在跑任务（旧按钮）；带 run_id 时只停那一次。
当前正在飞行的那一次网关请求仍会跑完，下一检查点才中断。
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_by_case: dict[str, set[str]] = {}
_cancelled: set[str] = set()


def begin_run(case: str, run_id: str | None = None) -> str:
    """登记一次运行。未给 run_id 时用案例名，兼容旧的单次取消测试。"""
    key = (case or "").strip()
    rid = (run_id or key).strip()
    if not key or not rid:
        return ""
    with _lock:
        _cancelled.discard(rid)
        _by_case.setdefault(key, set()).add(rid)
    return rid


def request_cancel(case: str, run_id: str | None = None) -> bool:
    """置取消旗标。指定 run_id 只停那一次；否则停该案例全部在跑任务。"""
    key = (case or "").strip()
    if not key:
        return False
    with _lock:
        ids = set(_by_case.get(key) or set())
        if run_id:
            if run_id not in ids:
                return False
            _cancelled.add(run_id)
            return True
        if not ids:
            return False
        _cancelled.update(ids)
        return True


def is_cancelled(case: str, run_id: str | None = None) -> bool:
    """run_id 给定时只看那一次；否则该案例任一在跑任务被取消即真。"""
    key = (case or "").strip()
    if not key:
        return False
    with _lock:
        if run_id:
            return run_id in _cancelled
        ids = _by_case.get(key) or set()
        return any(rid in _cancelled for rid in ids)


def end_run(case: str, run_id: str | None = None) -> None:
    key = (case or "").strip()
    rid = (run_id or key).strip()
    if not key or not rid:
        return
    with _lock:
        _cancelled.discard(rid)
        ids = _by_case.get(key)
        if ids is not None:
            ids.discard(rid)
            if not ids:
                _by_case.pop(key, None)


def check_cancel(case: str, run_id: str | None = None) -> None:
    """检查点：已取消则抛 TaskCancelledError。"""
    from app.llm.budget import TaskCancelledError

    if is_cancelled(case, run_id):
        raise TaskCancelledError("任务已被用户取消（协作式取消检查点）")
