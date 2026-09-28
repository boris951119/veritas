"""ModelClient（移植版）行为保持：桩注入、瞬态退避、json_mode 降级、
预算闸、密钥快速失败。全部走桩 completion_fn，零网络零 key。"""

import pytest

from app.config import Settings
from app.llm.budget import BudgetExceededError, BudgetGuard
from app.llm.model_client import LLMResponse, MissingApiKeyError, ModelClient


def _resp(content="ok", finish="stop", prompt=10, completion=5):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


def _settings(**kw) -> Settings:
    kw.setdefault("models", ["test-model"])
    return Settings(models=kw.pop("models"), llm_max_retries=2,
                    retry_backoff_base=0.0, **kw)


def test_chat_success_and_accounting():
    calls = []

    def completion(**kw):
        calls.append(kw)
        return _resp("你好")

    client = ModelClient(_settings(), completion_fn=completion)
    result = client.chat("test-model", [{"role": "user", "content": "hi"}])
    assert isinstance(result, LLMResponse) and result.content == "你好"
    assert result.total_tokens == 15
    assert client.total_tokens_used == 15
    assert client.call_log[-1]["content_chars"] == 2
    assert len(calls) == 1
    # 第 2 层护栏：max_tokens 必带
    assert calls[0]["max_tokens"] == _settings().max_response_tokens


def test_transient_error_backoff_retry():
    attempts, sleeps = [], []

    def completion(**kw):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("429 rate limit, too many requests")
        return _resp("第三次成功")

    client = ModelClient(_settings(), completion_fn=completion,
                         sleep_fn=sleeps.append)
    result = client.chat("test-model", [{"role": "user", "content": "hi"}])
    assert result.content == "第三次成功"
    assert len(attempts) == 3 and len(sleeps) == 2


def test_timeout_switches_leg_immediately():
    attempts, sleeps = [], []

    def completion(**kw):
        attempts.append(1)
        raise TimeoutError("gateway hung")

    client = ModelClient(_settings(), completion_fn=completion,
                         sleep_fn=sleeps.append)
    with pytest.raises(RuntimeError, match="test-model"):
        client.chat("test-model", [{"role": "user", "content": "hi"}])
    assert len(attempts) == 1  # 超时不同腿重试：快通道上抛
    assert sleeps == []


def test_non_transient_raises_without_retry():
    attempts = []

    def completion(**kw):
        attempts.append(1)
        raise RuntimeError("401 invalid api key")

    client = ModelClient(_settings(), completion_fn=completion, sleep_fn=lambda s: None)
    with pytest.raises(RuntimeError):
        client.chat("test-model", [{"role": "user", "content": "hi"}])
    assert len(attempts) == 1


def test_json_mode_degrades_on_unsupported():
    seen_formats, attempts = [], []

    def completion(**kw):
        attempts.append(1)
        seen_formats.append(kw.get("response_format"))
        if len(attempts) == 1:
            raise RuntimeError("400 bad request: response_format json_object unsupported")
        return _resp("{}")

    client = ModelClient(_settings(), completion_fn=completion, sleep_fn=lambda s: None)
    result = client.chat("test-model", [{"role": "user", "content": "hi"}], json_mode=True)
    assert result.content == "{}"
    assert seen_formats[0] == {"type": "json_object"} and seen_formats[1] is None


def test_budget_guard_blocks_when_exhausted():
    client = ModelClient(_settings(), completion_fn=lambda **kw: _resp(),
                         budget_guard=BudgetGuard(budget_tokens=10))
    client.chat("test-model", [{"role": "user", "content": "hi"}])  # 用 15 token
    with pytest.raises(BudgetExceededError):
        client.chat("test-model", [{"role": "user", "content": "hi"}])


def test_missing_api_key_fails_fast(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = ModelClient(_settings(models=["test-model", "gpt-4o"]),
                         completion_fn=lambda **kw: _resp())
    with pytest.raises(MissingApiKeyError):
        client.chat("gpt-4o", [{"role": "user", "content": "hi"}])


def test_truncation_flagged():
    def completion(**kw):
        return _resp("部分", finish="length")

    client = ModelClient(_settings(max_output_continuations=0),
                         completion_fn=completion)
    result = client.chat("test-model", [{"role": "user", "content": "hi"}])
    assert result.truncated is True
