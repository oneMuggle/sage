"""Anthropic Messages API Provider 适配器（A2）。

实现 ``ProviderClient`` ABC，直连 Anthropic 原生 ``/v1/messages`` 端点。

设计要点

- **零 SDK 依赖**：只用 ``httpx``，不引入 ``anthropic`` Python 包。
- **消息格式转换**：Anthropic 的 system 消息是顶层 ``system`` 字段，
  工具调用用 content block 而非 tool_calls 数组。
- **认证**：``x-api-key`` + ``anthropic-version`` 头。
- **Usage**：Anthropic 不报告 cache 分片时保持 0；cache_creation_input_tokens
  和 cache_read_input_tokens 存在时映射到 ``cache_write`` / ``cache_read``。
- **流式**：SSE 事件流，事件类型 ``message_start`` / ``content_block_delta``
  / ``message_delta`` / ``message_stop``。
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

# Anthropic stop_reason → 统一词汇
_STOP_REASON_MAP = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
}

# Anthropic API 版本（固定到支持 tool use + streaming 的稳定版本）
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(ProviderClient):
    """Anthropic Messages API provider。

    Args:
        base_url: API 基础 URL（默认 ``https://api.anthropic.com``）。
        api_key:  API key（x-api-key 头）。
        timeout:  请求超时秒数（默认 120）。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
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
        return {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
        }

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
        response = await self._client.post("/v1/messages", json=body)
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
        async with self._client.stream("POST", "/v1/messages", json=body) as response:
            response.raise_for_status()
            async for chunk in self._iter_sse(response):
                yield chunk

    def capabilities(self, model: str) -> ModelCapabilities:
        lower = model.lower()
        # Claude 3.5+ 支持 vision；推理能力由 extended thinking 提供
        vision = "claude-3" in lower or "claude-4" in lower
        reasoning = "claude-3-7" in lower or "claude-4" in lower
        return ModelCapabilities(
            tools=True,
            vision=vision,
            streaming=True,
            parallel_tool_calls=True,
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
        # 分离 system 消息（Anthropic 用顶层字段）
        system_text: Optional[str] = None
        api_messages: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.role.value if isinstance(msg.role, Role) else str(msg.role)
            if role == "system":
                system_text = msg.content
                continue
            api_messages.append(_serialize_message(msg))

        body: Dict[str, Any] = {
            "model": model,
            "max_tokens": settings.get("max_tokens", 4096),
            "messages": api_messages,
        }
        if system_text is not None:
            body["system"] = system_text
        if "temperature" in settings:
            body["temperature"] = settings["temperature"]
        if "top_p" in settings:
            body["top_p"] = settings["top_p"]
        # 推理参数（extended thinking）
        if "thinking_budget" in settings:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": settings["thinking_budget"],
            }
        # 工具
        if tools:
            body["tools"] = [_convert_tool_schema(t) for t in tools]
            if tool_choice is not None:
                body["tool_choice"] = _convert_tool_choice(tool_choice)
        return body

    def _parse_response(self, data: Dict[str, Any]) -> AssistantTurn:
        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        reasoning_parts: List[str] = []

        for block in data.get("content", []):
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        name=block.get("name", ""),
                        args=block.get("input", {}),
                        id=block.get("id"),
                    )
                )
            elif block_type == "thinking":
                reasoning_parts.append(block.get("thinking", ""))

        text = "".join(text_parts) or None
        reasoning = "".join(reasoning_parts) or None
        raw_reason = data.get("stop_reason", "")
        finish_reason = _STOP_REASON_MAP.get(raw_reason, raw_reason or None)
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
        """解析 Anthropic 风格 SSE 事件流。"""
        buf = b""
        usage_data: Optional[Dict[str, Any]] = None
        model_name: str = ""
        stop_reason: Optional[str] = None

        async for raw_chunk in response.aiter_bytes():
            buf += raw_chunk
            while b"\n\n" in buf:
                event_bytes, buf = buf.split(b"\n\n", 1)
                event_text = event_bytes.decode("utf-8", errors="replace")
                event_type: Optional[str] = None
                data_payload: Optional[str] = None
                for line in event_text.splitlines():
                    if line.startswith("event:"):
                        event_type = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data_payload = line[len("data:"):].strip()
                if event_type is None or data_payload is None:
                    continue
                try:
                    data_obj = json.loads(data_payload)
                except json.JSONDecodeError:
                    continue

                if event_type == "message_start":
                    msg = data_obj.get("message", {})
                    model_name = msg.get("model", "")
                    usage_data = msg.get("usage")
                elif event_type == "content_block_delta":
                    delta = data_obj.get("delta", {})
                    delta_type = delta.get("type")
                    if delta_type == "text_delta":
                        yield StreamChunk(text_delta=delta.get("text"))
                    elif delta_type == "thinking_delta":
                        yield StreamChunk(reasoning_delta=delta.get("thinking"))
                elif event_type == "message_delta":
                    delta = data_obj.get("delta", {})
                    stop_reason = delta.get("stop_reason")
                    final_usage = data_obj.get("usage")
                    if final_usage and usage_data:
                        usage_data = {**usage_data, **final_usage}
                elif event_type == "message_stop":
                    usage = _parse_usage(usage_data)
                    yield StreamChunk(
                        turn=AssistantTurn(
                            finish_reason=_STOP_REASON_MAP.get(
                                stop_reason or "", stop_reason
                            ),
                            model=model_name,
                            usage=usage,
                            raw=data_obj,
                        )
                    )


