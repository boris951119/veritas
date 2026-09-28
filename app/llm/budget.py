"""单任务 token 总预算闸门（移植自 token-burner app/utils/budget.py，
去掉 48h 运行墙钟段——veritas 为本地短周期研判，暂不需要收尾窗口）。

确定性程序护栏：
- 已用 ≥ 预算 × throttle_threshold → 省 token 模式（throttling），
  由编排层压缩辩论轮数、跳过非必要比对；
- 已用 ≥ 预算 → BudgetExceededError，立即中止（不静默继续）；
- 活动护栏槽：管线创建护栏后在此登记，零散 ModelClient 未显式接线时
  兜底复用，堵住无上限失血（token-burner ¥210 学费的教训）。
"""

from __future__ import annotations

from typing import Callable


class BudgetExceededError(RuntimeError):
    """任务 token 总预算耗尽（立即中止，落盘交用户）。"""


class TaskCancelledError(RuntimeError):
    """任务被用户取消（协作式取消：检查点抛出，任务体终止）。"""


_active_guard: "BudgetGuard | None" = None


def set_active_budget_guard(guard: "BudgetGuard | None") -> None:
    """登记当前任务的活动护栏（管线创建护栏时调用一次）。"""
    global _active_guard
    _active_guard = guard


def get_active_budget_guard() -> "BudgetGuard | None":
    """零散 ModelClient 兜底数据源：未显式接线时复用活动护栏。"""
    return _active_guard


class BudgetGuard:
    """单任务预算护栏：累计用量 + 阈值判定 + 超限拦截 + 取消检查点。"""

    def __init__(self, budget_tokens: int, throttle_threshold: float = 0.9):
        if not isinstance(budget_tokens, int) or isinstance(budget_tokens, bool) \
                or budget_tokens <= 0:
            raise ValueError(f"budget_tokens 必须为正整数，当前值: {budget_tokens!r}")
        if not 0.0 < throttle_threshold <= 1.0:
            raise ValueError(
                f"throttle_threshold 必须落在 (0, 1] 区间，当前值: {throttle_threshold!r}"
            )
        self.budget_tokens = budget_tokens
        self.throttle_threshold = throttle_threshold
        self.used_tokens = 0
        self._cancel_check: Callable[[], bool] | None = None
        self.cancelled = False

    def record(self, total_tokens: int) -> None:
        """累计一次 LLM 调用的用量（input + output）。"""
        self.used_tokens += max(0, int(total_tokens))

    def attach_cancel_check(self, check: Callable[[], bool]) -> None:
        """注入取消旗标检查（ensure_allowed 复用为取消检查点）。"""
        self._cancel_check = check

    @property
    def ratio(self) -> float:
        return self.used_tokens / self.budget_tokens

    @property
    def remaining(self) -> int:
        """距总闸还剩多少 token（可为负，表示已超支）。"""
        return self.budget_tokens - self.used_tokens

    @property
    def throttling(self) -> bool:
        """省 token 模式：≥阈值后压缩辩论轮数等非必要消耗。"""
        return self.ratio >= self.throttle_threshold

    @property
    def exceeded(self) -> bool:
        return self.used_tokens >= self.budget_tokens

    def ensure_allowed(self) -> None:
        """调用前检查：取消旗标 / 超预算即抛错（不静默继续）。"""
        if self._cancel_check is not None and self._cancel_check():
            self.cancelled = True
            raise TaskCancelledError("任务已被用户取消（协作式取消检查点）")
        if self.exceeded:
            raise BudgetExceededError(
                f"任务 token 总预算已耗尽: {self.summary()}（总闸）"
            )

    def summary(self) -> str:
        """用量摘要（落盘与看板展示）。"""
        return f"{self.used_tokens} / {self.budget_tokens} token（{self.ratio:.1%}）"
