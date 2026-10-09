"""工作台模型接入：本机落盘 + 进程内环境变量，供页面配置。

文件默认 `.workbench_llm.json`（已 gitignore），不进仓库。
一个 Base URL + 一个 Key + 多个模型 ID（首个为主模型；其余作回退
或按角色轮转异构）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SETTINGS_PATH = _REPO_ROOT / ".workbench_llm.json"
_ROLE_CN = {
    "mainstream": "主流视角",
    "redteam": "质疑视角",
    "technologist": "技术视角",
}


def settings_path() -> Path:
    override = (os.environ.get("VERITAS_WORKBENCH_LLM") or "").strip()
    return Path(override) if override else _SETTINGS_PATH


def _read() -> dict:
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_models(raw) -> list[str]:
    """人话输入 → 去重保序的模型列表。

    支持：列表、逗号/分号/换行分隔；忽略空行与 # 注释。
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        parts = re.split(r"[,;\n]+", str(raw))
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        m = str(p).strip()
        if not m or m.startswith("#"):
            continue
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def normalize_model_ids(models: list[str], *, base_url: str = "") -> list[str]:
    """OpenAI 兼容网关下，裸模型名自动加 openai/ 前缀。

    否则 litellm 会把 deepseek-* 当成官方 DeepSeek，去要
    DEEPSEEK_API_KEY，而工作台实际走的是 OPENAI_API_KEY + base_url。
    """
    compat = bool(str(base_url or "").strip())
    out: list[str] = []
    seen: set[str] = set()
    for m in models:
        mid = str(m).strip()
        if not mid:
            continue
        if compat and "/" not in mid:
            mid = f"openai/{mid}"
        if mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out


def models_from_data(data: dict) -> list[str]:
    models = parse_models(data.get("models"))
    if not models:
        models = parse_models(data.get("model"))
    if not models:
        models_env = (os.environ.get("VERITAS_MODELS")
                      or os.environ.get("VERITAS_MODEL") or "")
        models = parse_models(models_env)
    if not models:
        models = ["openai/deepseek-v4-flash"]
    # 只按落盘 base_url 补前缀；勿用进程里残留的 OPENAI_BASE_URL，
    # 否则单测/换配置会误给裸名加上 openai/
    return normalize_model_ids(
        models, base_url=str(data.get("base_url") or ""))


def assignment_preview(models: list[str], hetero: bool) -> list[dict]:
    """三个分析师将用哪个模型（给页面看的人话分工）。"""
    from app.agents.panel import DEFAULT_ROSTER

    models = models or ["（未填）"]
    rows = []
    for i, (name, _persona) in enumerate(DEFAULT_ROSTER):
        if hetero and len(models) >= 2:
            mid = models[i % len(models)]
        else:
            mid = models[0]
        rows.append({
            "role": name,
            "role_cn": _ROLE_CN.get(name, name),
            "model": mid,
        })
    return rows


def apply_to_environ(data: dict | None = None) -> None:
    """把已保存配置注入当前进程（litellm / Settings 都读环境变量）。"""
    data = _read() if data is None else data
    key = str(data.get("api_key") or "").strip()
    base = str(data.get("base_url") or "").strip()
    models = models_from_data(data)
    # 若 data 里根本没配模型，不要用默认值污染环境
    has_saved = bool(parse_models(data.get("models"))
                     or parse_models(data.get("model")))
    if key:
        os.environ["OPENAI_API_KEY"] = key
    elif data.get("forget_env_key"):
        # 用户选择「不保存」：本进程也不再沿用环境变量里的旧 key
        os.environ.pop("OPENAI_API_KEY", None)
    if base:
        os.environ["OPENAI_BASE_URL"] = base
    if has_saved and models:
        os.environ["VERITAS_MODELS"] = ",".join(models)


