"""Faux LLM Provider (A25 from pi)

模拟 LLM Provider，用于测试。完全避免真实 API 调用，测试成本低。

与 MockLLMAdapter 的区别：
- MockLLMAdapter: 简单的 mock，按顺序返回预设响应
- FauxProvider: 更完整的模拟，支持流式、token 统计、多轮对话

使用示例：
    faux = FauxProvider(responses=["Hello, world!"])
    result = await faux.complete(CompletionRequest(...))
    assert result.content == "Hello, world!"

    # 流式
    async for chunk in faux.stream(CompletionRequest(...)):
        print(chunk.content)

From pi's packages/ai/src/providers/faux.ts pattern.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Optional

from sage_core import Message, Role
from sage_core.repositories import LLMPort


@dataclass
class CompletionRequest:
    """Completion 请求"""
    messages: list[Message]
    tools: Optional[list[Any]] = None
    tool_choice: Optional[Any] = None
    temperature: float = 0.7
    max_tokens: int = 2048


@dataclass
class CompletionResponse:
    """Completion 响应"""
    content: str
    model: str = "faux-model"
    usage: dict[str, int] = field(default_factory=lambda: {
        "input": 10,
        "output": 20,
        "total": 30,
    })


@dataclass
class StreamChunk:
    """流式 chunk"""
    content: str
    is_done: bool = False


class FauxProvider:
    """
    模拟 LLM Provider (A25 from pi)

    特性：
    - 支持预设响应列表
    - 支持流式输出（逐字符）
    - 记录调用次数
    - 模拟 token 统计

    用途：
    - 单元测试：避免真实 API 调用
    - 集成测试：测试完整流程
    - CI/CD：不消耗 token
    """

    def __init__(
        self,
        responses: Optional[list[str]] = None,
        default_response: str = "This is a faux response.",
    ) -> None:
        """
        初始化 FauxProvider

        Args:
            responses: 预设响应列表，按顺序返回
            default_response: 默认响应（responses 耗尽后）
        """
        self.responses = responses or [default_response]
        self.default_response = default_response
        self.call_count = 0

    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        """
        返回预设响应

        Args:
            req: Completion 请求

        Returns:
            CompletionResponse
        """
        response = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1

        # 模拟 token 统计
        input_tokens = sum(len(m.content.split()) for m in req.messages)
        output_tokens = len(response.split())

        return CompletionResponse(
            content=response,
            model="faux-model",
            usage={
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
        )

    async def stream(self, req: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """
        流式返回预设响应（逐字符）

        Args:
            req: Completion 请求

        Yields:
            StreamChunk
        """
        response = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1

        for i, char in enumerate(response):
            yield StreamChunk(
                content=char,
                is_done=(i == len(response) - 1),
            )

    # ---- LLMPort 兼容接口 ----

    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[Any]] = None,
        tool_choice: Optional[Any] = None,
    ) -> Message:
        """LLMPort.chat 兼容接口"""
        req = CompletionRequest(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        resp = await self.complete(req)
        return Message(role=Role.ASSISTANT, content=resp.content)

    async def chat_stream(
        self,
        messages: list[Message],
    ) -> AsyncIterator[str]:
        """LLMPort.chat_stream 兼容接口"""
        req = CompletionRequest(messages=messages)
        async for chunk in self.stream(req):
            yield chunk.content


# 便捷函数
def create_faux_provider(responses: Optional[list[str]] = None) -> FauxProvider:
    """创建 FauxProvider（便捷函数）"""
    return FauxProvider(responses=responses)
