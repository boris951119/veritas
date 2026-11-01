"""测试会话禁真调用的守卫（app/llm/model_client 的 RealCallGuardedError）。

这道守卫治的是钱：`ModelClient` 的调用点是
`completion = self._completion_fn or _default_completion_fn()`——**测试只要忘了
注入桩，就会静默走到真 litellm**，而 `.env` 里的网关 key 早在 `app/config.py`
import 时就进了进程。测试全绿、账单照扣，人只有月底才知道。

现在：忘了塞桩 = 当场炸；生产路径不上膛 = 行为一字不变。
"""

import pytest

from app.config import Settings
from app.llm.model_client import (
    ModelClient, RealCallGuardedError, _default_completion_fn,
    _default_embedding_fn, arm_no_real_calls, disarm_no_real_calls,
    real_call_guard_armed)


def _settings() -> Settings:
    return Settings(models=["test-model"], llm_max_retries=2, retry_backoff_base=0.0)


@pytest.fixture
def disarmed():
    """临时卸膛，用完必复原——守卫状态是进程级的，泄漏会骗过后面的测试。"""
    disarm_no_real_calls()
    try:
        yield
    finally:
        arm_no_real_calls()


def test_conftest_arms_the_guard_for_the_whole_session():
    """上膛由 tests/conftest.py 负责：跑任何测试时它必须已经是武装态。"""
    assert real_call_guard_armed()


def test_default_completion_loader_is_blocked_when_armed():
    with pytest.raises(RealCallGuardedError, match="禁止真发起"):
        _default_completion_fn()


def test_default_embedding_loader_is_blocked_when_armed():
    with pytest.raises(RealCallGuardedError, match="embedding"):
        _default_embedding_fn()


def test_forgotten_stub_fails_loudly_instead_of_spending_money():
    """复现那个危险场景：建了真 ModelClient、忘了注入桩、直接 chat()。"""
    client = ModelClient(_settings())          # completion_fn 缺省 = None
    with pytest.raises(RealCallGuardedError, match="没有注入"):
        client.chat("test-model", [{"role": "user", "content": "hi"}])


def test_injected_stubs_still_work_when_armed():
    """守卫不许误伤：注入桩的正常测试照跑，一个字都不该变。"""
    def completion(**kw):
        return {"choices": [{"message": {"content": "好"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2}}

    client = ModelClient(_settings(), completion_fn=completion)
    assert client.chat("test-model", [{"role": "user", "content": "hi"}]).content == "好"


def test_production_path_is_not_blocked(disarmed):
    """没上膛时不许拦——否则明天跑官方用例会被自己的守卫打死。

    卸膛后走的是懒加载 litellm 那条原路径：环境里有 litellm 就返回可调用对象，
    没装就抛 ImportError。**唯一不许出现的是 RealCallGuardedError**。
    """
    try:
        fn = _default_completion_fn()
    except ImportError:                        # 本机没装 litellm 也算通过
        pytest.fail("本仓库 requirements 含 litellm，此处不应缺失")
    assert callable(fn)


def test_call_sites_no_longer_fall_through_to_the_real_loader():
    """钉住成因：调用点不许再用 `or _default_*()` 这种静默兜底写法。

    守卫拦住了花钱，但真正的修复是**没注入就是配置错误**——否则将来有人
    在别处新写一个 `or _default_completion_fn()`，守卫只能 cover 那一个入口。
    """
    import inspect

    src = inspect.getsource(ModelClient)
    assert "self._completion_fn or _default_completion_fn()" not in src
    assert "self._embedding_fn or _default_embedding_fn()" not in src
