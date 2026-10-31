"""本机 Ollama HTTP 客户端（摘要 + embedding；不发付费云）。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.kg_lab.config import EMBED_MODEL, OLLAMA_HOST, SUMMARY_MODEL, SUMMARY_NUM_PREDICT


def _post(path: str, payload: dict[str, Any], *, timeout: float = 600.0) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}{path}",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama 不可达 {OLLAMA_HOST}{path}: {e}") from e


def generate_json(
    prompt: str,
    *,
    model: str = SUMMARY_MODEL,
    num_predict: int = SUMMARY_NUM_PREDICT,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """调用 /api/generate，要求 JSON；解析失败时返回空结构。"""
    # qwen3 默认会先 think，吃掉 num_predict → 空 JSON；显式关闭。
    data = _post("/api/generate", {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        },
    })
    text = (data.get("response") or "").strip()
    try:
        obj = json.loads(text) if text else {}
    except json.JSONDecodeError:
        obj = {}
    if not isinstance(obj, dict):
        obj = {}
    return {
        "parsed": obj,
        "raw": text,
        "eval_count": data.get("eval_count"),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "total_duration_ns": data.get("total_duration"),
    }


def embed(text: str, *, model: str = EMBED_MODEL) -> list[float]:
    data = _post("/api/embeddings", {
        "model": model,
        "prompt": text or " ",
    }, timeout=120.0)
    vec = data.get("embedding") or []
    return [float(x) for x in vec]
