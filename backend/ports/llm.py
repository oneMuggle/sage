"""LLM Provider 端口。

定义 LLM 调用的抽象接口，由 ``backend.adapters.llm.httpx_llm``
（HttpxLLMAdapter）与 ``backend.adapters.llm.mock_llm``
（MockLLMAdapter）实现。Application 层只依赖本接口，不耦合
具体 provider（OpenAI / Anthropic / Ollama …）。

约定：

- ``chat``         非流式对话；返回完整 ``Message``。
- ``chat_stream``  流式对话；逐 token 返回字符串 delta。

A2（Provider 抽象 + Token 归一化，借鉴 OpenWorker ``coworker/providers``）
新增：

- ``TokenUsage``       跨厂商归一化的 token 用量（input/output/cache_read/cache_write）。
- ``AssistantTurn``    一次模型回复（文本 + 工具调用 + 归一化用量）。
- ``StreamChunk``      流式输出分片（增量 delta；最终片携带完整 turn）。
- ``ModelCapabilities`` 模型能力标志（工具/视觉/流式 …），用于优雅降级。
- ``ProviderClient``   provider 无关的单次补全接口（ABC），由
                       ``backend.adapters.out.llm.{openai,anthropic,gemini,ollama}``
                       与 ``ProviderRouter`` 实现。

``LLMPort`` 保留作向后兼容；新代码优先面向 ``ProviderClient`` 编程。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Union

from sage_core import Message, Role, ToolCall


class LLMPort(Protocol):
    """LLM 调用端口。"""

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Any]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Message:
        """非流式对话。

        Args:
            messages:    对话历史（domain ``Message`` 列表）。
            tools:       工具规格列表（通常为 ``ToolSpec`` 字典序列），
                         可选。
            tool_choice: 工具选择策略（如 ``"auto"`` /
                         ``{"name": "..."}``），可选。

        Returns:
            模型生成的完整 ``Message``（可能带 ``tool_calls``）。
        """
        ...

    def chat_stream(
        self,
        messages: List[Message],
    ) -> AsyncIterator[str]:
        """流式对话（逐 token delta）。

        Args:
            messages: 对话历史。

        Yields:
            模型生成的增量文本片段。
        """
        ...


# ============================================================================
# A2: Provider 抽象 + Token 归一化
# ============================================================================
#
# 借鉴 OpenWorker ``coworker/providers/base.py`` 的设计，适配 Sage 的
# async-first 技术栈（FastAPI / asyncio）。运行时不直接触碰厂商 SDK 或
# wire 协议，所有模型访问都经过 ``ProviderClient``。


@dataclass
class TokenUsage:
    """跨厂商归一化的 token 用量（4 字段）。

    字段语义（与 OpenWorker 对齐）：

    - ``input``       仅统计**未命中缓存**的新 prompt token
    - ``cache_read``  命中缓存读取的 prompt token
    - ``cache_write`` 写入缓存的 prompt token（Anthropic cache creation）
    - ``output``      输出 token；厂商把 thinking token 按 output 计费时
                      （Gemini ``thoughtsTokenCount``）一并折入本字段

    不报告缓存分片的 provider（Ollama 及多数 OpenAI-compatible 兼容
    厂商）cache 字段保持 0 —— **绝不猜测**。
    """

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def context_tokens(self) -> int:
        """Prompt 侧总量 —— 实际占用上下文窗口的 token 数。"""
        return self.input + self.cache_read + self.cache_write

    @property
    def total_tokens(self) -> int:
        """本次往返的总 token 数（prompt 侧 + 输出侧）。"""
        return self.context_tokens + self.output

    def as_dict(self) -> Dict[str, int]:
        """序列化为 4 字段 dict（供 API / 持久化使用）。"""
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
        }

    def __add__(self, other: object) -> TokenUsage:
        """逐字段相加（跨 turn 累计用量）。"""
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
        )


@dataclass
class AssistantTurn:
    """一次模型回复：自由文本和/或工具调用，附带归一化 token 用量。

    ``finish_reason`` 统一为 OpenAI 风格词汇：``stop`` / ``tool_calls`` /
    ``length``；各 adapter 负责把厂商原生值映射过来。
    """

    text: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None
    # 模型思考内容（Claude extended thinking / Gemini thought summaries /
    # DeepSeek reasoning_content）。仅展示与持久化，不应回放为上下文。
    reasoning: Optional[str] = None
    model: str = ""
    # 未报告 usage 的兼容服务器为 None —— 绝不猜测。
    usage: Optional[TokenUsage] = None
    raw: Any = field(default=None, repr=False, compare=False)

    @property
    def has_tool_calls(self) -> bool:
        """是否包含工具调用。"""
        return bool(self.tool_calls)

    def to_message(self) -> Message:
        """转换为 domain ``Message``（便于复用现有 ChatService 工具循环）。"""
        return Message(
            role=Role.ASSISTANT,
            content=self.text or "",
            tool_calls=list(self.tool_calls),
        )


@dataclass
class StreamChunk:
    """流式输出的一个分片。

    增量片携带 ``text_delta`` / ``reasoning_delta``；最终片携带完整的
    ``turn``（含归一化 ``usage``，若 provider 在流末报告）。
    """

    text_delta: Optional[str] = None
    reasoning_delta: Optional[str] = None
    turn: Optional[AssistantTurn] = None


@dataclass(frozen=True)
class ModelCapabilities:
    """模型能力标志，用于优雅降级。"""

    tools: bool = True
    vision: bool = False
    streaming: bool = True
    parallel_tool_calls: bool = True
    reasoning: bool = False


class ProviderClient(ABC):
    """单次、provider 无关的补全接口（A2）。

    设计要点（借鉴 OpenWorker，async 化适配 Sage）：

    - ``complete`` 返回一个 ``AssistantTurn``；**不含 agent 循环**，
      多轮工具编排归运行时（ChatService / agent loop）所有。
    - ``messages`` 使用 domain ``Message``；``tools`` 使用 OpenAI 风格
      schema dict（中立格式，各 adapter 翻译成厂商 wire 格式）。
    - ``stream`` 提供兜底默认实现（把 ``complete`` 结果包成单个最终
      chunk）；支持 token 级流式的 provider 覆盖之。
    - 生命周期：``aclose`` 释放底层 HTTP 资源（默认 no-op）。
    """

    @abstractmethod
    async def complete(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        """对给定 messages/tools 返回一次模型回复。"""

    @abstractmethod
    def capabilities(self, model: str) -> ModelCapabilities:
        """返回给定模型的能力标志。"""

    async def stream(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AsyncIterator[StreamChunk]:
        """流式输出。默认实现：不做 token 级流式，仅产出一个携带完整
        turn 的最终 chunk。支持流式的 provider 覆盖本方法。"""
        turn = await self.complete(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **settings,
        )
        yield StreamChunk(text_delta=turn.text, turn=turn)

    async def aclose(self) -> None:
        """释放底层 HTTP 资源（默认 no-op）。"""
        return
