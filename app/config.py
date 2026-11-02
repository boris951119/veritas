"""集中配置管理（veritas 版，自 token-burner 范式精简）。

职责：
1. 密钥仅走环境变量（不硬编码、不进 git），.env 由本模块在 import 时
   幂等加载（不覆盖已存在的环境变量）；
2. 集中收敛模型链、护栏、预算等可调参数——ModelClient 的全部行为参数
   都从 Settings 读取；
3. config.json 可覆盖模型清单与预算（密钥不参与文件覆盖）。

config.json 示例::

    {
      "models": ["openai/gpt-4o", "openai/deepseek-chat"],
      "budget_tokens": 800000
    }

模型命名走 litellm 惯例：`openai/<model>` 走 OpenAI 兼容网关
（读 OPENAI_API_KEY / OPENAI_BASE_URL），`deepseek/`、`anthropic/`、
`gemini/` 前缀走对应官方供应商。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """极简 .env 加载：KEY=VALUE 逐行，已存在的环境变量不覆盖。"""
    env = path or _REPO_ROOT / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

_CORPUS_SELECT_MAX_DEFAULT = 100
_INGEST_MAX_FILES_DEFAULT = 500
_INGEST_MAX_DEPTH_DEFAULT = 3

# C-67：探不到且无每模声明时的保守常量（env VERITAS_MODEL_CTX_FALLBACK 可覆盖）。
# 出处＝架构师建议档；〔150〕本机实测见过「Modelfile 没写 num_ctx ⇒ 运行时回退 2048」
# ⇒ 本值对那种端点仍可能偏大，披露必须点名方向风险，不许报成「安全」。
# 取值路都不许乘固定比例。R-C67-1：仅「端点可探但无 num_ctx」才落本常量；
# 「端点不可探」改走全局假定值（unchecked_global），不许静默当实测。
MODEL_CTX_FALLBACK_DEFAULT = 4096

# 探窗三态（R-C67-1）：正整数＝探到生效 num_ctx；
# no_num_ctx＝端点可探（拿到 /api/show）但 parameters 无 num_ctx；
# endpoint_unprobeable＝拿不到 /api/show（404／非 Ollama／连接失败等）。
# 调用方不许靠异常类型猜 A／B——本函数直接返回这三态。
PROBE_NO_NUM_CTX = "no_num_ctx"
PROBE_ENDPOINT_UNPROBEABLE = "endpoint_unprobeable"

# 进程内探窗缓存：同模不重探。值＝正整数｜三态哨兵。
_MODEL_CTX_PROBE_CACHE: dict[str, int | str] = {}


def _coerce_positive_int(
        raw, *, default: int, name: str) -> tuple[int, str | None]:
    """合法 ≥1 的整数 → (n, None)；否则回落 default＋披露句。禁止 0＝无限制。"""
    if isinstance(raw, bool):
        return default, f"{name}={raw!r} 非法（布尔），回落 {default}"
    if isinstance(raw, int):
        if raw >= 1:
            return raw, None
        return default, f"{name}={raw!r} 非法（须≥1），回落 {default}"
    if isinstance(raw, str):
        text = raw.strip()
        try:
            n = int(text, 10)
        except ValueError:
            return default, f"{name}={raw!r} 非整数，回落 {default}"
        if n >= 1:
            return n, None
        return default, f"{name}={raw!r} 非法（须≥1），回落 {default}"
    return default, f"{name}={raw!r} 非法，回落 {default}"


def _coerce_corpus_select_max(raw) -> tuple[int, str | None]:
    """解析纳入上限：合法 ≥1 的整数 → (n, None)；否则回落 100＋披露句。

    MAX 没有「关掉」语义（MIN=0 才有）；不得把 0 当无限制。
    """
    return _coerce_positive_int(
        raw, default=_CORPUS_SELECT_MAX_DEFAULT,
        name="corpus_select_max_sources")


def clear_model_ctx_probe_cache() -> None:
    """测试／探针复位用：清空进程内探窗缓存。"""
    _MODEL_CTX_PROBE_CACHE.clear()


def _bare_model_name(model: str) -> str:
    """litellm 前缀剥掉：openai/veritas-qwen3-14b → veritas-qwen3-14b。"""
    text = str(model or "").strip()
    if "/" in text:
        return text.split("/", 1)[-1]
    return text


def parse_ollama_num_ctx(payload: dict) -> int | None:
    """从 Ollama /api/show JSON 取生效 num_ctx（优先 parameters，不是原生 context_length）。"""
    if not isinstance(payload, dict):
        return None
    params = str(payload.get("parameters") or "")
    # 形如 "num_ctx                        16384\n..."
    for line in params.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == "num_ctx":
            try:
                n = int(parts[1])
            except ValueError:
                continue
            if n > 0:
                return n
    # 兜底：parameters 里 num_ctx=N
    for token in params.replace("\n", " ").split():
        if token.startswith("num_ctx="):
            try:
                n = int(token.split("=", 1)[1])
            except ValueError:
                continue
            if n > 0:
                return n
    return None


def probe_model_num_ctx(
    model: str,
    *,
    base_url: str | None = None,
    timeout: float = 10.0,
    use_cache: bool = True,
) -> int | str:
    """读本机 Ollama /api/show 的生效 num_ctx；返回三态（R-C67-1）。

    - 正整数：parameters 里读到生效 num_ctx
    - PROBE_NO_NUM_CTX：端点可探（拿到 JSON）但未写 num_ctx
    - PROBE_ENDPOINT_UNPROBEABLE：拿不到 /api/show（404／连不上／非 JSON 等）

    同模进程内缓存。调用方按返回值分流，不许再靠异常类型猜 A／B。
    """
    key = str(model or "").strip()
    if not key:
        return PROBE_ENDPOINT_UNPROBEABLE
    if use_cache and key in _MODEL_CTX_PROBE_CACHE:
        return _MODEL_CTX_PROBE_CACHE[key]
    import urllib.request

    if base_url is not None:
        raw_base = base_url.strip()
    else:
        # 只探本机 Ollama（与 scripts/probe_context_window.py 同口径）。
        # 云端 OPENAI_BASE_URL 没有 /api/show ⇒ 不算探窗端点，直接走默认本机根。
        ollama = (os.environ.get("OLLAMA_BASE")
                  or os.environ.get("OLLAMA_HOST") or "").strip()
        openai_base = (os.environ.get("OPENAI_BASE_URL") or "").strip()
        if ollama:
            raw_base = ollama
        elif openai_base and (
                "127.0.0.1" in openai_base or "localhost" in openai_base):
            raw_base = openai_base
        else:
            raw_base = "http://127.0.0.1:11434"
    # OPENAI_BASE_URL／OLLAMA_BASE 常带 /v1；Ollama 原生口在根。
    root = raw_base.rsplit("/v1", 1)[0].rstrip("/")
    if not root:
        value: int | str = PROBE_ENDPOINT_UNPROBEABLE
        if use_cache:
            _MODEL_CTX_PROBE_CACHE[key] = value
        return value
    bare = _bare_model_name(key)
    try:
        req = urllib.request.Request(
            root + "/api/show",
            data=json.dumps({"model": bare}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            value = PROBE_ENDPOINT_UNPROBEABLE
        else:
            if not isinstance(payload, dict):
                value = PROBE_ENDPOINT_UNPROBEABLE
            else:
                n = parse_ollama_num_ctx(payload)
                value = int(n) if n is not None and int(n) > 0 else PROBE_NO_NUM_CTX
    except Exception:  # noqa: BLE001 — 连不上／404／超时＝端点不可探（态 A）
        value = PROBE_ENDPOINT_UNPROBEABLE
    if use_cache:
        _MODEL_CTX_PROBE_CACHE[key] = value
    return value


def lookup_declared_model_ctx(
    settings: "Settings", model: str,
) -> int | None:
    """运维手写的该模型声明窗；查完整名与裸名。没有 → None。"""
    table = getattr(settings, "model_context_tokens_by_model", None) or {}
    if not isinstance(table, dict) or not table:
        return None
    key = str(model or "").strip()
    if key in table:
        try:
            n = int(table[key])
        except (TypeError, ValueError):
            n = 0
        return n if n > 0 else None
    bare = _bare_model_name(key)
    if bare in table:
        try:
            n = int(table[bare])
        except (TypeError, ValueError):
            n = 0
        return n if n > 0 else None
    return None


def choose_window_tokens(
    probed: int | None,
    declared: int | None,
    fallback: int,
) -> tuple[int, str]:
    """取值顺序写死＝探到 ＞ 声明 ＞ 保守常量。返回 (tokens, source)。

    仅处理「已是正整数／None」的窄口（探针真引用格用）。
    端点不可探／无 num_ctx 的分流在 resolve_model_window（R-C67-1）。
    source ∈ {probed, declared, fallback}；无固定比例。
    """
    if probed is not None and int(probed) > 0:
        return int(probed), "probed"
    if declared is not None and int(declared) > 0:
        return int(declared), "declared"
    fb = int(fallback) if int(fallback) > 0 else MODEL_CTX_FALLBACK_DEFAULT
    return fb, "fallback"


def _unchecked_global_rec(model: str, global_n: int) -> dict:
    """端点不可探 → 沿用全局假定值（不是实测）。"""
    return {
        "model": str(model or ""),
        "window_tokens": int(global_n),
        "source": "unchecked_global",
        "rule": "align_to_window_未检查",
        "detail": (
            f"窗口未检查（端点不可探，沿用全局 {int(global_n)}）"
            f"＝假定值，不是实测"
        ),
    }


def _fallback_rec(model: str, tokens: int) -> dict:
    """端点可探但无 num_ctx → 保守常量（〔150〕裸标签风险）。"""
    return {
        "model": str(model or ""),
        "window_tokens": int(tokens),
        "source": "fallback",
        "rule": "align_to_window_未检查",
        "detail": (
            f"端点可探但该模型未写 num_ctx，落保守常量 {int(tokens)}（未检查；"
            f"〔150〕本机见过 Modelfile 未写 num_ctx 时运行时回退 2048，"
            f"本保守值仍可能偏大，不是安全保证）"
        ),
    }


def resolve_model_window(
    settings: "Settings",
    model: str,
    *,
    do_probe: bool = True,
    probe_fn=None,
) -> dict:
    """单模窗解析。返回 window_tokens／source／rule／detail。

    顺序（R-C67-1）＝探到正整数 ＞ 每模声明 ＞ env 显式全局当声明 ＞
    无 num_ctx→保守常量 ＞ 端点不可探→沿用全局假定值（unchecked_global）。
    """
    probe = probe_fn or probe_model_num_ctx
    probe_raw: int | str | None = None
    if do_probe:
        try:
            probe_raw = probe(model)
        except Exception:  # noqa: BLE001 — 探针抛错＝端点不可探（不靠类型细分）
            probe_raw = PROBE_ENDPOINT_UNPROBEABLE

    declared = lookup_declared_model_ctx(settings, model)
    # env 显式 VERITAS_MODEL_CTX_TOKENS 且无每模声明 → 当声明
    # （可压住「无 num_ctx→4096」；件③ 行为腿）。
    env_as_declared = False
    if declared is None and getattr(settings, "model_ctx_tokens_env_set", False):
        global_n = int(getattr(settings, "model_context_tokens", 0) or 0)
        if global_n > 0:
            declared = global_n
            env_as_declared = True

    fallback = int(getattr(settings, "model_context_fallback_tokens",
                           MODEL_CTX_FALLBACK_DEFAULT)
                   or MODEL_CTX_FALLBACK_DEFAULT)
    global_tokens = int(getattr(settings, "model_context_tokens", 0) or 0)

    # 1) 探到正整数
    if isinstance(probe_raw, int) and int(probe_raw) > 0:
        return {
            "model": str(model or ""),
            "window_tokens": int(probe_raw),
            "source": "probed",
            "rule": "align_to_window",
            "detail": "source=probed",
        }
    # 2) 声明（每模表或 env 显式）
    if declared is not None and int(declared) > 0:
        source = "env_global" if env_as_declared else "declared"
        return {
            "model": str(model or ""),
            "window_tokens": int(declared),
            "source": source,
            "rule": "align_to_window",
            "detail": f"source={source}",
        }
    # 3) 端点可探但无 num_ctx → 保守常量
    if probe_raw == PROBE_NO_NUM_CTX:
        return _fallback_rec(model, fallback)
    # 4) 端点不可探（或 do_probe 且返回未知哨兵）→ 沿用全局假定值
    if do_probe and (
            probe_raw == PROBE_ENDPOINT_UNPROBEABLE
            or probe_raw is None
            or (isinstance(probe_raw, str)
                and probe_raw not in (PROBE_NO_NUM_CTX,))):
        if global_tokens > 0:
            return _unchecked_global_rec(model, global_tokens)
        return _fallback_rec(model, fallback)
    # 5) do_probe=False 且无声明：保持窄口＝保守常量（单测常用）
    return _fallback_rec(model, fallback)


def resolve_panel_min_window(
    settings: "Settings",
    models: list[str],
    *,
    do_probe: bool = True,
    probe_fn=None,
) -> dict:
    """编队所用模型窗的最小值（甲＝保守）。models 空 ⇒ 退回 settings.models。"""
    names = [str(m).strip() for m in (models or []) if str(m).strip()]
    if not names:
        names = [str(m).strip() for m in (getattr(settings, "models", None)
                                          or []) if str(m).strip()]
    if not names:
        g = int(getattr(settings, "model_context_tokens", 0) or 0)
        if g > 0:
            rec = _unchecked_global_rec("", g)
            return {
                "window_tokens": rec["window_tokens"],
                "source": rec["source"],
                "rule": rec["rule"],
                "detail": "编队无模型名，沿用全局假定值",
                "per_model": [],
                "used_fallback": False,
            }
        fallback = int(getattr(settings, "model_context_fallback_tokens",
                               MODEL_CTX_FALLBACK_DEFAULT)
                       or MODEL_CTX_FALLBACK_DEFAULT)
        rec = _fallback_rec("", fallback)
        return {
            "window_tokens": rec["window_tokens"],
            "source": rec["source"],
            "rule": rec["rule"],
            "detail": rec["detail"],
            "per_model": [],
            "used_fallback": True,
        }
    per = [resolve_model_window(settings, m, do_probe=do_probe,
                                probe_fn=probe_fn) for m in names]
    # 取最小值；并列时优先 fallback／unchecked_global（披露更保守）
    _prio = {"fallback": 0, "unchecked_global": 1}
    best = min(per, key=lambda r: (
        int(r["window_tokens"]),
        _prio.get(str(r["source"]), 2)))
    used_fallback = any(r["source"] == "fallback" for r in per)
    return {
        "window_tokens": int(best["window_tokens"]),
        "source": best["source"],
        "rule": best["rule"],
        "detail": best["detail"],
        "per_model": per,
        "used_fallback": used_fallback,
    }


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_MODELS: tuple[str, ...] = (
    "openai/gpt-4o",
    "openai/deepseek-chat",
)

# 模型名称前缀 -> 环境变量名（litellm 供应商惯例命名）；
# 命中前缀而环境变量缺失 → ModelClient 调用前快速失败。
MODEL_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("openai/", "OPENAI_API_KEY"),
    ("gpt-", "OPENAI_API_KEY"),
    ("deepseek/", "DEEPSEEK_API_KEY"),
    ("deepseek-", "DEEPSEEK_API_KEY"),
    ("claude-", "ANTHROPIC_API_KEY"),
    ("anthropic/", "ANTHROPIC_API_KEY"),
    ("gemini/", "GEMINI_API_KEY"),
)


@dataclass
class Settings:
    """系统全部可调参数的唯一收敛点。"""

    # ---- 模型 ----
    models: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))

    # ---- 预算护栏 ----
    budget_tokens: int = 800_000          # 单次研判任务 token 总闸
    budget_throttle_threshold: float = 0.9

    # ---- 调用护栏（与 token-burner model_client 同名同义）----
    max_response_tokens: int = 8_000      # 单轮输出上限
    max_output_continuations: int = 2     # 截断续写次数上限
    llm_timeout_seconds: int = 120        # 单次调用超时
    llm_max_retries: int = 3              # 瞬态错误重试上限
    retry_backoff_base: float = 1.0       # 指数退避基数（秒）
    strict_json_response: bool = True     # json_mode 携带 response_format
    llm_wall_clock_seconds: int = 0       # 网关长挂防御墙钟（0=关）
    # 采样温度（None=不传，走网关默认）。演示/复现场景建议在 config.json
    # 设 0.2 左右：不追求严格确定，但显著收敛「同案例两跑冲突数 0↔1」
    # 这类语义抖动
    llm_temperature: float | None = None

    # skill 纪律注入总开关（A/B 对照用；VERITAS_SKILLS=0 关闭注入，
    # 机械闸照常运行——对照组只关「教」，不关「验」）
    skills_enabled: bool = True

    # 模型画像探测（自适应提示词）：真实调用前先 1 次探测给模型打
    # 「纪律遵从」档，noncompliant 档注入强化规则+derived 契约并启用
    # 打回修复环。VERITAS_PROBE=0 关闭（A/B 需要固定提示词时用）。
    model_probe_enabled: bool = True
    # 答辩演示：强制档位（noncompliant/compliant/standard），空=真实探测。
    # VERITAS_FORCE_TIER=noncompliant 时跳过探测调用，链上记 forced=true。
    force_profile_tier: str = ""

    # 资料预算装箱（字符）：BM25 精排后按预算装入分析师提示词，
    # 装不下的段落全部披露（报告「因预算未进入研判的段落」）。
    # 常态语料（几万字）远低于默认值=零影响；超大输入时保产出。
    material_char_budget: int = 80_000

    # 模型上下文窗口（token）：发送前估算提示词是否超窗并披露（C-9 丙）。
    # 默认 16384＝本机 Ollama qwen3-14b Modelfile 实测；<=0 关闭检查
    # （关时报告须写「未检查」，不许静默当没超）。VERITAS_MODEL_CTX_TOKENS。
    # C-67：仍是向后兼容全局单值；装箱实参优先走 resolve_panel_min_window
    # （探到＞每模声明＞保守常量），本字段作 env 显式覆盖与 ≤0 关检查口。
    model_context_tokens: int = 16384
    # C-67：按模型名的声明窗（config.json model_context_tokens_by_model／
    # env VERITAS_MODEL_CTX_BY_MODEL＝JSON 对象）。键＝完整模型名或裸名。
    model_context_tokens_by_model: dict[str, int] = field(default_factory=dict)
    # C-67：探不到且无声明时的保守常量。不是官方安全尺——〔150〕本机见过
    # Modelfile 未写 num_ctx ⇒ 运行时回退 2048，本值对那种端点仍可能偏大。
    # env VERITAS_MODEL_CTX_FALLBACK 可覆盖。不许写成「安全」。
    model_context_fallback_tokens: int = MODEL_CTX_FALLBACK_DEFAULT
    # from_env 见到 VERITAS_MODEL_CTX_TOKENS 时置 True＝向后兼容「全局当声明」
    # （判据 f：未置此旗＋无每模声明＋探不到 ⇒ 必须落保守常量，不许沿用 16384）。
    model_ctx_tokens_env_set: bool = False
    # 中文字符／token 密度倒数：探针实测 ≈0.69 tok/字 → 1/0.69≈1.45。
    # 来源 scripts/probe_context_window.py（2026-10-16）。VERITAS_ZH_CHARS_PER_TOKEN。
    zh_chars_per_token: float = 1.45
    # 装箱是否以模型窗口为准（C-9 乙／C-19）：开＝有界缩档使整条提示词
    # est ≤ 窗口；关＝VERITAS_PACK_TO_WINDOW=0，走字预算老路。
    pack_to_window: bool = True

    # C-69 树10-①：日期键名统一读点（件①③）。默认 True＝时间标签亮（Boyu 10-28 拍「开＝标签亮就可以、一直开着」）。
    # env VERITAS_SOURCE_TIME_UNIFIED；config.json source_time_unified；关＝0/false/off。
    source_time_unified: bool = True
    # C-69：对撞三档文案（件②）。默认 True＝与上同拍。
    # env VERITAS_LEDGER_TIME_CLASS；config.json ledger_time_class；关＝0/false/off。
    ledger_time_class: bool = True
    # C-70：双轴相关性软闸（取消自动 zero 整源出局）。默认 True＝先试可回滚。
    # env VERITAS_RELEVANCE_SOFT_GATE；config.json relevance_soft_gate。
    relevance_soft_gate: bool = True
    # C-72 树17：要点槽＋主席支撑披露＋并列覆盖黄灯。默认 False＝生产与改前逐字相同。
    # env VERITAS_CLAIM_SLOTS；config.json claim_slots。
    # ⚠ 默认必须 False；整体跑开不开由 Boyu 当场拍，执行方不许自己改默认。
    claim_slots: bool = False
    # C-78：对撞行「组内相对偏差（中位数±k×MAD）」派生标签。
    # 默认 True＝Boyu 10-28 拍「只是打标签就开着」；关＝VERITAS_LEDGER_OUTLIER_TAG=0。
    # 只呈现、不改 find_collisions／采信／置信度／提示词；不许说涨分。
    # env VERITAS_LEDGER_OUTLIER_TAG；config.json ledger_outlier_tag。
    ledger_outlier_tag: bool = True
    # C-80：规范量名填充＋覆盖披露＋分组键优先走 metric_canon。
    # 默认 True＝Boyu 10-28 拍「现在开」；关＝VERITAS_METRIC_CANON=0。
    # 本阶段赋值＝rule:v1（机械身份归一＋垃圾拒填），不是模型、不是别名表。
    # env VERITAS_METRIC_CANON；config.json metric_canon。
    metric_canon: bool = True
    # C-79：演变链只认数值确有变化；同值多时点标「重复报道」＋黄灯。
    # 默认 True＝Boyu 10-28 拍「那就开了」；关＝VERITAS_EVOLVE_VALUE_CHANGE=0。
    # 只呈现／防错，不改采信／置信度；不许说已能识别重复报道／不许说涨分。
    # env VERITAS_EVOLVE_VALUE_CHANGE；config.json evolve_value_change。
    evolve_value_change: bool = True
    # 树16／C-66：续盒（多箱）。首箱三分析师；第 2‥N 箱定向补答（一名分析师）。
    # 默认 True＝Boyu 10-28 拍「先把续盒加进来」；关＝VERITAS_MULTI_BOX=0。
    # ⚠ 墙钟约随盒数上升；不许把 L2_union 说成对单箱 48 的涨分。
    # env VERITAS_MULTI_BOX／VERITAS_MULTI_BOX_MAX；config.json multi_box／multi_box_max。
    multi_box: bool = True
    multi_box_max: int = 3
    # C-99：锚审支撑分 + A0 软保底装箱。默认 True＝Boyu 10-30 拍「默认先开」。
    # 关＝VERITAS_REVIEW_BOOST=0。失败／测试禁真调用 → 回退现产 A0 并披露。
    # ⚠ 增加装箱前 LLM 调用（抽锚＋批审±补召回）；不许说官方涨分。
    # env VERITAS_REVIEW_BOOST／VERITAS_REVIEW_BOOST_B／VERITAS_REVIEW_BOOST_K；
    # config.json review_boost／review_boost_b／review_boost_k。
    review_boost: bool = True
    review_boost_b: float = 7000.0
    review_boost_k: int = 180
    review_boost_refill: int = 40

    # C-108：交卷窄面＋二筛密度（conflict_pairs／树17 focus／k＋rank）。
    # 默认 True＝密度盒序优先装箱；关＝VERITAS_KG_SUBMIT_SURFACE=0 回退旧装满。
    # 硬顶段数另旗 VERITAS_KG_CAP_SEGMENTS（默认关）。
    # 禁 r9／r21／DEFAULT_WEIGHTS／多维 feats 进 pack_material。
    # env VERITAS_KG_SUBMIT_SURFACE；config.json kg_submit_surface。
    kg_submit_surface: bool = True

    # C-109：一筛进池（只出口 pool_ids）。默认 True；关＝VERITAS_KG_STAGE1=0
    # 回退「无池／仅密度桥 BM25」。系数不进 pack。
    # env VERITAS_KG_STAGE1；config.json kg_stage1。
    kg_stage1: bool = True

    # C-111：保底回灌短盒（rehydrate_box）。默认 True；
    # 关＝VERITAS_KG_REHYDRATE_BOX=0 → C-109（无冻结盒／不垫 dens_k）。
    # 系数不进 pack。env／config.json kg_rehydrate_box。
    kg_rehydrate_box: bool = True

    # C-115：冲突三类覆盖＋处置留痕（Q5）。默认 False；
    # 开＝VERITAS_CONFLICT_TRACE=1。三档＝same_window／cross_day／unknown_time；
    # 不改 BM25／不往 pack 塞系数。env／config.json conflict_trace。
    conflict_trace: bool = False

    # 语料收窄阈值：信源数达到该值才走索引选料（默认 50=自动；
    # 0=强制关闭，小案例到不了阈值则整卷研判、不建 .corpus）。
    # 收窄后研判只看见 hydrate 出的小案卷，并披露「库内 N / 本次 M」。
    # 不代表已能把十万份留在磁盘倒排里——建索引仍会读入材料。
    corpus_select_min_sources: int = 50

    # 大库选料纳入上限（C-23）：默认 100；env VERITAS_CORPUS_SELECT_MAX /
    # config.json corpus_select_max_sources。只接受 ≥1 的整数；
    # 0／负数／非整数一律回落 100 并写入 corpus_select_max_disclosures
    # （MAX 上没有「关掉」语义——关掉选料只认 MIN=0）。
    # 不进 silent for-loop（val>0 静默丢弃无披露）；紧邻 min 单独解析。
    corpus_select_max_sources: int = 100
    corpus_select_max_disclosures: list[str] = field(default_factory=list)

    # 摄取目录封顶（C-7）：默认 500 份／深度 3；env
    # VERITAS_INGEST_MAX_FILES／VERITAS_INGEST_MAX_DEPTH；config.json 同名键。
    # 只接受 ≥1 的整数；0／负数／非整数回落默认并写入 ingest_max_disclosures。
    # 不进 silent for-loop（与 C-23 同口径）；禁止把 0 当「无限制」。
    ingest_max_files: int = 500
    ingest_max_depth: int = 3
    ingest_max_disclosures: list[str] = field(default_factory=list)

    # 检索：原问 + 词表同义词始终生效。模型只在最新一句不完整且有上一句时
    # 补成一条独立问句。无上一句不猜主语。VERITAS_QUERY_REWRITE=0 只关这次补全。
    query_rewrite_enabled: bool = True

    # 刀十一：未用关键段二次定向研判。VERITAS_SECOND_PASS=0 关闭。
    second_pass_enabled: bool = True
    second_pass_max_segments: int = 3

    # 链接抓取（默认关——离线演示兜底不受影响）：链接清单文件在
    # 开启时逐条抓取为 web 信源（超时/大小/条数三重上限），逐条披露
    # 成败。VERITAS_FETCH_LINKS=1 / CLI --fetch-links 开启。
    fetch_links_enabled: bool = False

    # 图片转码（默认开，自动降级）：网关有视觉端点时把已披露图片
    # 逐字转写为低可信派生信源（先验 0.3，meta.ocr 标注）；探测不到
    # 视觉端点自动降级回「未转写」披露。VERITAS_OCR=0 关闭。
    ocr_enabled: bool = True

    # PDF 抽取后端（默认 pypdf，U 盘/无开发环境友好）：
    # docling 为可选版式增强（需 requirements-docling，失败回退 pypdf）。
    # VERITAS_PDF_BACKEND=pypdf|docling
    pdf_backend: str = "pypdf"

    # ---- 可选组件（默认关；关闭时不 import 对应模块）----
    embedding_cache_enabled: bool = False
    llm_rate_limit_enabled: bool = False
    llm_rate_limit_rps: float = 1.0
    llm_rate_limit_burst: int = 3

    def validate(self) -> "Settings":
        """启动前确定性校验（脏配置在发起调用前死，而不是烧钱后死）。"""
        if len(set(self.models)) != len(self.models):
            raise ValueError("models 存在重复模型名")
        if not isinstance(self.budget_tokens, int) or self.budget_tokens <= 0:
            raise ValueError(f"budget_tokens 必须为正整数: {self.budget_tokens!r}")
        if not 0.0 < self.budget_throttle_threshold <= 1.0:
            raise ValueError("budget_throttle_threshold 必须落在 (0, 1]")
        if self.retry_backoff_base < 0:
            raise ValueError("retry_backoff_base 必须非负")
        if self.llm_max_retries < 0:
            raise ValueError("llm_max_retries 必须非负")
        if self.llm_temperature is not None and \
                not 0.0 <= self.llm_temperature <= 2.0:
            raise ValueError("llm_temperature 须落在 [0, 2]")
        if self.llm_rate_limit_enabled:
            if self.llm_rate_limit_rps <= 0:
                raise ValueError("llm_rate_limit_rps 必须为正数")
            if self.llm_rate_limit_burst < 1:
                raise ValueError("llm_rate_limit_burst 必须 >= 1")
        # C-23 R-C23-1：max < min 是合法组合——只披露、不回落。
        # min＝「库多大才启动选料」、max＝「选料后纳入几份」，与 select 内
        # 排序零耦合；回落会把用户显式写入的上限静默改掉。
        lo = int(self.corpus_select_min_sources)
        hi = int(self.corpus_select_max_sources)
        if lo > 0 and hi < lo:
            note = (
                f"上限 {hi} 低于触发门槛 {lo}，"
                f"仅当库内信源数 ≥{lo} 时才收窄到 {hi} 份；"
                f"上限按 {hi} 生效"
            )
            if note not in self.corpus_select_max_disclosures:
                self.corpus_select_max_disclosures.append(note)
        return self

    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "Settings":
        """环境变量 + config.json → Settings（环境变量优先级更高）。"""
        s = cls.from_json()
        model_env = os.environ.get("VERITAS_MODELS") or os.environ.get("VERITAS_MODEL")
        if model_env and model_env.strip():
            s.models = [m.strip() for m in model_env.split(",") if m.strip()]
        budget = os.environ.get("VERITAS_BUDGET_TOKENS")
        if budget and budget.strip().isdigit():
            s.budget_tokens = int(budget)
        skills_env = (os.environ.get("VERITAS_SKILLS") or "").strip().lower()
        if skills_env in ("0", "false", "off", "no"):
            s.skills_enabled = False
        probe_env = (os.environ.get("VERITAS_PROBE") or "").strip().lower()
        if probe_env in ("0", "false", "off", "no"):
            s.model_probe_enabled = False
        force_tier = (os.environ.get("VERITAS_FORCE_TIER") or "").strip().lower()
        if force_tier in ("noncompliant", "compliant", "standard"):
            s.force_profile_tier = force_tier
        fetch_env = (os.environ.get("VERITAS_FETCH_LINKS") or "").strip().lower()
        if fetch_env in ("1", "true", "on", "yes"):
            s.fetch_links_enabled = True
        ocr_env = (os.environ.get("VERITAS_OCR") or "").strip().lower()
        if ocr_env in ("0", "false", "off", "no"):
            s.ocr_enabled = False
        pdf_backend = (os.environ.get("VERITAS_PDF_BACKEND") or "").strip().lower()
        if pdf_backend in ("pypdf", "docling"):
            s.pdf_backend = pdf_backend
        select_min = (os.environ.get("VERITAS_CORPUS_SELECT_MIN") or "").strip()
        if select_min.isdigit():
            s.corpus_select_min_sources = int(select_min)
        # C-23：MAX 不照抄 min 的 .isdigit()（那条会接受 "0"）
        select_max = (os.environ.get("VERITAS_CORPUS_SELECT_MAX") or "").strip()
        if select_max:
            val, note = _coerce_corpus_select_max(select_max)
            s.corpus_select_max_sources = val
            if note:
                s.corpus_select_max_disclosures.append(
                    f"env VERITAS_CORPUS_SELECT_MAX: {note}")
        ingest_files = (os.environ.get("VERITAS_INGEST_MAX_FILES") or "").strip()
        if ingest_files:
            val, note = _coerce_positive_int(
                ingest_files, default=_INGEST_MAX_FILES_DEFAULT,
                name="ingest_max_files")
            s.ingest_max_files = val
            if note:
                s.ingest_max_disclosures.append(
                    f"env VERITAS_INGEST_MAX_FILES: {note}")
        ingest_depth = (os.environ.get("VERITAS_INGEST_MAX_DEPTH") or "").strip()
        if ingest_depth:
            val, note = _coerce_positive_int(
                ingest_depth, default=_INGEST_MAX_DEPTH_DEFAULT,
                name="ingest_max_depth")
            s.ingest_max_depth = val
            if note:
                s.ingest_max_disclosures.append(
                    f"env VERITAS_INGEST_MAX_DEPTH: {note}")
        rewrite_env = (os.environ.get("VERITAS_QUERY_REWRITE") or "").strip().lower()
        if rewrite_env in ("0", "false", "off", "no"):
            s.query_rewrite_enabled = False
        elif rewrite_env in ("1", "true", "on", "yes"):
            s.query_rewrite_enabled = True
        second_env = (os.environ.get("VERITAS_SECOND_PASS") or "").strip().lower()
        if second_env in ("0", "false", "off", "no"):
            s.second_pass_enabled = False
        elif second_env in ("1", "true", "on", "yes"):
            s.second_pass_enabled = True
        ctx_env = (os.environ.get("VERITAS_MODEL_CTX_TOKENS") or "").strip()
        if ctx_env.lstrip("-").isdigit():
            s.model_context_tokens = int(ctx_env)
            s.model_ctx_tokens_env_set = True
        by_env = (os.environ.get("VERITAS_MODEL_CTX_BY_MODEL") or "").strip()
        if by_env:
            try:
                raw_by = json.loads(by_env)
            except (json.JSONDecodeError, TypeError):
                raw_by = None
            if isinstance(raw_by, dict):
                parsed: dict[str, int] = {}
                for k, v in raw_by.items():
                    if isinstance(v, bool):
                        continue
                    try:
                        n = int(v)
                    except (TypeError, ValueError):
                        continue
                    if n > 0 and str(k).strip():
                        parsed[str(k).strip()] = n
                if parsed:
                    s.model_context_tokens_by_model = {
                        **s.model_context_tokens_by_model, **parsed}
        fb_env = (os.environ.get("VERITAS_MODEL_CTX_FALLBACK") or "").strip()
        if fb_env.isdigit() and int(fb_env) > 0:
            s.model_context_fallback_tokens = int(fb_env)
        zh_env = (os.environ.get("VERITAS_ZH_CHARS_PER_TOKEN") or "").strip()
        if zh_env:
            try:
                zh_val = float(zh_env)
                if zh_val > 0:
                    s.zh_chars_per_token = zh_val
            except ValueError:
                pass
        pack_env = (os.environ.get("VERITAS_PACK_TO_WINDOW") or "").strip().lower()
        if pack_env in ("0", "false", "off", "no"):
            s.pack_to_window = False
        elif pack_env in ("1", "true", "on", "yes"):
            s.pack_to_window = True
        stu = (os.environ.get("VERITAS_SOURCE_TIME_UNIFIED") or "").strip().lower()
        if stu in ("0", "false", "off", "no"):
            s.source_time_unified = False
        elif stu in ("1", "true", "on", "yes"):
            s.source_time_unified = True
        ltc = (os.environ.get("VERITAS_LEDGER_TIME_CLASS") or "").strip().lower()
        if ltc in ("0", "false", "off", "no"):
            s.ledger_time_class = False
        elif ltc in ("1", "true", "on", "yes"):
            s.ledger_time_class = True
        rsg = (os.environ.get("VERITAS_RELEVANCE_SOFT_GATE") or "").strip().lower()
        if rsg in ("0", "false", "off", "no"):
            s.relevance_soft_gate = False
        elif rsg in ("1", "true", "on", "yes"):
            s.relevance_soft_gate = True
        cs = (os.environ.get("VERITAS_CLAIM_SLOTS") or "").strip().lower()
        if cs in ("0", "false", "off", "no"):
            s.claim_slots = False
        elif cs in ("1", "true", "on", "yes"):
            s.claim_slots = True
        lot = (os.environ.get("VERITAS_LEDGER_OUTLIER_TAG") or "").strip().lower()
        if lot in ("0", "false", "off", "no"):
            s.ledger_outlier_tag = False
        elif lot in ("1", "true", "on", "yes"):
            s.ledger_outlier_tag = True
        mc = (os.environ.get("VERITAS_METRIC_CANON") or "").strip().lower()
        if mc in ("0", "false", "off", "no"):
            s.metric_canon = False
        elif mc in ("1", "true", "on", "yes"):
            s.metric_canon = True
        evc = (os.environ.get("VERITAS_EVOLVE_VALUE_CHANGE") or "").strip().lower()
        if evc in ("0", "false", "off", "no"):
            s.evolve_value_change = False
        elif evc in ("1", "true", "on", "yes"):
            s.evolve_value_change = True
        mb = (os.environ.get("VERITAS_MULTI_BOX") or "").strip().lower()
        if mb in ("0", "false", "off", "no"):
            s.multi_box = False
        elif mb in ("1", "true", "on", "yes"):
            s.multi_box = True
        mbm = (os.environ.get("VERITAS_MULTI_BOX_MAX") or "").strip()
        if mbm.isdigit() and int(mbm) >= 1:
            s.multi_box_max = int(mbm)
        rb = (os.environ.get("VERITAS_REVIEW_BOOST") or "").strip().lower()
        if rb in ("0", "false", "off", "no"):
            s.review_boost = False
        elif rb in ("1", "true", "on", "yes"):
            s.review_boost = True
        rbb = (os.environ.get("VERITAS_REVIEW_BOOST_B") or "").strip()
        if rbb:
            try:
                s.review_boost_b = float(rbb)
            except ValueError:
                pass
        rbk = (os.environ.get("VERITAS_REVIEW_BOOST_K") or "").strip()
        if rbk.isdigit() and int(rbk) >= 1:
            s.review_boost_k = int(rbk)
        rbr = (os.environ.get("VERITAS_REVIEW_BOOST_REFILL") or "").strip()
        if rbr.isdigit() and int(rbr) >= 0:
            s.review_boost_refill = int(rbr)
        kgs = (os.environ.get("VERITAS_KG_SUBMIT_SURFACE") or "").strip().lower()
        if kgs in ("0", "false", "off", "no"):
            s.kg_submit_surface = False
        elif kgs in ("1", "true", "on", "yes"):
            s.kg_submit_surface = True
        s1 = (os.environ.get("VERITAS_KG_STAGE1") or "").strip().lower()
        if s1 in ("0", "false", "off", "no"):
            s.kg_stage1 = False
        elif s1 in ("1", "true", "on", "yes"):
            s.kg_stage1 = True
        rh = (os.environ.get("VERITAS_KG_REHYDRATE_BOX") or "").strip().lower()
        if rh in ("0", "false", "off", "no"):
            s.kg_rehydrate_box = False
        elif rh in ("1", "true", "on", "yes"):
            s.kg_rehydrate_box = True
        ctr = (os.environ.get("VERITAS_CONFLICT_TRACE") or "").strip().lower()
        if ctr in ("0", "false", "off", "no"):
            s.conflict_trace = False
        elif ctr in ("1", "true", "on", "yes"):
            s.conflict_trace = True
        return s.validate()

    @classmethod
    def from_json(cls, path: Path | None = None) -> "Settings":
        """config.json 覆盖代码默认值（未知键忽略，结构错误降级为默认）。"""
        s = cls()
        cfg_path = path or _REPO_ROOT / "config.json"
        if not cfg_path.is_file():
            return s
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return s
        if not isinstance(data, dict):
            return s
        if isinstance(data.get("models"), list) and data["models"]:
            s.models = [str(m) for m in data["models"] if str(m).strip()]
        for key in ("budget_tokens", "max_response_tokens",
                    "llm_timeout_seconds", "llm_max_retries",
                    "llm_wall_clock_seconds", "material_char_budget"):
            val = data.get(key)
            if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                setattr(s, key, val)
        # model_context_tokens 允许 0（关闭检查）；正整数覆盖默认
        ctx = data.get("model_context_tokens")
        if isinstance(ctx, int) and not isinstance(ctx, bool) and ctx >= 0:
            s.model_context_tokens = ctx
        # C-67：按模型名的声明窗表
        by_raw = data.get("model_context_tokens_by_model")
        if isinstance(by_raw, dict):
            parsed_by: dict[str, int] = {}
            for k, v in by_raw.items():
                if isinstance(v, bool):
                    continue
                if isinstance(v, int) and v > 0 and str(k).strip():
                    parsed_by[str(k).strip()] = v
            if parsed_by:
                s.model_context_tokens_by_model = parsed_by
        fb = data.get("model_context_fallback_tokens")
        if isinstance(fb, int) and not isinstance(fb, bool) and fb > 0:
            s.model_context_fallback_tokens = fb
        zh = data.get("zh_chars_per_token")
        if isinstance(zh, (int, float)) and not isinstance(zh, bool) \
                and float(zh) > 0:
            s.zh_chars_per_token = float(zh)
        if "pack_to_window" in data:
            raw_pack = data.get("pack_to_window")
            if isinstance(raw_pack, bool):
                s.pack_to_window = raw_pack
            elif isinstance(raw_pack, (int, str)):
                s.pack_to_window = str(raw_pack).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "source_time_unified" in data:
            raw_stu = data.get("source_time_unified")
            if isinstance(raw_stu, bool):
                s.source_time_unified = raw_stu
            elif isinstance(raw_stu, (int, str)):
                s.source_time_unified = str(raw_stu).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "ledger_time_class" in data:
            raw_ltc = data.get("ledger_time_class")
            if isinstance(raw_ltc, bool):
                s.ledger_time_class = raw_ltc
            elif isinstance(raw_ltc, (int, str)):
                s.ledger_time_class = str(raw_ltc).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "relevance_soft_gate" in data:
            raw_rsg = data.get("relevance_soft_gate")
            if isinstance(raw_rsg, bool):
                s.relevance_soft_gate = raw_rsg
            elif isinstance(raw_rsg, (int, str)):
                s.relevance_soft_gate = str(raw_rsg).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "claim_slots" in data:
            raw_cs = data.get("claim_slots")
            if isinstance(raw_cs, bool):
                s.claim_slots = raw_cs
            elif isinstance(raw_cs, (int, str)):
                s.claim_slots = str(raw_cs).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "ledger_outlier_tag" in data:
            raw_lot = data.get("ledger_outlier_tag")
            if isinstance(raw_lot, bool):
                s.ledger_outlier_tag = raw_lot
            elif isinstance(raw_lot, (int, str)):
                s.ledger_outlier_tag = str(raw_lot).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "metric_canon" in data:
            raw_mc = data.get("metric_canon")
            if isinstance(raw_mc, bool):
                s.metric_canon = raw_mc
            elif isinstance(raw_mc, (int, str)):
                s.metric_canon = str(raw_mc).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "evolve_value_change" in data:
            raw_evc = data.get("evolve_value_change")
            if isinstance(raw_evc, bool):
                s.evolve_value_change = raw_evc
            elif isinstance(raw_evc, (int, str)):
                s.evolve_value_change = str(raw_evc).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "multi_box" in data:
            raw_mb = data.get("multi_box")
            if isinstance(raw_mb, bool):
                s.multi_box = raw_mb
            elif isinstance(raw_mb, (int, str)):
                s.multi_box = str(raw_mb).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "multi_box_max" in data:
            raw_mbm = data.get("multi_box_max")
            if isinstance(raw_mbm, int) and not isinstance(raw_mbm, bool) \
                    and raw_mbm >= 1:
                s.multi_box_max = raw_mbm
        if "review_boost" in data:
            raw_rb = data.get("review_boost")
            if isinstance(raw_rb, bool):
                s.review_boost = raw_rb
            elif isinstance(raw_rb, (int, str)):
                s.review_boost = str(raw_rb).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "review_boost_b" in data:
            raw_rbb = data.get("review_boost_b")
            if isinstance(raw_rbb, (int, float)) and not isinstance(raw_rbb, bool):
                s.review_boost_b = float(raw_rbb)
        if "review_boost_k" in data:
            raw_rbk = data.get("review_boost_k")
            if isinstance(raw_rbk, int) and not isinstance(raw_rbk, bool) \
                    and raw_rbk >= 1:
                s.review_boost_k = raw_rbk
        if "review_boost_refill" in data:
            raw_rbr = data.get("review_boost_refill")
            if isinstance(raw_rbr, int) and not isinstance(raw_rbr, bool) \
                    and raw_rbr >= 0:
                s.review_boost_refill = raw_rbr
        if "kg_submit_surface" in data:
            raw_kgs = data.get("kg_submit_surface")
            if isinstance(raw_kgs, bool):
                s.kg_submit_surface = raw_kgs
            elif isinstance(raw_kgs, (int, str)):
                s.kg_submit_surface = str(raw_kgs).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "kg_stage1" in data:
            raw_s1 = data.get("kg_stage1")
            if isinstance(raw_s1, bool):
                s.kg_stage1 = raw_s1
            elif isinstance(raw_s1, (int, str)):
                s.kg_stage1 = str(raw_s1).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "kg_rehydrate_box" in data:
            raw_rh = data.get("kg_rehydrate_box")
            if isinstance(raw_rh, bool):
                s.kg_rehydrate_box = raw_rh
            elif isinstance(raw_rh, (int, str)):
                s.kg_rehydrate_box = str(raw_rh).strip().lower() not in (
                    "0", "false", "off", "no", "")
        if "conflict_trace" in data:
            raw_ctr = data.get("conflict_trace")
            if isinstance(raw_ctr, bool):
                s.conflict_trace = raw_ctr
            elif isinstance(raw_ctr, (int, str)):
                s.conflict_trace = str(raw_ctr).strip().lower() not in (
                    "0", "false", "off", "no", "")
        select_min = data.get("corpus_select_min_sources")
        if isinstance(select_min, int) and not isinstance(select_min, bool) \
                and select_min >= 0:
            s.corpus_select_min_sources = select_min
        # C-23：单独解析（不进上方 silent for-loop——非法值须披露不可静默丢）。
        # config.json 只认真正的 int≥1；字符串 "100"／0／负数一律回落＋披露。
        if "corpus_select_max_sources" in data:
            raw = data.get("corpus_select_max_sources")
            if (isinstance(raw, int) and not isinstance(raw, bool)
                    and raw >= 1):
                s.corpus_select_max_sources = raw
            else:
                s.corpus_select_max_sources = _CORPUS_SELECT_MAX_DEFAULT
                s.corpus_select_max_disclosures.append(
                    f"config.json: corpus_select_max_sources={raw!r} "
                    f"非法（须为≥1 的整数），回落 {_CORPUS_SELECT_MAX_DEFAULT}")
        # C-7：摄取封顶单独解析（不进 silent for-loop）
        if "ingest_max_files" in data:
            raw = data.get("ingest_max_files")
            if (isinstance(raw, int) and not isinstance(raw, bool)
                    and raw >= 1):
                s.ingest_max_files = raw
            else:
                s.ingest_max_files = _INGEST_MAX_FILES_DEFAULT
                s.ingest_max_disclosures.append(
                    f"config.json: ingest_max_files={raw!r} "
                    f"非法（须为≥1 的整数），回落 {_INGEST_MAX_FILES_DEFAULT}")
        if "ingest_max_depth" in data:
            raw = data.get("ingest_max_depth")
            if (isinstance(raw, int) and not isinstance(raw, bool)
                    and raw >= 1):
                s.ingest_max_depth = raw
            else:
                s.ingest_max_depth = _INGEST_MAX_DEPTH_DEFAULT
                s.ingest_max_disclosures.append(
                    f"config.json: ingest_max_depth={raw!r} "
                    f"非法（须为≥1 的整数），回落 {_INGEST_MAX_DEPTH_DEFAULT}")
        temp = data.get("llm_temperature")
        if isinstance(temp, (int, float)) and not isinstance(temp, bool) \
                and 0.0 <= float(temp) <= 2.0:
            s.llm_temperature = float(temp)
        pb = str(data.get("pdf_backend") or "").strip().lower()
        if pb in ("pypdf", "docling"):
            s.pdf_backend = pb
        return s
