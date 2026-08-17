"""OpenAI（及 OpenAI-compatible）Provider adapter（A2）。

用 httpx 直连厂商 ``/chat/completions`` REST API —— **不引入 openai
SDK**，保持 Sage 的零 SDK 依赖约束（Win7 LTS / Py3.8 打包矩阵）。
本模块同时作为 ``OllamaProvider`` 的基类（Ollama 暴露 OpenAI 兼容端点）。

Token 归一化语义（与 OpenWorker ``openai_provider._usage_from`` 对齐）：
``prompt_tokens`` **包含**缓存命中部分，需把
``prompt_tokens_details.cached_tokens`` 拆入 ``cache_read``，``input``
只保留未缓存的新 token。

流式说明：``stream`` 实现了 SSE 文本增量 + 流末 usage 归一化；
流内 tool_call 增量组装留给后续集成阶段（非流式 ``complete`` 已完整
支持工具调用）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional, Union

import httpx
from sage_core import Message, Role, ToolCall

from backend.adapters.out.llm._common import raise_classified_error
from backend.core.errors import LLMError, LLMErrorType
from backend.ports.llm import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    TokenUsage,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"

#: 允许透传到请求体的生成参数白名单（其余 settings 忽略，避免污染 wire 调用）。
_SETTING_PASSTHROUGH = (
    "temperature",
    "max_tokens",
    "top_p",
    "reasoning_effort",  # OpenAI o1/o3/5、DeepSeek、多数兼容代理
    "thinking_budget",  # Gemini 2.5 OpenAI 兼容模式
)


# ============================================================================
# 双向转换辅助（模块级纯函数，便于单测直接调用）
# ============================================================================


def messages_to_openai(messages: List[Message]) -> List[Dict[str, Any]]:
    """domain ``Message`` 列表 → OpenAI wire 格式 dict 列表。"""
    result: List[Dict[str, Any]] = []
    for msg in messages:
        entry: Dict[str, Any] = {
            "role": msg.role.value if isinstance(msg.role, Role) else str(msg.role),
            "content": msg.content,
        }
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id or "",
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.args, ensure_ascii=False),
                    },
                }
                for tc in msg.tool_calls
            ]
        if msg.tool_call_id is not None:
            entry["tool_call_id"] = msg.tool_call_id
        result.append(entry)
    return result


def usage_from_openai(usage: Optional[Dict[str, Any]]) -> Optional[TokenUsage]:
    """chat.completions ``usage`` → 归一化 4 字段。

    ``prompt_tokens`` 包含缓存命中部分：减去
    ``prompt_tokens_details.cached_tokens`` 拆入 ``cache_read``。
    OpenAI API 形态没有写侧分片，``cache_write`` 恒 0。
    无 usage（部分兼容服务器）返回 None —— 绝不猜测。
    """
    if not usage:
        return None
    prompt = int(usage.get("prompt_tokens") or 0)
    details = usage.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0) if isinstance(details, dict) else 0
    return TokenUsage(
        input=max(prompt - cached, 0),
        output=int(usage.get("completion_tokens") or 0),
        cache_read=cached,
    )


def turn_from_openai(data: Dict[str, Any], fallback_model: str) -> AssistantTurn:
    """chat.completions 响应 JSON → ``AssistantTurn``。

    tool_calls 的 ``arguments``（JSON 字符串）反序列化为 dict；非法 JSON
    安全降级为 ``{}`` 并记 warning（与 HttpxLLMAdapter 行为一致）。
    """
    choices = data.get("choices") or []
    if not choices:
        raise LLMError(LLMErrorType.PARSING, "LLM 返回空响应(无 choices)")
    choice = choices[0]
    msg_data = choice.get("message") or {}

    tool_calls: List[ToolCall] = []
    for tc in msg_data.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (ValueError, TypeError):
            logger.warning("OpenAI tool_call arguments 不是合法 JSON, 降级为空 dict: %r", raw_args)
            args = {}
        tool_calls.append(ToolCall(name=fn.get("name") or "", args=args, id=tc.get("id") or None))

    return AssistantTurn(
        text=msg_data.get("content") or "",
        tool_calls=tool_calls,
        finish_reason=choice.get("finish_reason"),
        reasoning=msg_data.get("reasoning_content") or msg_data.get("reasoning"),
        model=data.get("model") or fallback_model,
        usage=usage_from_openai(data.get("usage")),
        raw=data,
    )


# ============================================================================
# Adapter
# ============================================================================


class OpenAIProvider(ProviderClient):
    """OpenAI chat.completions 实现；任何 OpenAI-compatible 端点均可复用。

    用法::

        provider = OpenAIProvider(api_key="sk-xxx")
        turn = await provider.complete(
            model="gpt-4o",
            messages=[Message(role=Role.USER, content="hi")],
        )
    """

    #: 补全端点路径（相对 base_url）；子类可覆盖。
    completions_path = "/chat/completions"

    #: 默认能力标志；子类可覆盖。
    default_capabilities = ModelCapabilities()

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        extra_headers: Optional[Dict[str, str]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._extra_headers = dict(extra_headers or {})
        self._client = client
        # 注入的 client 不由本 provider 关闭（生命周期归调用方）。
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        """惰性创建 httpx client（关闭后可自动重建）。"""
        if self._client is None or self._client.is_closed:
            headers: Dict[str, str] = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            headers.update(self._extra_headers)
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=httpx.Timeout(self._timeout),
            )
            self._owns_client = True
        return self._client

    def _build_body(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: Optional[Union[str, Dict[str, Any]]],
        stream: bool,
        **settings: Any,
    ) -> Dict[str, Any]:
        """组装 chat.completions 请求体。"""
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_openai(messages),
            "stream": stream,
        }
        if stream:
            # 流末携带 usage（OpenAI 及多数兼容厂商支持；不支持的忽略该字段）。
            body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
        for key in _SETTING_PASSTHROUGH:
            if settings.get(key) is not None:
                body[key] = settings[key]
        return body

    # -- ProviderClient 实现 ----

    def capabilities(self, model: str) -> ModelCapabilities:
        """返回默认能力标志（OpenAI 全功能）。"""
        return self.default_capabilities

    async def complete(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        """非流式补全。"""
        client = self._get_client()
        body = self._build_body(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=False,
            **settings,
        )
        try:
            response = await client.post(self.completions_path, json=body)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 — 统一分类后重抛
            raise_classified_error(exc)
        return turn_from_openai(data, fallback_model=model)

    async def stream(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AsyncIterator[StreamChunk]:
        """SSE 流式：逐块 yield 文本增量，末尾 yield 携带 usage 的完整 turn。"""
        client = self._get_client()
        body = self._build_body(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            **settings,
        )
        usage: Optional[TokenUsage] = None
        text_parts: List[str] = []
        finish_reason: Optional[str] = None
        resp_model = model
        try:
            async with client.stream("POST", self.completions_path, json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: ") :].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if data.get("model"):
                        resp_model = data["model"]
                    chunk_usage = usage_from_openai(data.get("usage"))
                    if chunk_usage is not None:
                        usage = chunk_usage
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        text_parts.append(piece)
                        yield StreamChunk(text_delta=piece)
                    if choices[0].get("finish_reason"):
                        finish_reason = choices[0]["finish_reason"]
        except Exception as exc:  # noqa: BLE001 — 统一分类后重抛
            raise_classified_error(exc)
        turn = AssistantTurn(
            text="".join(text_parts),
            finish_reason=finish_reason,
            model=resp_model,
            usage=usage,
        )
        yield StreamChunk(turn=turn)

    async def aclose(self) -> None:
        """关闭自建 httpx client（注入的 client 不动）。"""
        if self._client is not None and self._owns_client and not self._client.is_closed:
            await self._client.aclose()
