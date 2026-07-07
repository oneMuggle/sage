"""LLM Provider 端口。

定义 LLM 调用的抽象接口，由 ``backend.adapters.llm.httpx_llm``
（HttpxLLMAdapter）与 ``backend.adapters.llm.mock_llm``
（MockLLMAdapter）实现。Application 层只依赖本接口，不耦合
具体 provider（OpenAI / Anthropic / Ollama …）。

约定：

- ``chat``         非流式对话；返回完整 ``Message``。
- ``chat_stream``  流式对话；逐 token 返回字符串 delta。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional, Protocol, Union

from sage_core import Message


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
