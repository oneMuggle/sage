"""LLM HTTP 客户端 adapter（生产实现）。

把现有 ``core.llm_client.LLMClient`` 包装成实现 ``backend.ports.llm.LLMPort`` 的对象，
完成 ``domain.Message`` ↔ LLMClient 内部 ``dict`` 格式的双向转换。

设计要点
--------

- **不改 LLMClient**：保持其 dict 风格的 API 不变，adapter 只做翻译层。
- **构造参数透传** ``LLMConfig`` 字段（``provider/api_key/base_url/model/temperature/...``）。
- **LLMResponse → domain.Message**：把 ``LLMToolCall.arguments``（JSON 字符串）反序列化为
  ``domain.ToolCall.args``（dict）；空字符串安全降级为 ``{}``。
- **stream 透传**：``LLMClient.chat_stream`` 已是 async generator，adapter 直接 yield。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from backend.core.legacy.llm_client import LLMClient as _LLMClient, LLMConfig, LLMResponse
from backend.domain.message import Message, Role, ToolCall

logger = logging.getLogger(__name__)


# ============================================================================
# 双向转换辅助
# ============================================================================


def _to_domain_message(raw: LLMResponse) -> Message:
    """``LLMResponse`` → ``domain.Message``。

    - ``content``  ：直接透传（可能为空串）。
    - ``tool_calls``：把 ``LLMToolCall.arguments``（JSON 字符串）解析回 ``dict``；
                    解析失败时安全降级为 ``{}``，保证不抛错。
    - ``role``  ：固定为 ``ASSISTANT``（LLMClient 的 chat 返回值总是 assistant 消息）。
    """
    domain_tcs: list[ToolCall] = []
    for tc in raw.tool_calls or []:
        try:
            args: dict[str, Any] = json.loads(tc.arguments) if tc.arguments else {}
        except (ValueError, TypeError):
            logger.warning(
                "LLMClient 工具调用 arguments 不是合法 JSON, 降级为空 dict: %r",
                tc.arguments,
            )
            args = {}
        domain_tcs.append(ToolCall(name=tc.name, args=args, id=tc.id or None))

    return Message(
        role=Role.ASSISTANT,
        content=raw.content or "",
        tool_calls=domain_tcs,
    )


def _from_domain_message(msg: Message) -> dict[str, Any]:
    """``domain.Message`` → LLMClient 输入 dict。

    LLMClient 的 ``_convert_messages`` 会再次过滤（只保留 role/content/tool_calls/tool_call_id），
    但我们仍按 OpenAI 标准格式输出，避免依赖其内部实现细节。
    """
    entry: dict[str, Any] = {
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


# ============================================================================
# Adapter
# ============================================================================


class HttpxLLMAdapter:
    """``LLMPort`` 的 httpx 实现（生产）。包装现有 ``core.llm_client.LLMClient``。

    用法::

        adapter = HttpxLLMAdapter(
            provider="openai",
            api_key="sk-xxx",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        )
        reply = await adapter.chat([Message(role=Role.USER, content="hi")])

    构造参数与 ``LLMConfig`` 字段一一对应（``**kwargs`` → ``LLMConfig(**kwargs)``）。
    """

    def __init__(self, **kwargs: Any) -> None:
        config = LLMConfig(**kwargs)
        self._client = _LLMClient(config)

    # ---- LLMPort 实现 ----

    async def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> Message:
        """非流式对话：把 ``domain.Message`` 列表翻译成 LLMClient 输入并委派。

        Args:
            messages:    domain ``Message`` 列表。
            tools:       OpenAI 风格工具 schema 列表（透传）。
            tool_choice: ``"auto"`` / ``"none"`` / ``"required"`` 或 ``{"name": "..."}``（透传）。

        Returns:
            模型回复的 ``domain.Message``（可能带 ``tool_calls``）。
        """
        raw_messages = [_from_domain_message(m) for m in messages]
        # LLMClient.tool_choice 签名是 str | None；dict[str, Any] 形式由调用方自行
        # 解析为 provider-specific 形式，adapter 不做猜测。
        tc: str | None = tool_choice if isinstance(tool_choice, str) else None

        response: LLMResponse = await self._client.chat(
            raw_messages,
            tools=tools,
            tool_choice=tc,
        )
        return _to_domain_message(response)

    async def chat_stream(
        self,
        messages: list[Message],
    ) -> AsyncIterator[str]:
        """流式对话：逐 token 透传 LLMClient 的异步生成器。

        透传而非重新封装，避免在 adapter 层引入额外缓冲。
        """
        raw_messages = [_from_domain_message(m) for m in messages]
        async for chunk in self._client.chat_stream(raw_messages):
            yield chunk

    # ---- 公开辅助（便于测试 / 复用）----

    @staticmethod
    def from_domain(msg: Message) -> dict[str, Any]:
        """显式暴露 domain → dict 转换（单元测试直接调用）。"""
        return _from_domain_message(msg)

    @staticmethod
    def to_domain(raw: LLMResponse) -> Message:
        """显式暴露 LLMResponse → domain 转换（单元测试直接调用）。"""
        return _to_domain_message(raw)

    async def aclose(self) -> None:
        """关闭底层 httpx 客户端（与 LLMClient 生命周期对齐）。"""
        await self._client.close()