# ============================================================================
# 模块级辅助
# ============================================================================


def _serialize_message(msg: Message) -> Dict[str, Any]:
    """``domain.Message`` → Anthropic 风格 dict。

    Anthropic 与 OpenAI 的关键差异：

    - tool call 结果：role 为 ``user``，content 为 tool_result block 数组
    - assistant tool_calls：content 为 tool_use block 数组
    """
    role = msg.role.value if isinstance(msg.role, Role) else str(msg.role)

    # 工具结果消息（tool_call_id 存在）
    if role == "tool" or msg.tool_call_id is not None:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content,
                }
            ],
        }

    # assistant 带工具调用
    if role == "assistant" and msg.tool_calls:
        content_blocks: List[Dict[str, Any]] = []
        if msg.content:
            content_blocks.append({"type": "text", "text": msg.content})
        for tc in msg.tool_calls:
            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": tc.id or "",
                    "name": tc.name,
                    "input": tc.args,
                }
            )
        return {"role": "assistant", "content": content_blocks}

    # 普通消息
    return {"role": role, "content": msg.content}


def _convert_tool_schema(tool: Dict[str, Any]) -> Dict[str, Any]:
    """OpenAI 风格 tool schema → Anthropic 风格。

    OpenAI: ``{"type": "function", "function": {"name": ..., "parameters": ...}}``
    Anthropic: ``{"name": ..., "description": ..., "input_schema": ...}``
    """
    fn = tool.get("function", tool)
    return {
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
    }


def _convert_tool_choice(choice: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """OpenAI tool_choice → Anthropic tool_choice。"""
    if isinstance(choice, str):
        if choice == "auto":
            return {"type": "auto"}
        if choice == "required":
            return {"type": "any"}
        if choice == "none":
            return {"type": "none"}
        return {"type": "auto"}
    if isinstance(choice, dict) and "name" in choice:
        return {"type": "tool", "name": choice["name"]}
    return {"type": "auto"}


def _parse_usage(raw: Optional[Dict[str, Any]]) -> Optional[TokenUsage]:
    """Anthropic usage → TokenUsage。

    Anthropic 字段：input_tokens / output_tokens /
    cache_creation_input_tokens（→ cache_write）/
    cache_read_input_tokens（→ cache_read）。
    """
    if not raw:
        return None
    return TokenUsage(
        input=raw.get("input_tokens", 0),
        output=raw.get("output_tokens", 0),
        cache_write=raw.get("cache_creation_input_tokens", 0),
        cache_read=raw.get("cache_read_input_tokens", 0),
    )
