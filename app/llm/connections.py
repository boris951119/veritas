"""模型连接注册表：按模型名/前缀解析 api_key 与 base_url。

来源优先级：config.json 的 connections 段 > 环境变量（litellm 自读
OPENAI_API_KEY / OPENAI_BASE_URL，本模块只服务显式注册的场景）。

config.json 示例::

    {
      "connections": {
        "openai/": {"api_key": "sk-...", "base_url": "https://gw.example.com/v1"}
      }
    }

键既可以是完整模型名（"openai/gpt-4o"）也可以是前缀（"openai/"），
最长匹配优先。解析失败/无命中一律返回 None（调用方回落环境变量路径）。
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_connections() -> dict[str, dict[str, str]]:
    path = _REPO_ROOT / "config.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    conns = data.get("connections") if isinstance(data, dict) else None
    if not isinstance(conns, dict):
        return {}
    return {
        str(k): {str(ik): str(iv) for ik, iv in v.items() if isinstance(iv, (str, int))}
        for k, v in conns.items() if isinstance(v, dict)
    }


def resolve_credentials(model: str) -> dict[str, str] | None:
    """按「完整名 > 最长前缀」解析连接凭据；无命中返回 None。"""
    conns = _load_connections()
    if model in conns:
        return conns[model]
    matches = [key for key in conns if model.startswith(key)]
    if not matches:
        return None
    return conns[max(matches, key=len)]
