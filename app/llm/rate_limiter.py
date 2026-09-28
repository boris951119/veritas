"""全局限流器（M8-5）：令牌桶按供应商排队，超限等待而非报错。

设计锚点（v0.4.md M8-5）：
- 令牌桶控制对同一供应商的并发请求节奏，容量=burst、回填速率=rps；
- 超限排队（阻塞等待）而非直接报错——排队耐心换任务成功率；
- 429 退避由 9 章既有重试机制处理（_call_with_retry），本模块只负责
  「发出去之前」的节奏控制，两层互不替代；
- 供应商键提取：`openai/glm-4-plus` → `openai`（同供应商模型共享桶）；
  无前缀的裸模型按模型名自成一桶（确定性，不做成本映射查询）；
- clock_fn / sleep_fn 为注入点（测试用假时钟，单线程确定验证）。
"""

from __future__ import annotations

import threading
import time
from typing import Callable


def provider_of(model: str) -> str:
    """从 litellm 风格模型名提取供应商键（确定性规则，D.1）。"""
    return model.split("/", 1)[0] if "/" in model else model


class _Bucket:
    """单供应商令牌桶（锁 + 时间回填）。"""

    __slots__ = ("lock", "tokens", "last")

    def __init__(self, burst: float, now: float):
        self.lock = threading.Lock()
        self.tokens = float(burst)
        self.last = now


class RateLimiter:
    """进程级全局限流器：每供应商一个桶，跨 ModelClient 实例共享。

    acquire() 阻塞至拿到令牌，返回累计等待秒数（0 = 未排队）。
    无锁休眠（sleep 在锁外）：等待者不阻塞其他供应商的线程，
    同供应商线程在循环重试中自然排队（先到先醒，非严格 FIFO）。
    """

    def __init__(
        self,
        rps: float,
        burst: int,
        clock_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ):
        if rps <= 0:
            raise ValueError(f"rps 必须为正数，当前: {rps}")
        if burst < 1:
            raise ValueError(f"burst 必须 >= 1，当前: {burst}")
        self._rps = float(rps)
        self._burst = float(burst)
        self._clock = clock_fn or time.monotonic
        self._sleep = sleep_fn or time.sleep
        self._buckets: dict[str, _Bucket] = {}
        self._registry_lock = threading.Lock()

    def _bucket_for(self, provider: str) -> _Bucket:
        with self._registry_lock:
            bucket = self._buckets.get(provider)
            if bucket is None:
                bucket = _Bucket(self._burst, self._clock())
                self._buckets[provider] = bucket
            return bucket

    def acquire(self, provider: str) -> float:
        """取一枚令牌（阻塞）。返回累计等待秒数（观测用）。"""
        bucket = self._bucket_for(provider)
        waited = 0.0
        while True:
            with bucket.lock:
                now = self._clock()
                elapsed = now - bucket.last
                # 时间回填：不超过桶容量
                bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._rps)
                bucket.last = now
                if bucket.tokens >= 1.0:
                    bucket.tokens -= 1.0
                    return waited
                wait = (1.0 - bucket.tokens) / self._rps
            self._sleep(wait)
            waited += wait
