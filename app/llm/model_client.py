"""LLM 调用统一封装（规格文档第 17 章第一阶段、第 9 章 API 集成）。

职责：
- 统一经 litellm 调用不同供应商模型（第 9 章）；
- 落实第 2 层护栏（11.2）：每次调用携带 max_tokens = max_response_tokens；
- 模型支持时携带 response_format={"type": "json_object"}（15.1 第 4 级），
  不支持则自动降级为普通调用（提示词层约束由 prompt_templates 负责）；
- 返回结构化 LLMResponse（content + input/output token 用量），
  并维护调用累计与调用日志，供总预算闸门（11.0）与审计（第 5 章）使用；
- 密钥缺失在调用前快速失败（确定性校验，总则 D.1）。

litellm 采用懒加载：测试与无需真实调用的环境不依赖其安装；
completion_fn 可注入桩函数（依赖倒置）。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.config import MODEL_ENV_KEYS, Settings
from app.llm.budget import BudgetGuard

# 注入点：调用签名与 litellm.completion / litellm.embedding 一致
CompletionFn = Callable[..., Any]
EmbeddingFn = Callable[..., Any]

# 9 章韧性：瞬态错误特征（超时/限流/连接/过载/5xx）→ 指数退避重试；
# 其余错误（参数/鉴权类）非瞬态 → 立即上抛。匹配异常类名 + 消息文本。
_TRANSIENT_MARKERS: tuple[str, ...] = (
    "timeout", "timed out",
    "connection", "connect error",
    "429", "rate limit", "ratelimit", "too many requests",
    "temporarily", "overloaded", "unavailable",
    "502", "503", "504", "internal server error",
    # bench_v1 round-2 取证：GLM 网关偶发返回 GBK 编码错误页，litellm 侧
    # json 解析响应体抛 UnicodeDecodeError/JSONDecodeError——响应乱码属
    # 网关瞬态故障，重试即可恢复（此前直接上谋杀整个任务）
    "unicodedecodeerror", "jsondecodeerror",
    # factory26 r7b 取证：评审模型偶发返回 message.content 缺失的响应
    # （网关抖动）——换一次尝试即恢复，非瞬态判定会当场谋杀整个任务
    "message.content",
)

# factory26 r7c：空内容扩容重试的生成预算天花板（tokens）。
# 推理模型长推理吃满 max_tokens → finish=length + content 空，
# 翻倍重试需上限防失控（8000 → 16000 → 放弃）。
_EMPTY_CONTENT_MAX_TOKENS_CEILING = 16000
# 彩排 A 取证（2026-09-23，mini 四需求）：624k/880k 预算烧掉 71%，其中
# 「测试」阶段 363k。按 (模型, 输入) 归组后看清空烧的形状：glm-5.3 在
# write_tests 上走了 6 条 8000→16000→24000 阶梯，**全部以 content 仍空收场**
# （约 26.4 万 token = 整跑 42% 买回零字符），最终可用的测试内容由换腿后的
# deepseek-v4-pro 产出；而 deepseek-v4-pro 的翻倍 2/2 真的换回内容
# （14017/14303，均在 16000 档以下）。结论：扩容只对「差一点就够」的模型
# 对路，对吃满预算的推理模型是纯空烧。故每模型只陪一次扩容——扩容仍空即
# 记死，此后直接返回空内容由调用方的换腿链接手；扩容换回内容则返还额度。
_EMPTY_CONTENT_LADDER_BUDGET = 1


def _is_timeout(exc: BaseException) -> bool:
    """超时形态判定（内建 TimeoutError + 各家 SDK 的超时异常类）。

    shape-keep 彩排取证（9/23 整跑夭折）：真实网关超时抛的是
    litellm.Timeout，其 MRO 为 Timeout→APITimeoutError→APIConnectionError
    →OpenAIError→Exception，**不含内建 TimeoutError**（那是 OSError 分支）。
    于是旧判定 isinstance(exc, TimeoutError) 对生产路径上的超时永不命中，
    墙钟快上抛只在自造的 TimeoutError 上生效——同腿照样吃满
    (1+llm_max_retries)×llm_timeout_seconds，3 模型链 4×120s×3≈24 分钟
    空烧后整跑 rc=1、零交付。

    只按**类名**匹配（沿 MRO 找 "timeout"），不看消息文本：429/连接重置
    这类错误的消息里常带 "timeout" 字样，但它们没实打实耗掉一整段等待，
    同腿退避重试仍然划算，不该被拖进换腿快通道。
    """
    if isinstance(exc, TimeoutError):
        return True
    return any("timeout" in c.__name__.lower() for c in type(exc).__mro__)


def _is_response_format_unsupported(exc: BaseException) -> bool:
    """仅当错误像「response_format / json_object 不被支持」才允许 json_mode 降级。

    v54 P1-2：超时/连接类错误禁止整梯重跑（单调用最坏 60-80 分钟）。
    判定：消息含 400 或 bad request，且含 response_format 或 json（大小写不敏感）。
    """
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if _is_timeout(cur):
            return False
        cur = cur.__cause__ or cur.__context__

    text = f"{type(exc).__name__} {exc}".lower()
    # 超时/连接：即便包进 RuntimeError 也禁止降级整梯
    if any(m in text for m in ("timeout", "timed out")):
        return False
    if any(m in text for m in ("connection", "connect error", "connecttimeout")):
        if "response_format" not in text and "json_object" not in text:
            return False
    has_bad_req = ("400" in text) or ("bad request" in text)
    has_rf = (
        "response_format" in text
        or "json_object" in text
        or "json mode" in text
    )
    return has_bad_req and has_rf


def _is_transient(exc: Exception) -> bool:
    """判断异常是否为瞬态（可退避重试）。"""
    if isinstance(exc, TimeoutError):
        return True  # 墙钟防御超时（网关长挂）→ 换一次尝试常可恢复
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def leg_chain(primary: str | None, roster: Any) -> list[str]:
    """尝试用腿序：主腿打头，预设名单按序备胎（去重保序）。

    单模型形态（runner 同模补位）下返回 [primary]——链长即调用上界，
    死网关只烧一次墙钟而不是「重试轮数 × 腿数」。
    """
    chain: list[str] = []
    for model in [primary, *(roster or [])]:
        if model and model not in chain:
            chain.append(model)
    return chain


def _apply_connection_creds(model: str, kwargs: dict[str, Any]) -> bool:
    """v1.1 C1：按模型名查连接注册表,命中则注入 api_key/base_url。

    解析失败一律降级返回 False(走环境变量路径),不阻断主管线;
    返回 True 表示连接凭据已注入(调用方可跳过环境密钥检查)。
    """
    try:
        from app.llm.connections import resolve_credentials
        creds = resolve_credentials(model)
    except Exception:
        return False
    if not creds:
        return False
    kwargs["api_key"] = creds.get("api_key", "")
    if creds.get("base_url"):
        kwargs["base_url"] = creds["base_url"]
    return True


class MissingApiKeyError(RuntimeError):
    """已知供应商的 API 密钥缺失（应在发起调用前抛出）。"""


@dataclass
class LLMResponse:
    """单次 LLM 调用的结构化结果（8.4 之外的内部数据结构）。"""

    model: str
    content: str
    input_tokens: int
    output_tokens: int
    # 11.2：续写上限耗尽仍截断 → 按未完成处理（交调用方决策，不静默丢弃）
    truncated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _default_completion_fn() -> CompletionFn:
    """懒加载 litellm.completion（沙箱/测试环境无需安装）。"""
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover - 环境缺依赖时的明确报错
        raise ImportError(
            "litellm 未安装，无法发起真实 LLM 调用。"
            "请先安装：pip install litellm"
        ) from exc
    litellm.suppress_debug_info = True
    return litellm.completion


def _default_embedding_fn() -> EmbeddingFn:
    """懒加载 litellm.embedding（同 completion 的懒加载模式）。"""
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "litellm 未安装，无法发起 embedding 调用。"
            "请先安装：pip install litellm"
        ) from exc
    litellm.suppress_debug_info = True
    return litellm.embedding


def _get_embedding(response: Any) -> tuple[list[float], int]:
    """从 litellm embedding 响应提取向量与 token 用量。"""
    data = _index(response, "data")
    if not data:
        raise RuntimeError("embedding 响应缺少 data 字段")
    vector = _index(data[0], "embedding")
    if vector is None:
        raise RuntimeError("embedding 响应缺少 embedding 向量")
    usage = _index(response, "usage") or {}
    prompt_tokens = int(_index(usage, "prompt_tokens") or 0)
    return list(vector), prompt_tokens


class ModelClientEmbedder:
    """Embedder 协议适配器（11.3：LoopDetector ← ModelClient.embed）。

    失败安全降级：embed 调用失败时返回空向量（余弦=0 → 不误判
    重复），讨论流程不中断；失败已在 ModelClient 侧记入观测日志。
    """

    def __init__(self, client: "ModelClient", model: str):
        self._client = client
        self._model = model

    def embed(self, text: str) -> list[float]:
        try:
            return self._client.embed(self._model, text)
        except Exception:
            return []


class ModelClient:
    """面向 Agent 的统一模型调用客户端。"""

    def __init__(
        self,
        settings: Settings,
        completion_fn: CompletionFn | None = None,
        budget_guard: BudgetGuard | None = None,
        embedding_fn: EmbeddingFn | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        embedding_cache: Any | None = None,
        rate_limiter: Any | None = None,
    ):
        self.settings = settings
        self._completion_fn = completion_fn
        self._embedding_fn = embedding_fn
        self._sleep = sleep_fn or time.sleep  # 9 章退避（测试可注入记录器）
        # M4-1：embedding 向量缓存（跨任务共享实例，由工厂持有；
        # 命中零 API 调用、零 token；None = 不启用）
        self.embedding_cache = embedding_cache
        # M8-5：全局限流器（工厂持有单实例跨任务共享；None = 不限流）
        self.rate_limiter = rate_limiter
        # 11.0 第 0 层总闸：任务级预算护栏（由 Pipeline 挂接/卸载）。
        # 零散实例兜底（2026-09-20 平台双跑取证：auto_repair 自建 client
        # 整体绕过预算，7.0M/6.2M vs 2M 帽，¥210 学费）——未显式接线时
        # 复用管线登记的活动护栏，堵住无上限失血。
        if budget_guard is None:
            from app.llm.budget import get_active_budget_guard

            budget_guard = get_active_budget_guard()
        self.budget_guard: BudgetGuard | None = budget_guard
        # 11.0 可观测性：每步 token 累计
        self.total_tokens_used: int = 0
        # 彩排 A：空内容扩容的每模型额度台账（已花掉了多少条阶梯）
        self._empty_ladder_spent: dict[str, int] = {}
        # 第 5 章可审计：调用日志（模型、模式、用量）
        self.call_log: list[dict[str, Any]] = []
        # M8-4：任务进度钩子——每次调用结束后回调（entry 同 call_log 条目）；
        # 由 Pipeline 按任务挂接，未挂接零开销
        self.on_call: Callable[[dict[str, Any]], None] | None = None

    # ------------------------------------------------------------------

    def _call_with_wall_clock(self, fn, kwargs: dict[str, Any]) -> Any:
        """网关长挂防御：单次调用限墙钟（llm_wall_clock_seconds，0=关）。

        httpx read timeout 只约束「字节间隙」——网关对长生成滴字续命时
        永不触发，单请求实测可挂 25 分钟以上（P2P 演练取证）。放入
        守护线程 join(deadline)：超时抛 TimeoutError（瞬态 → 既有退避
        重试），被遗弃线程随响应到达自行消散。
        """
        limit = int(self.settings.llm_wall_clock_seconds or 0)
        if limit <= 0:
            return fn(**kwargs)
        import threading

        box: dict[str, Any] = {}

        def _worker() -> None:
            try:
                box["result"] = fn(**kwargs)
            except BaseException as exc:  # 原样转交主线程判定
                box["error"] = exc

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=float(limit))
        if t.is_alive():
            raise TimeoutError(
                f"单次调用超过墙钟上限 {limit}s timed out"
                "（网关长挂防御触发）"
            )
        if "error" in box:
            raise box["error"]
        return box["result"]

    def _call_with_retry(
        self,
        fn: Callable[..., Any],
        kwargs: dict[str, Any],
        model: str,
        error_prefix: str,
        max_retries: int | None = None,
    ) -> Any:
        """调用 LLM 接口（9 章韧性：瞬态错误指数退避重试）。

        - 瞬态错误（超时/429/连接/5xx/过载）重试至多 llm_max_retries 次，
          退避 sleep = retry_backoff_base * 2**attempt；
        - 非瞬态错误（参数/鉴权类）立即上抛（重试无意义，徒耗预算）；
        - 重试耗尽抛 RuntimeError（含尝试次数，可观测）。
        - max_retries 可覆盖（json_mode 降级梯用 max_retries//2）。
        """
        if max_retries is None:
            max_retries = self.settings.llm_max_retries
        for attempt in range(max_retries + 1):
            # M8-5：每次尝试（含 429 重试与续写）先取令牌——排队控节奏，
            # 与 9 章退避重试互补；未启用限流时零开销直通
            if self.rate_limiter is not None:
                from app.llm.rate_limiter import provider_of

                self.rate_limiter.acquire(provider_of(model))
            try:
                return self._call_with_wall_clock(fn, kwargs)
            except Exception as exc:
                # keep7v 取证：墙钟超时已实打实耗掉 limit 秒，同腿重试
                # 只会再耗一次（网关挂连接 ×(1+重试)×20min 可烧穿整条
                # 链）。换腿才是正确重试——立即上抛交给上层模型备胎链。
                # shape-keep 彩排修正：判定口径从「仅内建 TimeoutError」
                # 放宽到各家 SDK 的超时类，真实网关超时同走此快通道。
                if _is_timeout(exc):
                    raise RuntimeError(
                        f"{error_prefix}（{model}）: {exc}") from exc
                if not _is_transient(exc):
                    raise RuntimeError(
                        f"{error_prefix}（{model}）: {exc}"
                    ) from exc
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"{error_prefix}（{model}，已重试 {max_retries} 次）: {exc}"
                    ) from exc
                self._sleep(self.settings.retry_backoff_base * (2 ** attempt))
        raise AssertionError("unreachable")  # pragma: no cover

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool = False,
    ) -> LLMResponse:
        """发起一次对话补全。

        Args:
            model: 模型名称（须已在 Settings.models 登记）。
            messages: OpenAI 风格消息列表。
            json_mode: 请求结构化 JSON 输出（15.1 第 4 级）。

        Raises:
            ValueError: 模型未登记。
            MissingApiKeyError: 已知供应商密钥缺失。
            RuntimeError: 调用失败（含降级重试后仍失败）。
        """
        if model not in self.settings.models:
            raise ValueError(
                f"模型「{model}」未在配置中登记，可用模型: {self.settings.models}"
            )
        # 11.0：超预算 → 立即中止该任务（每次调用前拦截）
        if self.budget_guard is not None:
            self.budget_guard.ensure_allowed()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": self.settings.max_response_tokens,  # 第 2 层护栏
            "timeout": self.settings.llm_timeout_seconds,     # 9 章：单次调用超时
        }
        if self.settings.llm_temperature is not None:
            kwargs["temperature"] = self.settings.llm_temperature
        # v1.1 C1：连接注册表命中 → 注入 api_key/base_url(热加载);
        # 未命中回落环境变量密钥检查(行为与 v1.0 一致)
        if not _apply_connection_creds(model, kwargs):
            self._check_api_key(model)
        use_json = json_mode and self.settings.strict_json_response
        if use_json:
            kwargs["response_format"] = {"type": "json_object"}

        completion = self._completion_fn or _default_completion_fn()

        # factory26 r7b：响应构建（含 content 校验）纳入重试与墙钟范围——
        # 网关偶发返回 message.content 缺失的响应，构建在重试外会让该
        # 抖动绕过瞬态判定当场终止任务。raw_holder 暴露末次成功裸响应
        # （截断续写需读 finish_reason）。
        raw_holder: list[Any] = []

        def _call_and_build(**kw):
            response = completion(**kw)
            raw_holder.append(response)
            try:
                # 看门狗进展源（2026-09-19 本地首跑取证）：验收期 LLM 修复
                # 不产生 Pipeline 事件，5 小时活跃工作被误判楔死强杀——
                # 每次成功的 LLM 响应都算进展，最大盲区压到一个墙钟窗口。
                from app.pipeline import touch_progress

                touch_progress()
            except Exception:
                pass
            return self._build_response(
                model, response, json_mode=json_mode, messages=kw["messages"]
            )

        try:
            result = self._call_with_retry(
                _call_and_build, kwargs, model, "LLM 调用失败"
            )
        except RuntimeError as exc:
            # v54 P1-2：json_mode 降级只允许 response_format 不支持类错误；
            # 超时/连接禁止整梯重跑；降级梯重试次数减半（至少 1）。
            if use_json and _is_response_format_unsupported(exc):
                kwargs.pop("response_format", None)
                half = max(1, self.settings.llm_max_retries // 2)
                result = self._call_with_retry(
                    _call_and_build, kwargs, model, "LLM 调用失败",
                    max_retries=half,
                )
            else:
                raise
        response = raw_holder[-1] if raw_holder else None

        # factory26 r7c 取证：推理模型（glm-5.2/5.3）长推理可吃光 max_tokens，
        # 返回 finish=length + content 空（completion_tokens 全花在推理上）
        # ——空内容走「续写」是死路，翻倍生成预算重试才对路。
        # 彩排 A 再取证：翻倍只对部分模型对路，且每模型最多值一次（额度见
        # _EMPTY_CONTENT_LADDER_BUDGET），故阶梯只留一档、只陪一次；空到底就
        # 照旧返回空内容——调用方的换腿链本就把空响应当腿故障，钱该花在那。
        if _content_empty(result) and _get_finish_reason(response) == "length":
            spent = self._empty_ladder_spent.get(model, 0)
            new_cap = min(
                int(kwargs.get("max_tokens") or 0) * 2,
                _EMPTY_CONTENT_MAX_TOKENS_CEILING,
            )
            if (
                spent < _EMPTY_CONTENT_LADDER_BUDGET
                and new_cap > int(kwargs.get("max_tokens") or 0)
                and self.settings.max_output_continuations
            ):
                self._empty_ladder_spent[model] = spent + 1
                kwargs["max_tokens"] = new_cap
                result = self._call_with_retry(
                    _call_and_build, kwargs, model, "LLM 调用失败（空内容扩容重试）"
                )
                response = raw_holder[-1]
                if not _content_empty(result):
                    self._empty_ladder_spent[model] = spent  # 扩容换回了内容：返还额度

        # 11.2：截断（finish_reason=length）分块续写，不静默丢弃
        # 彩排 A 同批修：content 为空时这条循环同样进得去——往空内容上接
        # 「继续，从中断处接着输出剩余部分」是凭空续写，钱花了没有落点
        # （扩容阶梯失败后 finish 仍是 length，正好走进这条死路）。
        continuations = 0
        while (
            not _content_empty(result)
            and _get_finish_reason(response) == "length"
            and continuations < self.settings.max_output_continuations
        ):
            continuations += 1
            # 上下文接续：原对话 + 已生成部分（assistant）+ 继续指令
            kwargs["messages"] = (
                messages
                + [{"role": "assistant", "content": result.content}]
                + [{"role": "user", "content": "继续，从中断处接着输出剩余部分，不要重复已有内容。"}]
            )
            try:
                continuation = self._call_with_retry(
                    _call_and_build, kwargs, model, "LLM 续写调用失败"
                )
                response = raw_holder[-1]
            except RuntimeError:
                raise
            # bench_v1 试跑取证（2026-09-04）：句中截断（原文不以换行结尾）时，
            # GLM 续写响应以真实换行开头而非接着输出原行——裸拼接在拼接点产生
            # 未闭合字符串（unterminated string literal），且修复轮重新生成再次
            # 截断续写，5 轮不收敛。故句中截断剥掉续写头部的换行（截断位置是
            # 行内坐标，续写须原位接上）；原文本就结束在行尾则保持续写原样。
            head = continuation.content
            if result.content and not result.content.endswith("\n"):
                head = head.lstrip("\r\n")
            # 合并：内容拼接、用量累计
            result = LLMResponse(
                model=model,
                content=result.content + head,
                input_tokens=result.input_tokens + continuation.input_tokens,
                output_tokens=result.output_tokens + continuation.output_tokens,
                truncated=continuation.truncated,
            )
        if _get_finish_reason(response) == "length":
            result.truncated = True
        return result

    def embed(self, model: str, text: str) -> list[float]:
        """发起一次 embedding 调用（11.3 第二道，经 model_client 统一封装）。

        token 用量计入总预算闸门（11.0）与审计日志（第 5 章）。
        Raises:
            RuntimeError: 调用失败或响应结构非法。
        """
        # 11.0：embedding 调用同样受总预算闸门约束
        if self.budget_guard is not None:
            self.budget_guard.ensure_allowed()

        # M4-1：缓存命中直接返回（零 API 调用、零 token；审计留痕 + M4-4 节省量）
        if self.embedding_cache is not None:
            cached, saved_tokens = self.embedding_cache.lookup(model, text)
            if cached is not None:
                entry = {
                    "model": model,
                    "kind": "embedding",
                    "json_mode": False,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "content_chars": len(text),
                    "system_hint": "",
                    "cache_hit": True,
                    "saved_tokens": saved_tokens,
                }
                self.call_log.append(entry)
                self._notify_on_call(entry)
                return cached

        embedding = self._embedding_fn or _default_embedding_fn()
        embed_kwargs: dict[str, Any] = {
            "model": model,
            "input": [text],
            "timeout": self.settings.llm_timeout_seconds,
        }
        _apply_connection_creds(model, embed_kwargs)
        response = self._call_with_retry(
            embedding,
            embed_kwargs,
            model,
            "embedding 调用失败",
        )

        vector, prompt_tokens = _get_embedding(response)
        # M4-1：写入缓存（同模型同文本下次命中；M4-4：记录原调用 token 供节省量统计）
        if self.embedding_cache is not None:
            self.embedding_cache.put(model, text, vector, tokens=prompt_tokens)
        # 11.0 累计与第 5 章审计日志（kind=embedding）
        self.total_tokens_used += prompt_tokens
        if self.budget_guard is not None:
            self.budget_guard.record(prompt_tokens)
        entry = {
            "model": model,
            "kind": "embedding",
            "json_mode": False,
            "input_tokens": prompt_tokens,
            "output_tokens": 0,
            "content_chars": len(text),
            "system_hint": "",
        }
        self.call_log.append(entry)
        self._notify_on_call(entry)
        return vector

    # ------------------------------------------------------------------

    def _check_api_key(self, model: str) -> None:
        """已知供应商密钥缺失时快速失败（第 5 章：密钥仅从环境变量读取）。"""
        for prefix, env_name in MODEL_ENV_KEYS:
            if model.startswith(prefix):
                if not os.environ.get(env_name):
                    raise MissingApiKeyError(
                        f"模型「{model}」需要环境变量 {env_name}，"
                        "请在 .env 或环境中配置后再调用"
                    )
                return  # 命中已知供应商即结束

    def _build_response(
        self,
        model: str,
        response: Any,
        json_mode: bool,
        messages: list[dict[str, str]] | None = None,
    ) -> LLMResponse:
        """从 litellm 响应提取内容与 token 用量（兼容 dict 与对象两种访问方式）。"""
        content = _get_content(response)
        input_tokens, output_tokens = _get_usage(response)

        result = LLMResponse(
            model=model,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        # 11.0 累计与第 5 章审计日志
        self.total_tokens_used += result.total_tokens
        if self.budget_guard is not None:
            self.budget_guard.record(result.total_tokens)
        entry = {
            "model": model,
            "json_mode": json_mode,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "content_chars": len(content),
            "system_hint": (messages[0]["content"] if messages else ""),  # 8.5 环节归属
        }
        self.call_log.append(entry)
        self._notify_on_call(entry)
        return result

    def _notify_on_call(self, entry: dict[str, Any]) -> None:
        """M8-4：调用后进度钩子（回调失败不影响调用本身）。"""
        if self.on_call is None:
            return
        try:
            self.on_call(entry)
        except Exception:
            pass


def _get_content(response: Any) -> str:
    choices = _index(response, "choices")
    if not choices:
        raise RuntimeError("LLM 响应缺少 choices 字段")
    message = _index(choices[0], "message")
    content = _index(message, "content")
    if content is None:
        # factory26 r7c-2 取证：glm-5.2 推理吃满 max_tokens 返回
        # content=null（而非空串）——此时抛错会在扩容判断之前炸掉，
        # 带着同一 max_tokens 重试必然确定性复现。finish=length 时按
        # 空串放行，交给空内容扩容重试通道（翻倍至天花板）。
        if _get_finish_reason(response) == "length":
            return ""
        raise RuntimeError("LLM 响应缺少 message.content 字段")
    return str(content)


def _get_usage(response: Any) -> tuple[int, int]:
    usage = _index(response, "usage")
    if usage is None:
        return 0, 0
    prompt = _index(usage, "prompt_tokens")
    completion = _index(usage, "completion_tokens")
    return int(prompt or 0), int(completion or 0)


def _get_finish_reason(response: Any) -> str | None:
    """提取 finish_reason（11.2 截断判定；缺失视为正常结束）。"""
    choices = _index(response, "choices")
    if not choices:
        return None
    reason = _index(choices[0], "finish_reason")
    return str(reason) if reason else None


def _content_empty(result: "LLMResponse") -> bool:
    """响应内容是否等于没有（空串/纯空白）。

    彩排 A 取证：推理模型吃满 max_tokens 时 content 可为 ""（或一串空白），
    HTTP 200、非异常——既有换腿链只看异常，于是把这种「成功但零产出」当
    成功返回，调用方再整节点重来。这里给出统一的判定口径。
    """
    return not (getattr(result, "content", "") or "").strip()


def _index(obj: Any, key: str) -> Any:
    """兼容 dict 访问与属性访问（litellm ModelResponse 两者皆可）。"""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


class ModelClientFactory:
    """任务级 ModelClient 工厂（M8-1）。

    budget_guard / call_log / total_tokens_used 是任务级状态：挂在
    单例上时多任务并发即预算串数、调用日志混写（M8 现状问题）。
    工厂保证每任务 create() 出独立实例，预算闸门与审计日志天然隔离。

    completion_fn / embedding_fn / sleep_fn 为注入点（测试桩），
    透传给每个实例；settings 为共享只读配置（无任务级状态）。
    """

    def __init__(
        self,
        settings: Settings | None = None,
        completion_fn: CompletionFn | None = None,
        embedding_fn: EmbeddingFn | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        rate_limiter: Any | None = None,
    ):
        self._settings = settings or Settings()
        self._completion_fn = completion_fn
        self._embedding_fn = embedding_fn
        self._sleep_fn = sleep_fn
        # M4-1：跨任务共享的 embedding 缓存（工厂持有单实例，
        # 每个任务级客户端都接入——跨任务复用正是缓存的价值）
        self._embedding_cache: Any | None = None
        if self._settings.embedding_cache_enabled:
            from app.llm.embedding_cache import EmbeddingCache

            self._embedding_cache = EmbeddingCache(
                self._settings.embedding_cache_path,
                ttl_days=self._settings.embedding_cache_ttl_days,
            )
        # M8-5：全局限流器——工厂持有单实例，所有任务级客户端共享
        # （限流是进程级约束：每任务一个限流器等于没限）。外部注入优先，
        # 未注入且配置开启时按配置构建。
        if rate_limiter is not None:
            self._rate_limiter: Any | None = rate_limiter
        elif self._settings.llm_rate_limit_enabled:
            from app.llm.rate_limiter import RateLimiter

            self._rate_limiter = RateLimiter(
                self._settings.llm_rate_limit_rps,
                self._settings.llm_rate_limit_burst,
                sleep_fn=sleep_fn,
            )
        else:
            self._rate_limiter = None

    def create(self) -> ModelClient:
        """创建一个任务级独立 ModelClient 实例（共享只读配置与缓存）。"""
        return ModelClient(
            self._settings,
            completion_fn=self._completion_fn,
            embedding_fn=self._embedding_fn,
            sleep_fn=self._sleep_fn,
            embedding_cache=self._embedding_cache,
            rate_limiter=self._rate_limiter,
        )