def mask_key(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return k[:2] + "***"
    return k[:4] + "…" + k[-4:]


def llm_status() -> dict:
    """页面展示用：不回传完整 key。"""
    data = _read()
    file_key = str(data.get("api_key") or "").strip()
    env_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if file_key:
        key = file_key
        source = "workbench"
    elif env_key and not data.get("forget_env_key"):
        key = env_key
        source = "env"
    else:
        key = ""
        source = "none"
    base = str(data.get("base_url") or "").strip() or (
        os.environ.get("OPENAI_BASE_URL") or "").strip()
    models = models_from_data(data)
    # hetero：多模型时默认开启角色轮转；单模型强制关
    if "hetero" in data:
        hetero = bool(data.get("hetero"))
    else:
        hetero = len(models) >= 2
    if len(models) < 2:
        hetero = False
    force_demo = bool(data.get("force_demo"))
    has_key = bool(key)
    live = has_key and not force_demo
    return {
        "has_key": has_key,
        "key_hint": mask_key(key) if has_key else "",
        "base_url": base,
        "model": models[0],
        "models": models,
        "hetero": hetero,
        "assignment": assignment_preview(models, hetero),
        "force_demo": force_demo,
        "mode": "live" if live else "demo",
        "source": source,
        "forget_env_key": bool(data.get("forget_env_key")),
    }


def save_llm_settings(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    models: list[str] | str | None = None,
    hetero: bool | None = None,
    force_demo: bool | None = None,
) -> dict:
    """保存。api_key=None 表示不改；空串表示清除。"""
    data = _read()
    if api_key is not None:
        key = api_key.strip()
        if key:
            data["api_key"] = key
            data.pop("forget_env_key", None)  # 重新接入则恢复可用环境 key
        else:
            data.pop("api_key", None)
            data["forget_env_key"] = True
    if base_url is not None:
        base = base_url.strip()
        if base:
            data["base_url"] = base
        else:
            data.pop("base_url", None)
    # models 优先；兼容旧字段 model
    if models is not None:
        parsed = parse_models(models)
        if parsed:
            parsed = normalize_model_ids(
                parsed, base_url=str(data.get("base_url") or ""))
            data["models"] = parsed
            data["model"] = parsed[0]
        else:
            data.pop("models", None)
            data.pop("model", None)
    elif model is not None:
        parsed = parse_models(model)
        if parsed:
            parsed = normalize_model_ids(
                parsed, base_url=str(data.get("base_url") or ""))
            data["models"] = parsed
            data["model"] = parsed[0]
        else:
            data.pop("models", None)
            data.pop("model", None)
    elif data.get("models") or data.get("model"):
        # 已有配置：网关 + 裸名时补前缀（修历史误填）
        raw = parse_models(data.get("models")) or parse_models(data.get("model"))
        fixed = normalize_model_ids(
            raw, base_url=str(data.get("base_url") or ""))
        if fixed:
            data["models"] = fixed
            data["model"] = fixed[0]
    if hetero is not None:
        data["hetero"] = bool(hetero)
    if force_demo is not None:
        data["force_demo"] = bool(force_demo)
    _write(data)
    if api_key is not None and not api_key.strip():
        os.environ.pop("OPENAI_API_KEY", None)
    apply_to_environ(data)
    return llm_status()


def discard_session_key() -> dict:
    """退出时选「不保存」：删掉本软件记住的 key，并忽略环境变量旧 key。"""
    return save_llm_settings(api_key="")


def keep_session_key() -> dict:
    """退出时选「确定保存」：保留当前已接入配置，供下次启动复用。"""
    data = _read()
    data.pop("forget_env_key", None)
    _write(data)
    apply_to_environ(data)
    return llm_status()


def is_live_mode() -> bool:
    return llm_status()["mode"] == "live"


def workbench_roster() -> list[tuple[str, str, str | None]] | None:
    """多模型且开启异构时，给三个分析师轮转挂模型；否则 None（全用主模型）。"""
    from app.agents.panel import DEFAULT_ROSTER

    st = llm_status()
    models = st.get("models") or []
    if not st.get("hetero") or len(models) < 2:
        return None
    return [
        (name, persona, models[i % len(models)])
        for i, (name, persona) in enumerate(DEFAULT_ROSTER)
    ]


# 服务启动时若已有落盘配置，先注入进程
apply_to_environ()
