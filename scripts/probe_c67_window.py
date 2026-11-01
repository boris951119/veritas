"""C-67：每模探窗清单（默认 --dry-run＝零 HTTP 零模型零付费）。

跑法::

    PYTHONPATH=. .venv/bin/python scripts/probe_c67_window.py
    PYTHONPATH=. .venv/bin/python scripts/probe_c67_window.py --probe

--dry-run（默认）只打印将要探的模型清单；加 --probe 才对本机 Ollama
发 /api/show（超时 10s）。云端列一律标「未跑＝429」，不许拿声明冒充实吃。

纯函数 choose_window_tokens／list_models_to_probe 供 tests 真引用
（协议 §5 第 26 条；不进零引用豁免表）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from app.config import (  # noqa: E402
    MODEL_CTX_FALLBACK_DEFAULT,
    PROBE_ENDPOINT_UNPROBEABLE,
    PROBE_NO_NUM_CTX,
    Settings,
    choose_window_tokens,
    clear_model_ctx_probe_cache,
    parse_ollama_num_ctx,
    probe_model_num_ctx,
    resolve_model_window,
    resolve_panel_min_window,
)

# 再导出，方便测试 `from scripts.probe_c67_window import choose_window_tokens`
__all__ = [
    "choose_window_tokens",
    "list_models_to_probe",
    "parse_ollama_num_ctx",
    "probe_model_num_ctx",
    "resolve_model_window",
    "resolve_panel_min_window",
    "main",
]


def list_models_to_probe(settings: Settings | None = None) -> list[str]:
    """将要探的模型清单（roster／config models ∪ 每模声明表的键），去重保序。"""
    s = settings or Settings.from_env()
    seen: set[str] = set()
    out: list[str] = []
    for m in list(s.models) + list(s.model_context_tokens_by_model.keys()):
        name = str(m).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C-67 每模探窗")
    parser.add_argument(
        "--probe", action="store_true",
        help="真发本机 Ollama /api/show（默认 --dry-run＝零 HTTP）")
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="只打印清单（默认；与 --probe 互斥时以 --probe 为准）")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    models = list_models_to_probe(settings)
    fallback = int(settings.model_context_fallback_tokens
                   or MODEL_CTX_FALLBACK_DEFAULT)

    print(f"C-67 探窗清单 n={len(models)} "
          f"fallback={fallback} "
          f"global_ctx={settings.model_context_tokens} "
          f"by_model={len(settings.model_context_tokens_by_model)}")
    for m in models:
        print(f"  - {m}")

    if not args.probe:
        print("mode=dry-run（零 HTTP 零模型零付费；加 --probe 才真发）")
        return 0

    print("mode=probe（本机 Ollama /api/show，timeout=10s；"
          "云端名 404＝探不到，交账标未跑＝429）")
    clear_model_ctx_probe_cache()
    # 与 app.config.probe_model_num_ctx 同口径：只打本机 Ollama，
    # 不把云端 OPENAI_BASE_URL 当 /api/show 根。
    for m in models:
        value = probe_model_num_ctx(m, timeout=10.0, use_cache=True)
        rec = resolve_model_window(settings, m, do_probe=True)
        print(f"  {m}: probed={value!r} → window={rec['window_tokens']} "
              f"source={rec['source']} rule={rec['rule']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
