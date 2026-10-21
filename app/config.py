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


def _coerce_corpus_select_max(raw) -> tuple[int, str | None]:
    """解析纳入上限：合法 ≥1 的整数 → (n, None)；否则回落 100＋披露句。

    MAX 没有「关掉」语义（MIN=0 才有）；不得把 0 当无限制。
    """
    default = _CORPUS_SELECT_MAX_DEFAULT
    if isinstance(raw, bool):
        return default, (
            f"corpus_select_max_sources={raw!r} 非法（布尔），回落 {default}")
    if isinstance(raw, int):
        if raw >= 1:
            return raw, None
        return default, (
            f"corpus_select_max_sources={raw!r} 非法（须≥1），回落 {default}")
    if isinstance(raw, str):
        text = raw.strip()
        try:
            n = int(text, 10)
        except ValueError:
            return default, (
                f"corpus_select_max_sources={raw!r} 非整数，回落 {default}")
        if n >= 1:
            return n, None
        return default, (
            f"corpus_select_max_sources={raw!r} 非法（须≥1），回落 {default}")
    return default, (
        f"corpus_select_max_sources={raw!r} 非法，回落 {default}")


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
    model_context_tokens: int = 16384
    # 中文字符／token 密度倒数：探针实测 ≈0.69 tok/字 → 1/0.69≈1.45。
    # 来源 scripts/probe_context_window.py（2026-10-16）。VERITAS_ZH_CHARS_PER_TOKEN。
    zh_chars_per_token: float = 1.45
    # 装箱是否以模型窗口为准（C-9 乙／C-19）：开＝有界缩档使整条提示词
    # est ≤ 窗口；关＝VERITAS_PACK_TO_WINDOW=0，走字预算老路。
    pack_to_window: bool = True

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
        temp = data.get("llm_temperature")
        if isinstance(temp, (int, float)) and not isinstance(temp, bool) \
                and 0.0 <= float(temp) <= 2.0:
            s.llm_temperature = float(temp)
        pb = str(data.get("pdf_backend") or "").strip().lower()
        if pb in ("pypdf", "docling"):
            s.pdf_backend = pb
        return s
