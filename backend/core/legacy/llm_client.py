"""
LLM Client - 大语言模型客户端
支持 OpenAI-compatible API 协议，兼容多种提供商
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.core.errors import LLMError, LLMErrorType

logger = logging.getLogger(__name__)

# 预编译：提取 LLM 输出中的 <think>...</think> 推理块。
# 部分 provider（如 DeepSeek）把推理内容用此标签包裹在 content 字段中。
THINK_TAG_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)

# ===== L3 请求层重试退避（对标增强第二轮批次 B）=====
#: 默认最大尝试次数（首次 + 2 次重试）；env ``SAGE_LLM_RETRY_MAX_ATTEMPTS`` 覆盖
_LLM_RETRY_MAX_ATTEMPTS = 3
#: 指数退避基数秒数；env ``SAGE_LLM_RETRY_BASE_DELAY_S`` 覆盖
_LLM_RETRY_BASE_DELAY_S = 1.0
#: 单次退避上限
_LLM_RETRY_MAX_DELAY_S = 15.0
#: 可重试的错误类型：限流 / 服务端错误 / 超时 / 网络不可达
_RETRYABLE_ERROR_TYPES = frozenset(
    {
        LLMErrorType.RATE_LIMITED,
        LLMErrorType.SERVER_ERROR,
        LLMErrorType.TIMEOUT,
        LLMErrorType.NETWORK,
    }
)


def _retry_settings() -> Tuple[int, float]:
    """读重试配置：env 覆盖 > 默认。任何解析失败回退默认，永不抛错。"""
    max_attempts = _LLM_RETRY_MAX_ATTEMPTS
    base_delay = _LLM_RETRY_BASE_DELAY_S
    raw_attempts = os.environ.get("SAGE_LLM_RETRY_MAX_ATTEMPTS", "").strip()
    if raw_attempts:
        try:
            value = int(raw_attempts)
            if value >= 1:
                max_attempts = value
        except ValueError:
            logger.warning("env SAGE_LLM_RETRY_MAX_ATTEMPTS=%r 非法,回退默认", raw_attempts)
    raw_delay = os.environ.get("SAGE_LLM_RETRY_BASE_DELAY_S", "").strip()
    if raw_delay:
        try:
            value = float(raw_delay)
            if value >= 0:
                base_delay = value
        except ValueError:
            logger.warning("env SAGE_LLM_RETRY_BASE_DELAY_S=%r 非法,回退默认", raw_delay)
    return max_attempts, base_delay


def _retry_backoff_seconds(err: LLMError, attempt: int, base_delay: float) -> float:
    """第 attempt 次失败后的退避秒数：retry-after 优先,否则指数退避封顶。"""
    if err.retry_after:
        return min(float(err.retry_after), _LLM_RETRY_MAX_DELAY_S)
    return min(base_delay * (2 ** (attempt - 1)), _LLM_RETRY_MAX_DELAY_S)


def extract_cached_tokens(usage: Dict[str, Any]) -> int:
    """多 provider 缓存命中字段归一化（L4 缓存感知记账）。

    全链路走 OpenAI 兼容线格式,缓存命中字段各家不同:
    - OpenAI 系: ``usage.prompt_tokens_details.cached_tokens``
    - DeepSeek: ``usage.prompt_cache_hit_tokens``
    - Anthropic 原生形态（经兼容网关透传时）: ``usage.cache_read_input_tokens``

    注意: prompt_tokens 已**包含**命中部分（OpenAI/DeepSeek 口径）,
    调用方拆账时用 prompt - cached 计全价输入。
    """
    if not isinstance(usage, dict):
        return 0
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        try:
            return int(details.get("cached_tokens") or 0)
        except (TypeError, ValueError):
            return 0
    for key in ("prompt_cache_hit_tokens", "cache_read_input_tokens"):
        value = usage.get(key)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


@dataclass
class LLMMessage:
    """单条对话消息"""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


@dataclass
class LLMToolCall:
    """工具调用"""

    id: str
    name: str
    arguments: str  # JSON string


@dataclass
class LLMChoice:
    """单条回复选项"""

    message: LLMMessage
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[LLMToolCall]] = None


@dataclass
class LLMResponse:
    """LLM 回复"""

    content: str = ""
    reasoning_content: Optional[str] = (
        None  # LLM 思考/推理过程（Claude extended thinking, o1 reasoning 等）
    )
    model: str = ""
    finish_reason: Optional[str] = None
    tool_calls: List[LLMToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    # M6 生态扩展: OpenAI 响应中的原始 usage 块 (prompt_tokens /
    # completion_tokens / total_tokens)。响应无 usage 字段时保持 None —
    # 既有调用方不受影响。
    usage: Optional[Dict[str, int]] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass
class LLMConfig:
    """LLM 连接配置"""
    provider: str = "openai"  # openai, claude, gemini, deepseek, ollama, custom
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 60
    # 推理参数（覆盖 commit #38 之前的硬编码 "custom" provider 路径，
    # 让用户在前端选的真实 provider 透传到 LLMClient，并启用 thinking 输出）
    reasoning_effort: Optional[str] = None  # OpenAI o1/o3/5: "low" | "medium" | "high"
    thinking_budget: Optional[int] = None  # Gemini 2.5: 思考 token 上限,0 关闭,-1 动态
    extra_headers: Dict[str, str] = field(default_factory=dict)
    # === v2: LLM proxy 路由 ===
    # 为统一「测试连接」与「chat」两条路径的 baseUrl 解析规则（避免 baseUrl 是否
    # 包含 `/v1` 后缀的二义性），所有 LLM HTTP 调用现在走本机 FastAPI 上的
    # `/api/v1/llm/*` 反向代理。`base_url` 仍然是用户填的真实上游 URL（用于
    # 构造 `X-LLM-Provider-Url` header），`backend_url` 是本机后端地址（默认
    # 从环境变量 `BACKEND_URL` 读取，否则 `http://127.0.0.1:8765`）。
    # 当 `use_proxy=False` 时，绕过 proxy 直连上游 — 仅用于单测（respx mock
    # 直接拦截上游调用，简化 fixture）。
    backend_url: str = field(
        default_factory=lambda: os.environ.get("BACKEND_URL", "http://127.0.0.1:8765")
    )
    use_proxy: bool = True


class StreamToolCallAggregator:
    """把流式响应中的 tool_calls 增量按 index 聚合成完整调用（L2 真流式）。

    OpenAI 兼容流式协议里,一次工具调用拆成多个 delta:
    ``{"index": 0, "id": "call_x", "function": {"name": "f", "arguments": "{\"a\"}}``
    ``{"index": 0, "function": {"arguments": ": 1}"}}``
    arguments 字符串逐段拼接,id/name 只在首块出现。部分上游省略 index ——
    按 0 处理（单调用场景唯一合理默认）。
    """

    def __init__(self) -> None:
        # index -> {"id": str, "name": str, "arguments": str}
        self._partials: Dict[int, Dict[str, str]] = {}

    def feed(self, delta_tool_calls: Any) -> None:
        """消费一个 chunk 的 ``delta.tool_calls``（list 或 None），非法形状静默跳过。"""
        if not isinstance(delta_tool_calls, list):
            return
        for delta in delta_tool_calls:
            if not isinstance(delta, dict):
                continue
            index = delta.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                index = 0
            slot = self._partials.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if isinstance(delta.get("id"), str) and delta["id"] and not slot["id"]:
                slot["id"] = delta["id"]
            function = delta.get("function")
            if not isinstance(function, dict):
                continue
            if isinstance(function.get("name"), str) and function["name"] and not slot["name"]:
                slot["name"] = function["name"]
            arguments_piece = function.get("arguments")
            if isinstance(arguments_piece, str):
                slot["arguments"] += arguments_piece

    def build(self) -> List[LLMToolCall]:
        """按 index 升序输出聚合结果；name 为空的残缺调用丢弃。"""
        calls: List[LLMToolCall] = []
        for index in sorted(self._partials):
            slot = self._partials[index]
            if not slot["name"]:
                continue
            calls.append(
                LLMToolCall(
                    id=slot["id"] or f"call_{index}",
                    name=slot["name"],
                    arguments=slot["arguments"] or "{}",
                )
            )
        return calls


class LLMClient:
    """
    LLM 客户端，支持 OpenAI-compatible API

    用法:
        config = LLMConfig(
            provider="openai",
            api_key="sk-xxx",
            model="gpt-4"
        )
        client = LLMClient(config)
        response = await client.chat(messages)
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
        # L2 真流式 (2026-09-06): 流式 + tools 首块前失败过的 provider 标记
        # （部分上游不支持 stream+tools 或 stream_options）。置位后
        # run_loop 直接走非流式,避免每次迭代都白白多打一个失败请求。
        self.stream_unsupported = False
        # L8 (批次 C): 用量归因的会话维度——run_loop 按需注入,缺省 None
        # (usage_events 落库为 unattributed 行)。
        self.session_id: Optional[str] = None

    def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端

        v2: 默认走本机 LLM proxy (`<backend_url>/api/v1/llm`),把真实上游 URL
        通过 `X-LLM-Provider-Url` header 注入,与前端"测试连接"走同一通路。
        单测场景下 `LLMConfig(use_proxy=False)` 切回直连上游,保持 fixture 简洁。
        """
        if self._client is None or self._client.is_closed:
            headers: Dict[str, str] = {"Content-Type": "application/json"}

            if self.config.use_proxy:
                backend = (self.config.backend_url or "http://127.0.0.1:8765").rstrip("/")
                client_base_url = f"{backend}/api/v1/llm"
                headers["X-LLM-Provider-Url"] = self.config.base_url
            else:
                client_base_url = self.config.base_url

            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            headers.update(self.config.extra_headers)

            # The proxy's process-local capability is distinct from the
            # provider API key. Read only the explicitly injected token: the
            # local-auth helper's generated fallback is not available to an
            # independently authenticated HTTP request. Omitting this header
            # when the token is absent preserves the proxy's fail-closed 401.
            if self.config.use_proxy:
                local_auth_token = os.environ.get("SAGE_LOCAL_AUTH_TOKEN")
                if local_auth_token:
                    headers["X-Sage-Local-Authorization"] = f"Bearer {local_auth_token}"

            self._client = httpx.AsyncClient(
                base_url=client_base_url,
                headers=headers,
                timeout=httpx.Timeout(self.config.timeout),
            )
        return self._client

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def _raise_classified_error(exc: Exception) -> None:
        """把底层异常映射为分类的 ``LLMError`` 并抛出。

        ``chat`` 与 ``chat_stream`` 共享同一套分类规则
        （见 ``backend.core.errors.LLMErrorType``）:

        - ``httpx.TimeoutException``    → TIMEOUT
        - ``httpx.ConnectError``        → NETWORK
        - ``httpx.HTTPStatusError``     → AUTH_FAILED (401) / RATE_LIMITED (429)
                                          / SERVER_ERROR (5xx) / UNKNOWN (其余)
        - ``ValueError`` / ``KeyError`` → PARSING（``json.JSONDecodeError`` 是
                                          ValueError 子类）
        - 其余异常                        → UNKNOWN

        本方法总是抛出异常，不会正常返回。
        """
        if isinstance(exc, httpx.TimeoutException):
            logger.error(f"LLM 请求超时: {exc}")
            raise LLMError(LLMErrorType.TIMEOUT, f"请求 LLM 超时: {exc}")
        if isinstance(exc, httpx.ConnectError):
            logger.error(f"LLM 连接失败: {exc}")
            raise LLMError(LLMErrorType.NETWORK, f"无法连接 LLM: {exc}")
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status == 401:
                raise LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效或过期", status_code=401)
            if status == 429:
                retry_after = None
                try:
                    retry_after = int(exc.response.headers.get("retry-after", "0")) or None
                except (ValueError, TypeError):
                    retry_after = None
                raise LLMError(
                    LLMErrorType.RATE_LIMITED, "请求过于频繁，请稍后再试", retry_after=retry_after
                )
            if 500 <= status < 600:
                raise LLMError(
                    LLMErrorType.SERVER_ERROR, f"LLM 服务端错误 (HTTP {status})", status_code=status
                )
            raise LLMError(LLMErrorType.UNKNOWN, f"LLM HTTP 错误: {status}", status_code=status)
        if isinstance(exc, (ValueError, KeyError)):  # noqa: UP038  (Py3.8: isinstance 不支持 X | Y)
            logger.error(f"LLM 响应解析失败: {exc}")
            raise LLMError(LLMErrorType.PARSING, f"LLM 响应格式异常: {exc}")
        logger.error(f"LLM 请求未知失败: {exc}")
        raise LLMError(LLMErrorType.UNKNOWN, f"LLM 请求失败: {exc}")

    @staticmethod
    def _convert_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换消息格式"""
        result = []
        for msg in messages:
            entry = {"role": msg["role"], "content": msg["content"]}
            if "tool_calls" in msg:
                entry["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                entry["tool_call_id"] = msg["tool_call_id"]
            result.append(entry)
        return result

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: list) -> List[LLMToolCall]:
        """解析工具调用"""
        result = []
        for tc in raw_tool_calls:
            result.append(
                LLMToolCall(
                    id=tc.get("id", ""),
                    name=tc["function"]["name"],
                    arguments=tc["function"].get("arguments", "{}"),
                )
            )
        return result

    @staticmethod
    def _extract_think_tags(content: str) -> Tuple[Optional[str], str]:
        """
        从 content 中提取 <think>...</think> 标签内容。

        Args:
            content: LLM 输出的原始内容

        Returns:
            (reasoning_content, clean_content) 元组
            - reasoning_content: 提取的思考内容，无标签则为 None
            - clean_content: 移除 <think> 标签后的内容
        """
        matches = THINK_TAG_RE.findall(content)

        if not matches:
            # 没有 <think> 标签
            return None, content

        # 合并所有思考内容
        reasoning = "".join(matches)

        # 从 content 中移除所有 <think> 标签
        clean_content = THINK_TAG_RE.sub("", content)

        return reasoning, clean_content

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> LLMResponse:
        """
        发送聊天请求（非流式）

        Args:
            messages: 消息列表，每条包含 role 和 content
            tools: OpenAI 格式工具 schema 列表（可选）
            tool_choice: "auto" | "none" | "required"（默认 "auto"，仅当 tools 非空时写入请求体）

        Returns:
            LLM 回复
        """
        client = self._get_client()

        body = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"

        if self.config.provider == "claude":
            body["max_tokens"] = self.config.max_tokens

        # 推理参数透传: provider 决定哪种 key 会被上游接受
        # - OpenAI o1/o3/5 + DeepSeek + 多数 OpenAI 兼容代理: reasoning_effort
        # - Gemini 2.5 (OpenAI 兼容模式): thinking_budget
        # 同时存在时,让上游自己挑(不同 provider 接受不同 key)
        if self.config.reasoning_effort is not None:
            body["reasoning_effort"] = self.config.reasoning_effort
        if self.config.thinking_budget is not None:
            body["thinking_budget"] = self.config.thinking_budget

        start_time = time.time()

        # L3 重试退避: 限流/服务端错误/超时/网络失败按指数退避重试
        # （尊重 retry-after）。请求整体重放安全——非流式,无部分产出。
        max_attempts, base_delay = _retry_settings()
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await client.post("/v1/chat/completions", json=body)
                response.raise_for_status()
                data = response.json()
                break
            except Exception as e:
                try:
                    self._raise_classified_error(e)  # 总是抛出
                except LLMError as llm_err:
                    if (
                        attempt >= max_attempts
                        or llm_err.type not in _RETRYABLE_ERROR_TYPES
                    ):
                        raise
                    delay = _retry_backoff_seconds(llm_err, attempt, base_delay)
                    logger.warning(
                        "LLM 请求失败(%s/%s): %s — %.1fs 后重试",
                        attempt,
                        max_attempts,
                        llm_err.message,
                        delay,
                    )
                    await asyncio.sleep(delay)

        elapsed = time.time() - start_time
        logger.debug(f"LLM 响应耗时: {elapsed:.2f}s")

        choices = data.get("choices", [])
        if not choices:
            raise LLMError(LLMErrorType.PARSING, "LLM 返回空响应(无 choices)")

        choice = choices[0]
        msg_data = choice.get("message", {})
        content = msg_data.get("content", "")

        # 提取 reasoning_content（多提供商兼容）
        # Anthropic Claude 使用 reasoning_content 字段
        # OpenAI o1/o3 使用 reasoning 或 reasoning_content 字段
        # DeepSeek 使用 reasoning_content 字段
        # 优先使用 reasoning_content，其次 reasoning
        reasoning_content = msg_data.get("reasoning_content") or msg_data.get("reasoning")

        # 某些 LLM 提供商（如 DeepSeek）会把思考内容用 <think> 标签包裹在 content 中
        # 始终清理 content 中的 <think> 标签，无论 reasoning_content 字段是否存在
        if content:
            parsed_reasoning, parsed_content = self._extract_think_tags(content)
            # 如果 reasoning_content 字段为空，使用解析出的思考内容
            if not reasoning_content and parsed_reasoning is not None:
                reasoning_content = parsed_reasoning
            # 更新 content（移除 <think> 标签）
            content = parsed_content

        tool_calls = []
        if msg_data.get("tool_calls"):
            tool_calls = self._parse_tool_calls(msg_data["tool_calls"])

        usage = data.get("usage", {})

        # ===== M6 USAGE BEGIN: 规范化 usage + 记录到全局 tracker =====
        # tracker 故障永不影响 chat 返回 (fail-open)。
        usage_dict: Optional[Dict[str, int]] = None
        if isinstance(usage, dict) and usage:
            usage_dict = {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
                # L4: 缓存命中拆账（OpenAI details / DeepSeek / Anthropic 形态归一）
                "cached_tokens": extract_cached_tokens(usage),
            }
            try:
                from backend.services.usage_tracker import usage_tracker

                usage_tracker.record(
                    data.get("model", self.config.model),
                    usage_dict["prompt_tokens"],
                    usage_dict["completion_tokens"],
                    session_id=self.session_id,
                    cached_tokens=usage_dict["cached_tokens"],
                )
            except Exception as usage_err:
                logger.debug("usage tracking skipped: %s", usage_err)
        # ===== M6 USAGE END =====

        return LLMResponse(
            content=content,
            reasoning_content=reasoning_content,
            model=data.get("model", self.config.model),
            finish_reason=choice.get("finish_reason"),
            tool_calls=tool_calls,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            usage=usage_dict,
            raw=data,
        )

    async def chat_stream(self, messages: List[Dict[str, Any]]) -> AsyncGenerator[str, None]:
        """
        发送聊天请求（流式）

        Args:
            messages: 消息列表

        Yields:
            每个 chunk 的文本内容

        Raises:
            LLMError: 与 ``chat()`` 同一套分类规则（Task 11 已关闭）：
                超时 → TIMEOUT，连接失败 → NETWORK，HTTP 状态码 →
                AUTH_FAILED / RATE_LIMITED / SERVER_ERROR / UNKNOWN，
                解析失败 → PARSING。
        """
        client = self._get_client()

        body = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }

        if self.config.reasoning_effort is not None:
            body["reasoning_effort"] = self.config.reasoning_effort
        if self.config.thinking_budget is not None:
            body["thinking_budget"] = self.config.thinking_budget

        # ===== M6 USAGE BEGIN: 流式 usage 捕获 (final chunk 若携带 usage) =====
        stream_model: str = self.config.model
        stream_usage: Optional[Dict[str, Any]] = None
        # ===== M6 USAGE END =====

        try:
            async with client.stream("POST", "/v1/chat/completions", json=body) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                        # ===== M6 USAGE BEGIN =====
                        if isinstance(data.get("model"), str):
                            stream_model = data["model"]
                        if isinstance(data.get("usage"), dict):
                            stream_usage = data["usage"]
                        # ===== M6 USAGE END =====
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue

            # ===== M6 USAGE BEGIN: 流结束后记录 (tracker 故障 fail-open) =====
            if isinstance(stream_usage, dict) and stream_usage:
                try:
                    from backend.services.usage_tracker import usage_tracker

                    usage_tracker.record(
                        stream_model,
                        int(stream_usage.get("prompt_tokens") or 0),
                        int(stream_usage.get("completion_tokens") or 0),
                        session_id=self.session_id,
                        cached_tokens=extract_cached_tokens(stream_usage),
                    )
                except Exception as usage_err:
                    logger.debug("usage tracking (stream) skipped: %s", usage_err)
            # ===== M6 USAGE END =====

        except Exception as e:
            self._raise_classified_error(e)

    async def chat_stream_events(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        """流式 chat（L2 真流式）：内容/推理增量实时产出，工具调用增量聚合。

        与 ``chat_stream``（纯文本、无 tools、无聚合）的区别：本方法发送
        ``tools`` 与 ``stream_options.include_usage``，yield 结构化事件元组：

        - ``("content_delta", str)``      内容增量（原始流，未做 <think> 清理）
        - ``("reasoning_delta", str)``    推理增量（delta.reasoning_content / reasoning）
        - ``("response", LLMResponse)``   流结束（终值仅 yield 一次）：content 为
          全量（已做 <think> 提取），tool_calls 为聚合结果，usage 已记入 tracker

        请求失败时抛 ``LLMError``（与 ``chat()`` 同一套分类规则）。首个事件
        之前失败（如上游不支持 stream+tools 返回 4xx）时调用方可安全回退
        ``chat()`` 非流式；**已产出 content_delta 之后**失败不可重放，应按
        失败终止。调用方（agent.run_loop）据 ``stream_unsupported`` 标记跳过
        后续迭代的流式尝试。

        Args:
            messages: 消息列表
            tools: OpenAI 格式工具 schema 列表（可选）
            tool_choice: "auto" | "none" | "required"
        """
        client = self._get_client()

        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
            # OpenAI / DeepSeek / 多数兼容网关支持；不支持的由 run_loop
            # 回退非流式（本方法只在首个事件前抛错，重放安全）。
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
        if self.config.reasoning_effort is not None:
            body["reasoning_effort"] = self.config.reasoning_effort
        if self.config.thinking_budget is not None:
            body["thinking_budget"] = self.config.thinking_budget

        aggregator = StreamToolCallAggregator()
        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        finish_reason: Optional[str] = None
        stream_model: str = self.config.model
        stream_usage: Optional[Dict[str, Any]] = None

        # L3 重试退避（流式版）: 仅在"尚未产出任何增量"时重试——此时重放
        # 安全（调用方没收到过任何事件）;已有增量后失败无法安全重放,按原
        # 错误面终止（调用方语义见 run_loop）。
        max_attempts, base_delay = _retry_settings()
        attempt = 0
        while True:
            attempt += 1
            try:
                async with client.stream(
                    "POST", "/v1/chat/completions", json=body
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        if isinstance(data.get("model"), str):
                            stream_model = data["model"]
                        if isinstance(data.get("usage"), dict) and data["usage"]:
                            stream_usage = data["usage"]

                        choices = data.get("choices", [])
                        if not choices:
                            continue
                        choice = choices[0]
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                        delta = choice.get("delta") or {}

                        reasoning_piece = delta.get("reasoning_content") or delta.get(
                            "reasoning"
                        )
                        if isinstance(reasoning_piece, str) and reasoning_piece:
                            reasoning_parts.append(reasoning_piece)
                            yield ("reasoning_delta", reasoning_piece)

                        content_piece = delta.get("content")
                        if isinstance(content_piece, str) and content_piece:
                            content_parts.append(content_piece)
                            yield ("content_delta", content_piece)

                        if delta.get("tool_calls"):
                            aggregator.feed(delta["tool_calls"])
                break  # 流正常结束

            except Exception as e:
                try:
                    self._raise_classified_error(e)  # 总是抛出
                except LLMError as llm_err:
                    nothing_yielded = not content_parts and not reasoning_parts
                    if (
                        attempt >= max_attempts
                        or llm_err.type not in _RETRYABLE_ERROR_TYPES
                        or not nothing_yielded
                    ):
                        raise
                    delay = _retry_backoff_seconds(llm_err, attempt, base_delay)
                    logger.warning(
                        "LLM 流式请求失败(%s/%s): %s — %.1fs 后重试",
                        attempt,
                        max_attempts,
                        llm_err.message,
                        delay,
                    )
                    # 重置累积器,保证重放从零开始
                    aggregator = StreamToolCallAggregator()
                    content_parts = []
                    reasoning_parts = []
                    finish_reason = None
                    stream_usage = None
                    await asyncio.sleep(delay)

        raw_content = "".join(content_parts)
        reasoning_content = "".join(reasoning_parts) or None
        if raw_content:
            # <think> 标签清理与 chat() 同口径：字段缺失时用标签内容兜底。
            # 已知限制：流式期间 <think> 原文会先以 content_delta 下发,
            # 最终 response.content 为清理后的版本（DONE 收尾对齐）。
            parsed_reasoning, parsed_content = self._extract_think_tags(raw_content)
            if not reasoning_content and parsed_reasoning is not None:
                reasoning_content = parsed_reasoning
            raw_content = parsed_content

        usage_dict: Optional[Dict[str, int]] = None
        if isinstance(stream_usage, dict) and stream_usage:
            usage_dict = {
                "prompt_tokens": int(stream_usage.get("prompt_tokens") or 0),
                "completion_tokens": int(stream_usage.get("completion_tokens") or 0),
                "total_tokens": int(stream_usage.get("total_tokens") or 0),
                # L4: 缓存命中拆账（与 chat() 同口径）
                "cached_tokens": extract_cached_tokens(stream_usage),
            }
            try:
                from backend.services.usage_tracker import usage_tracker

                usage_tracker.record(
                    stream_model,
                    usage_dict["prompt_tokens"],
                    usage_dict["completion_tokens"],
                    session_id=self.session_id,
                    cached_tokens=usage_dict["cached_tokens"],
                )
            except Exception as usage_err:
                logger.debug("usage tracking (stream) skipped: %s", usage_err)

        yield (
            "response",
            LLMResponse(
                content=raw_content,
                reasoning_content=reasoning_content,
                model=stream_model,
                finish_reason=finish_reason,
                tool_calls=aggregator.build(),
                input_tokens=usage_dict["prompt_tokens"] if usage_dict else 0,
                output_tokens=usage_dict["completion_tokens"] if usage_dict else 0,
                total_tokens=usage_dict["total_tokens"] if usage_dict else 0,
                usage=usage_dict,
            ),
        )

    async def complete(self, prompt: str) -> str:
        """
        简单补全接口

        Args:
            prompt: 提示文本

        Returns:
            补全结果文本
        """
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat(messages)
        return response.content

    def to_dict(self) -> Dict[str, Any]:
        """导出配置信息"""
        return {
            "provider": self.config.provider,
            "model": self.config.model,
            "base_url": self.config.base_url,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
