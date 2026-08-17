"""Anthropic（Claude Messages API）Provider adapter（A2）。

用 httpx 直连 ``POST /v1/messages`` REST API —— **不引入 anthropic
SDK**，保持 Sage 的零 SDK 依赖约束（Win7 LTS / Py3.8 打包矩阵）。

消息格式翻译要点：

- SYSTEM 消息抽为顶层 ``system`` 参数（多条以空行拼接）。
- TOOL 消息翻译为 user 侧 ``tool_result`` content block。
- ASSISTANT 的 tool_calls 翻译为 ``tool_use`` content block。
- Anthropic 要求 user/assistant **严格交替**：连续同 role 消息的
  content block 合并到同一条 wire 消息。

Token 归一化语义（与 OpenWorker ``anthropic_provider._usage_from`` 对齐）：
``input_tokens`` 本身**不含**缓存部分；``cache_read_input_tokens`` →
``cache_read``，``cache_creation_input_tokens`` → ``cache_write``。

流式说明：``stream`` 解析 Anthropic SSE 事件流
（``message_start`` / ``content_block_start`` / ``content_block_delta`` /
``message_delta``），支持文本增量、thinking 增量与流内 tool_use 组装，
流末 yield 携带完整归一化 usage 的 turn。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from sage_core import Message, Role, ToolCall

from backend.adapters.out.llm._common import raise_classified_error
from backend.ports.llm import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    TokenUsage,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
#: Anthropic 的 ``max_tokens`` 为必填项；调用方未指定时使用本默认值。
DEFAULT_MAX_TOKENS = 4096

#: Anthropic stop_reason → OpenAI 风格 finish_reason 词汇。
FINISH_REASON_MAP = {
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "stop_sequence": "stop",
}


# ============================================================================
# 双向转换辅助（模块级纯函数，便于单测直接调用）
# ============================================================================


def messages_to_anthropic(
    messages: List[Message],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """domain ``Message`` 列表 → ``(system, wire_messages)``。

    - SYSTEM 消息合并为顶层 ``system`` 字符串（多条以 ``\\n\\n`` 拼接）。
    - TOOL 消息 → user 角色 ``tool_result`` block。
    - ASSISTANT 消息 → text block + ``tool_use`` block。
    - 连续同角色消息的 block 合并（Anthropic 要求 user/assistant 交替）。
    """
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.role if isinstance(msg.role, Role) else Role(str(msg.role))

        if role is Role.SYSTEM:
            if msg.content:
                system_parts.append(msg.content)
            continue

        blocks: List[Dict[str, Any]]
        if role is Role.TOOL:
            wire_role = "user"
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content,
                }
            ]
        elif role is Role.ASSISTANT:
            wire_role = "assistant"
            blocks = []
            if msg.content:
                blocks.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id or "",
                        "name": tc.name,
                        "input": tc.args,
                    }
                )
            if not blocks:  # 空 assistant 消息兜底，避免非法空 content
                blocks.append({"type": "text", "text": ""})
        else:  # USER
            wire_role = "user"
            blocks = [{"type": "text", "text": msg.content}]

        if out and out[-1]["role"] == wire_role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": wire_role, "content": blocks})

    system = "\n\n".join(system_parts) if system_parts else None
    return system, out


def tools_to_anthropic(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """OpenAI 风格工具 schema → Anthropic tools 格式。

    输入形如 ``{"type": "function", "function": {name, description, parameters}}``；
    也容忍已经扁平的 ``{name, description, parameters}``。
    """
    result: List[Dict[str, Any]] = []
    for spec in tools or []:
        fn = spec.get("function") or spec
        result.append(
            {
                "name": fn.get("name") or "",
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return result


def tool_choice_to_anthropic(
    tool_choice: Optional[Union[str, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """OpenAI 风格 tool_choice → Anthropic tool_choice 对象。"""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function") or tool_choice
        name = fn.get("name")
        return {"type": "tool", "name": name} if name else {"type": "any"}
    return {"type": {"auto": "auto", "required": "any", "none": "none"}.get(tool_choice, "auto")}


def usage_from_anthropic(usage: Optional[Dict[str, Any]]) -> Optional[TokenUsage]:
    """Messages API ``usage`` → 归一化 4 字段。

    ``input_tokens`` 本身不含缓存部分（与 OpenAI/Gemini 相反），
    因此无需减法；``cache_read_input_tokens`` /
    ``cache_creation_input_tokens`` 直接映射。
    """
    if not usage:
        return None
    return TokenUsage(
        input=int(usage.get("input_tokens") or 0),
        output=int(usage.get("output_tokens") or 0),
        cache_read=int(usage.get("cache_read_input_tokens") or 0),
        cache_write=int(usage.get("cache_creation_input_tokens") or 0),
    )


def turn_from_anthropic(data: Dict[str, Any], fallback_model: str) -> AssistantTurn:
    """Messages API 响应 JSON → ``AssistantTurn``。"""
    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_calls: List[ToolCall] = []

    for block in data.get("content") or []:
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text") or "")
        elif block_type == "thinking":
            reasoning_parts.append(block.get("thinking") or "")
        elif block_type == "tool_use":
            tool_calls.append(
                ToolCall(
                    name=block.get("name") or "",
                    args=block.get("input") or {},
                    id=block.get("id") or None,
                )
            )

    stop_reason = data.get("stop_reason")
    finish_reason = (
        FINISH_REASON_MAP.get(stop_reason, stop_reason)
        if isinstance(stop_reason, str)
        else stop_reason
    )
    return AssistantTurn(
        text="".join(text_parts),
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        reasoning="".join(reasoning_parts) or None,
        model=data.get("model") or fallback_model,
        usage=usage_from_anthropic(data.get("usage")),
        raw=data,
    )


# ============================================================================
# Adapter
# ============================================================================


class AnthropicProvider(ProviderClient):
    """Anthropic Messages API 实现。

    用法::

        provider = AnthropicProvider(api_key="sk-ant-xxx")
        turn = await provider.complete(
            model="claude-sonnet-4-5",
            messages=[Message(role=Role.USER, content="hi")],
        )
    """

    completions_path = "/v1/messages"

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        extra_headers: Optional[Dict[str, str]] = None,
        client: Optional[httpx.AsyncClient] = None,
        anthropic_version: str = DEFAULT_ANTHROPIC_VERSION,
        default_max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._extra_headers = dict(extra_headers or {})
        self._anthropic_version = anthropic_version
        self._default_max_tokens = default_max_tokens
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        """惰性创建 httpx client（关闭后可自动重建）。"""
        if self._client is None or self._client.is_closed:
            headers: Dict[str, str] = {
                "Content-Type": "application/json",
                "anthropic-version": self._anthropic_version,
            }
            if self._api_key:
                headers["x-api-key"] = self._api_key
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
        """组装 Messages API 请求体。"""
        system, wire_messages = messages_to_anthropic(messages)
        body: Dict[str, Any] = {
            "model": model,
            "messages": wire_messages,
            # Anthropic 必填项；调用方未显式指定时用默认值。
            "max_tokens": settings.get("max_tokens") or self._default_max_tokens,
        }
        if stream:
            body["stream"] = True
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools_to_anthropic(tools)
            choice = tool_choice_to_anthropic(tool_choice)
            if choice:
                body["tool_choice"] = choice
        if settings.get("temperature") is not None:
            body["temperature"] = settings["temperature"]
        if settings.get("top_p") is not None:
            body["top_p"] = settings["top_p"]
        if settings.get("thinking_budget") is not None:
            # Claude extended thinking：{"type": "enabled", "budget_tokens": N}
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": settings["thinking_budget"],
            }
        return body

    # -- ProviderClient 实现 ----

    def capabilities(self, model: str) -> ModelCapabilities:
        """Claude 能力：工具 + 流式 + 推理；并行工具调用默认开启。"""
        return ModelCapabilities(vision=True, reasoning=True)

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
        return turn_from_anthropic(data, fallback_model=model)

    async def stream(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AsyncIterator[StreamChunk]:
        """解析 Anthropic SSE 事件流，末尾 yield 携带完整 usage 的 turn。

        事件处理：

        - ``message_start``        初始化 model + prompt 侧 usage
        - ``content_block_start``  tool_use block 开工（记录 index/id/name）
        - ``content_block_delta``  text_delta / thinking_delta / input_json_delta
        - ``message_delta``        stop_reason + 累计 output_tokens
        """
        client = self._get_client()
        body = self._build_body(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            **settings,
        )

        usage = TokenUsage()
        text_parts: List[str] = []
        reasoning_parts: List[str] = []
        finish_reason: Optional[str] = None
        resp_model = model
        # index → 正在组装的 tool_use（id/name/args JSON 片段）
        tool_blocks: Dict[int, Dict[str, Any]] = {}

        try:
            async with client.stream("POST", self.completions_path, json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: ") :].strip()
                    if not payload:
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")
                    if etype == "message_start":
                        message = event.get("message") or {}
                        resp_model = message.get("model") or resp_model
                        start_usage = usage_from_anthropic(message.get("usage"))
                        if start_usage is not None:
                            usage = start_usage
                    elif etype == "content_block_start":
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            tool_blocks[event.get("index", 0)] = {
                                "id": block.get("id") or None,
                                "name": block.get("name") or "",
                                "args_json": "",
                            }
                    elif etype == "content_block_delta":
                        delta = event.get("delta") or {}
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            piece = delta.get("text") or ""
                            if piece:
                                text_parts.append(piece)
                                yield StreamChunk(text_delta=piece)
                        elif dtype == "thinking_delta":
                            piece = delta.get("thinking") or ""
                            if piece:
                                reasoning_parts.append(piece)
                                yield StreamChunk(reasoning_delta=piece)
                        elif dtype == "input_json_delta":
                            idx = event.get("index", 0)
                            if idx in tool_blocks:
                                tool_blocks[idx]["args_json"] += delta.get("partial_json") or ""
                    elif etype == "message_delta":
                        delta = event.get("delta") or {}
                        stop_reason = delta.get("stop_reason")
                        if stop_reason:
                            finish_reason = FINISH_REASON_MAP.get(stop_reason, stop_reason)
                        # 累计 output token 数挂在 message_delta.usage 上。
                        out = int((event.get("usage") or {}).get("output_tokens") or 0)
                        if out:
                            usage.output = out
        except Exception as exc:  # noqa: BLE001 — 统一分类后重抛
            raise_classified_error(exc)

        tool_calls: List[ToolCall] = []
        for idx in sorted(tool_blocks):
            tb = tool_blocks[idx]
            raw_args = tb["args_json"] or "{}"
            try:
                args = json.loads(raw_args)
            except (ValueError, TypeError):
                logger.warning(
                    "Anthropic tool_use input_json 不是合法 JSON, 降级为空 dict: %r",
                    raw_args,
                )
                args = {}
            tool_calls.append(ToolCall(name=tb["name"], args=args, id=tb["id"]))

        turn = AssistantTurn(
            text="".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning="".join(reasoning_parts) or None,
            model=resp_model,
            usage=usage,
        )
        yield StreamChunk(turn=turn)

    async def aclose(self) -> None:
        """关闭自建 httpx client（注入的 client 不动）。"""
        if self._client is not None and self._owns_client and not self._client.is_closed:
            await self._client.aclose()
