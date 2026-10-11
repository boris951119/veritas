"""研判全程进度：各环节开始/结束 + 耗时（秒），落盘供工作台轮询。

批式管线无法 SSE 流式推送时，用 progress.json 做可见性：浏览器边跑边刷。
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

# 当前跑次的进度器。按线程隔离，并行研判各写各的 progress.json。
_ACTIVE: ContextVar["RunProgress | None"] = ContextVar(
    "veritas_run_progress", default=None)

# 稳定中文标签（UI / 报告共用）
STEP_LABELS: dict[str, str] = {
    "ingest": "读取资料并切片",
    "hygiene": "议题预检·对撞·去重·相关性",
    "clarify": "议题回读确认（槽位未齐）",
    "material": "BM25 精排与预算装箱",
    "probe": "模型纪律画像探测",
    "panel": "三分析师并行研判",
    "citation": "引文逐字核对",
    "repair": "打回修复环",
    "collab": "归并·冲突·质证·仲裁",
    "chair": "主席汇总",
    "finalize": "置信度与报告落盘",
    "done": "完成",
}


def set_active_progress(prog: "RunProgress | None") -> None:
    _ACTIVE.set(prog)


def get_active_progress() -> "RunProgress | None":
    return _ACTIVE.get()


class RunProgress:
    """写入 out_dir/progress.json：current + steps[] + 累计秒。"""

    def __init__(self, out_dir: Path | None):
        self.out_dir = Path(out_dir) if out_dir else None
        self.run_t0 = time.monotonic()
        self.steps: list[dict[str, Any]] = []
        self._open: dict[str, Any] | None = None
        self._open_t0: float | None = None
        self.step: str = "init"

    @property
    def elapsed_total(self) -> float:
        return round(time.monotonic() - self.run_t0, 2)

    def start(self, step_id: str, label: str | None = None,
              **detail: Any) -> None:
        self._close_open()
        self.step = step_id
        self._open_t0 = time.monotonic()
        self._open = {
            "id": step_id,
            "label": label or STEP_LABELS.get(step_id, step_id),
            "status": "running",
            "started_s": round(self._open_t0 - self.run_t0, 2),
            "elapsed_s": None,
            "detail": {k: v for k, v in detail.items() if v is not None},
        }
        self.steps.append(self._open)
        self.flush()

    def note(self, **detail: Any) -> None:
        if not self._open:
            return
        self._open.setdefault("detail", {}).update(
            {k: v for k, v in detail.items() if v is not None})
        if self._open_t0 is not None:
            self._open["elapsed_s"] = round(
                time.monotonic() - self._open_t0, 2)
        self.flush()

    def finish(self, **detail: Any) -> None:
        if detail:
            self.note(**detail)
        self._close_open()
        self.flush()

    def complete(self, **extra: Any) -> None:
        """整次研判结束。"""
        self._close_open()
        self.step = "done"
        self.steps.append({
            "id": "done",
            "label": STEP_LABELS["done"],
            "status": "done",
            "started_s": self.elapsed_total,
            "elapsed_s": 0.0,
            "detail": {k: v for k, v in extra.items() if v is not None},
        })
        self.flush(extra=extra)

    def _close_open(self) -> None:
        if not self._open or self._open_t0 is None:
            self._open = None
            self._open_t0 = None
            return
        self._open["status"] = "done"
        self._open["elapsed_s"] = round(
            time.monotonic() - self._open_t0, 2)
        self._open = None
        self._open_t0 = None

    def flush(self, extra: dict[str, Any] | None = None) -> None:
        if self.out_dir is None:
            return
        self.out_dir.mkdir(parents=True, exist_ok=True)
        # running 步刷新瞬时耗时
        if self._open is not None and self._open_t0 is not None:
            self._open["elapsed_s"] = round(
                time.monotonic() - self._open_t0, 2)
        payload: dict[str, Any] = {
            "step": self.step,
            "label": STEP_LABELS.get(self.step, self.step),
            "elapsed_s": self.elapsed_total,
            "steps": self.steps,
        }
        if extra:
            payload.update(extra)
        (self.out_dir / "progress.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def mark_failed(self, reason: str) -> None:
        """后台线程里的失败落盘，轮询方据此停止等待。"""
        self._close_open()
        self.step = "error"
        self.flush(extra={"status": "error", "error": str(reason)[:300]})

    def mark_cancelled(self, reason: str = "用户终止") -> None:
        """协作式取消落盘：面板立刻可见，不再装成「还在跑」。"""
        self._close_open()
        self.step = "cancelled"
        self.flush(extra={
            "status": "cancelled",
            "label": "已终止",
            "hint": reason,
        })

    @contextmanager
    def stage(self, step_id: str, label: str | None = None,
              **detail: Any) -> Iterator["RunProgress"]:
        self.start(step_id, label, **detail)
        try:
            yield self
        finally:
            self.finish()


def ensure_progress(out_dir: Path | None) -> RunProgress:
    """取得当前进度器；无则按 out_dir 新建并设为 active。"""
    prog = get_active_progress()
    if prog is not None:
        if out_dir and prog.out_dir is None:
            prog.out_dir = Path(out_dir)
        return prog
    prog = RunProgress(out_dir)
    set_active_progress(prog)
    return prog
