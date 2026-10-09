"""工作台页面接入模型：落盘、掩码、模式切换。"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.server import create_app
from app.workbench_llm import (
    apply_to_environ,
    is_live_mode,
    llm_status,
    mask_key,
    normalize_model_ids,
    parse_models,
    save_llm_settings,
    workbench_roster,
)


def test_mask_key():
    assert mask_key("sk-abcdefghij") == "sk-a…ghij"
    assert mask_key("") == ""


def test_parse_models_human_input():
    assert parse_models("a\nb\nc") == ["a", "b", "c"]
    assert parse_models("a, b; c") == ["a", "b", "c"]
    assert parse_models("# x\na\na") == ["a"]


def test_normalize_bare_model_for_openai_gateway(tmp_path, monkeypatch):
    assert normalize_model_ids(
        ["deepseek-v4-flash-0731"],
        base_url="https://example.com/v1",
    ) == ["openai/deepseek-v4-flash-0731"]
    assert normalize_model_ids(
        ["openai/qwen3.8-max"],
        base_url="https://example.com/v1",
    ) == ["openai/qwen3.8-max"]
    path = tmp_path / "llm.json"
    monkeypatch.setenv("VERITAS_WORKBENCH_LLM", str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    st = save_llm_settings(
        api_key="sk-test-key-123456",
        base_url="https://example.com/v1",
        model="deepseek-v4-flash-0731",
    )
    assert st["model"] == "openai/deepseek-v4-flash-0731"


def test_save_and_status_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "llm.json"
    monkeypatch.setenv("VERITAS_WORKBENCH_LLM", str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    st = save_llm_settings(
        api_key="sk-test-key-123456",
        base_url="https://example.com/v1",
        model="openai/deepseek-v4-flash",
        force_demo=False,
    )
    assert st["mode"] == "live"
    assert st["has_key"] is True
    assert "sk-t" in st["key_hint"]
    assert "123456" not in st["key_hint"] or "…" in st["key_hint"]
    assert is_live_mode() is True
    assert os.environ.get("OPENAI_API_KEY") == "sk-test-key-123456"

    st2 = save_llm_settings(force_demo=True)
    assert st2["mode"] == "demo"
    assert st2["has_key"] is True

    st3 = save_llm_settings(api_key="")
    assert st3["has_key"] is False
    assert st3["mode"] == "demo"
    assert "OPENAI_API_KEY" not in os.environ


def test_env_key_counts_as_live_without_file(tmp_path, monkeypatch):
    path = tmp_path / "empty.json"
    monkeypatch.setenv("VERITAS_WORKBENCH_LLM", str(path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env-xxxxxx")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    apply_to_environ({})
    st = llm_status()
    assert st["has_key"] is True
    assert st["mode"] == "live"
    assert st["source"] == "env"


def test_llm_api_endpoints(tmp_path, monkeypatch):
    path = tmp_path / "api.json"
    monkeypatch.setenv("VERITAS_WORKBENCH_LLM", str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cases = tmp_path / "cases"
    cases.mkdir()
    client = TestClient(create_app(cases_root=cases))

    empty = client.get("/api/llm").json()
    assert empty["mode"] == "demo" and empty["has_key"] is False

    saved = client.post("/api/llm", json={
        "api_key": "ak_demo_secret_key_99",
        "base_url": "https://api.example.com/v1",
        "models": ["openai/qwen3.8-max", "openai/glm-5.3", "openai/deepseek-v4-flash"],
        "hetero": True,
        "force_demo": False,
    }).json()
    assert saved["mode"] == "live"
    assert saved["models"] == [
        "openai/qwen3.8-max", "openai/glm-5.3", "openai/deepseek-v4-flash"]
    assert saved["hetero"] is True
    assert len(saved["assignment"]) == 3
    assert saved["assignment"][0]["model"] == "openai/qwen3.8-max"
    assert saved["assignment"][1]["model"] == "openai/glm-5.3"
    assert "ak_d" in saved["key_hint"]
    assert "secret" not in saved["key_hint"]

    again = client.get("/api/llm").json()
    assert again["model"] == "openai/qwen3.8-max"
    assert again["base_url"] == "https://api.example.com/v1"

    # 留空 key 不覆盖；关异构则三角色共用主模型
    keep = client.post("/api/llm", json={
        "models": "openai/glm-5.3\nopenai/qwen3.8-max",
        "hetero": False,
        "force_demo": True,
    }).json()
    assert keep["has_key"] is True and keep["mode"] == "demo"
    assert keep["model"] == "openai/glm-5.3"
    assert keep["hetero"] is False
    assert all(a["model"] == "openai/glm-5.3" for a in keep["assignment"])


def test_exit_discard_forgets_env_key(tmp_path, monkeypatch):
    from app.workbench_llm import discard_session_key, keep_session_key

    path = tmp_path / "exit.json"
    monkeypatch.setenv("VERITAS_WORKBENCH_LLM", str(path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-should-forget")
    st = save_llm_settings(api_key="sk-ui-saved-key-xx", force_demo=False)
    assert st["has_key"] is True
    gone = discard_session_key()
    assert gone["has_key"] is False
    assert gone["forget_env_key"] is True
    # 环境变量仍在进程里时也不应再被当成已接入
    assert llm_status()["has_key"] is False
    keep_session_key()  # 仅清 forget 标记；无 file key 时仍无 key
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_exit_api(tmp_path, monkeypatch):
    path = tmp_path / "exit-api.json"
    monkeypatch.setenv("VERITAS_WORKBENCH_LLM", str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cases = tmp_path / "cases"
    cases.mkdir()
    client = TestClient(create_app(cases_root=cases))
    client.post("/api/llm", json={"api_key": "sk-exit-test-key-01", "force_demo": False})
    keep = client.post("/api/llm/exit-keep").json()
    assert keep["has_key"] is True
    discard = client.post("/api/llm/exit-discard").json()
    assert discard["has_key"] is False


def test_workbench_roster_rotates(tmp_path, monkeypatch):
    path = tmp_path / "roster.json"
    monkeypatch.setenv("VERITAS_WORKBENCH_LLM", str(path))
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    save_llm_settings(
        models=["m1", "m2", "m3"], hetero=True, force_demo=True)
    roster = workbench_roster()
    assert roster is not None
    assert [r[2] for r in roster] == ["m1", "m2", "m3"]
    save_llm_settings(hetero=False)
    assert workbench_roster() is None
