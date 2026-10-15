"""OpenAI / OpenAI-compatible Provider 适配器（A2）。

实现 ``ProviderClient`` ABC，直连 ``/v1/chat/completions`` 端点。
覆盖范围：

- OpenAI 官方（GPT-4o / o1 / o3 / GPT-5 系列）
- Azure OpenAI（路径一致，base_url 不同）
- 兼容 OpenAI 协议的代理（DeepSeek / Together / Groq / OpenRouter …）

设计要点

- **零 SDK 依赖**：只用 ``httpx``，不引入 ``openai`` Python 包。
- **消息格式**：入参为 ``domain.Message``，内部翻译为 OpenAI 风格 dict。
- **流式**：覆盖 ``stream()``，使用 SSE 逐 chunk 解析。
- **Usage 归一化**：把 ``usage.prompt_tokens``/``completion_tokens`` 映射到
  ``TokenUsage``（不报告 cache 分片时 cache 字段保持 0，绝不猜测）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import httpx
from sage_core import Message, Role, ToolCall

from backend.ports.llm import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    TokenUsage,
)

logger = logging.getLogger(__name__)

# OpenAI 风格 finish_reason → 统一词汇
_FINISH_REASON_MAP = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "content_filter": "stop",
}


class OpenAIProvider(ProviderClient):
    """OpenAI / OpenAI-compatible provider。

    Args:
        base_url: API 基础 URL（如 ``https://api.openai.com/v1``）。
        api_key:  API key（Authorization: Bearer）。
        timeout:  请求超时秒数（默认 120）。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._build_headers(api_key),
            timeout=timeout,
        )

    @staticmethod
    def _build_headers(api_key: str) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    # ------------------------------------------------------------------ #
    # ProviderClient 抽象方法实现
    # ------------------------------------------------------------------ #

    async def complete(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        body = self._build_body(
            model=model, messages=messages, tools=tools, tool_choice=tool_choice, **settings
        )
        response = await self._client.post("/chat/completions", json=body)
        response.raise_for_status()
        data = response.json()
        return self._parse_response(data)

    async def stream(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AsyncIterator[StreamChunk]:
        body = self._build_body(
            model=model, messages=messages, tools=tools, tool_choice=tool_choice, **settings
        )
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}

        async with self._client.stream("POST", "/chat/completions", json=body) as response:
            response.raise_for_status()
            async for chunk in self._iter_sse(response):
                yield chunk

    def capabilities(self, model: str) -> ModelCapabilities:
        # 启发式：o-系列支持 reasoning；gpt-4o/gpt-4o-mini 支持 vision
        lower = model.lower()
        reasoning = lower.startswith(("o1", "o3", "o5", "o-"))
        vision = "4o" in lower or "gpt-4-vision" in lower
        return ModelCapabilities(
            tools=True,
            vision=vision,
            streaming=True,
            parallel_tool_calls=not reasoning,  # o-系列不支持 parallel
            reasoning=reasoning,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #

    def _build_body(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: Optional[Union[str, Dict[str, Any]]],
        **settings: Any,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": model,
            "messages": [_serialize_message(m) for m in messages],
        }
        # 透传通用设置
        if "temperature" in settings:
            body["temperature"] = settings["temperature"]
        if "max_tokens" in settings:
            body["max_tokens"] = settings["max_tokens"]
        if "top_p" in settings:
            body["top_p"] = settings["top_p"]
        # 推理参数（o-系列用 reasoning_effort）
        if "reasoning_effort" in settings:
            body["reasoning_effort"] = settings["reasoning_effort"]
        # 工具
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice if tool_choice is not None else "auto"
        return body

    def _parse_response(self, data: Dict[str, Any]) -> AssistantTurn:
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        # 文本
        text = msg.get("content") or None
        # 推理内容（o-系列 reasoning_content / 部分代理 reasoning）
        reasoning = msg.get("reasoning_content") or msg.get("reasoning")
        # 工具调用
        tool_calls: List[ToolCall] = []
        for raw_tc in msg.get("tool_calls") or []:
            fn = raw_tc.get("function", {})
            args_raw = fn.get("arguments", "")
            try:
                args: Dict[str, Any] = json.loads(args_raw) if args_raw else {}
            except (ValueError, TypeError):
                logger.warning("tool_call arguments 不是合法 JSON: %r", args_raw)
                args = {}
            tool_calls.append(
                ToolCall(
                    name=fn.get("name", ""),
                    args=args,
                    id=raw_tc.get("id"),
                )
            )
        # finish_reason 归一化
        raw_reason = choice.get("finish_reason", "")
        finish_reason = _FINISH_REASON_MAP.get(raw_reason, raw_reason or None)
        # usage
        usage = _parse_usage(data.get("usage"))
        return AssistantTurn(
            text=text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning=reasoning,
            model=data.get("model", ""),
            usage=usage,
            raw=data,
        )

    async def _iter_sse(self, response: httpx.Response) -> AsyncIterator[StreamChunk]:
        """解析 OpenAI 风格的 SSE 流。"""
        buf = b""
        async for raw_chunk in response.aiter_bytes():
            buf += raw_chunk
            while b"\n\n" in buf:
                event_bytes, buf = buf.split(b"\n\n", 1)
                event_text = event_bytes.decode("utf-8", errors="replace")
                # 逐行解析 data: 前缀
                for line in event_text.splitlines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    chunk = _parse_stream_chunk(data)
                    if chunk is not None:
                        yield chunk


def _parse_stream_chunk(data: Dict[str, Any]) -> Optional[StreamChunk]:
    """解析单个 SSE data 块。"""
    choices = data.get("choices", [])
    if not choices:
        # 可能只有 usage（stream_options.include_usage=True）
        usage = _parse_usage(data.get("usage"))
        if usage is not None:
            return StreamChunk(turn=AssistantTurn(usage=usage, raw=data))
        return None
    delta = choices[0].get("delta", {})
    text_delta = delta.get("content") or None
    reasoning_delta = delta.get("reasoning_content") or delta.get("reasoning")
    # 流末 finish_reason 存在时，组装完整 turn
    finish_reason = choices[0].get("finish_reason")
    turn: Optional[AssistantTurn] = None
    if finish_reason is not None:
        usage = _parse_usage(data.get("usage"))
        turn = AssistantTurn(
            finish_reason=_FINISH_REASON_MAP.get(finish_reason, finish_reason),
            model=data.get("model", ""),
            usage=usage,
            raw=data,
        )
    return StreamChunk(
        text_delta=text_delta,
        reasoning_delta=reasoning_delta,
        turn=turn,
    )


def _serialize_message(msg: Message) -> Dict[str, Any]:
    """``domain.Message`` → OpenAI 风格 dict。"""
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
    return entry


def _parse_usage(raw: Optional[Dict[str, Any]]) -> Optional[TokenUsage]:
    """OpenAI usage → TokenUsage（不报告 cache 分片时保持 0）。"""
    if not raw:
        return None
    cached = 0
    details = raw.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = details.get("cached_tokens", 0)
    return TokenUsage(
        input=raw.get("prompt_tokens", 0),
        output=raw.get("completion_tokens", 0),
        cache_read=cached,
    )
