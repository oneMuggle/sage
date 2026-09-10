"""Mock LLM adapter（测试用）。

用法：
    adapter = MockLLMAdapter(responses=[Message(role=ASSISTANT, content="hi")])
    result = await adapter.chat([Message(role=USER, content="hello")])
    assert result.content == "hi"
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional, Union

from sage_core import Message, Role
from sage_core.repositories import LLMPort


class MockLLMAdapter:
    """``LLMPort`` 的内存实现，供单元测试使用。

    行为：

    - ``chat``           按顺序消费 ``responses``；耗尽后返回 ``default_content``。
    - ``chat_stream``    把 ``default_content`` 逐字符 yield。
    - 每次调用都会被记录到 ``calls``（list[dict]），便于后续断言。
    - ``reset``          清空调用记录并把 responses 索引归零。
    - ``assert_called_with`` 断言最后一次调用的入参符合预期。

    该类不依赖网络 / 外部服务；可在 ``asyncio`` 测试中以普通对象形式使用。
    """

    def __init__(
        self,
        responses: Optional[List[Message]] = None,
        default_content: str = "[mock default]",
    ) -> None:
        self._responses: List[Message] = list(responses or [])
        self._index: int = 0
        self._default_content: str = default_content
        self.calls: List[Dict[str, Any]] = []

    # ---- LLMPort 实现 ----

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Any]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Message:
        """按顺序返回预置 responses；耗尽后回退到 ``default_content``。"""
        self.calls.append({"messages": messages, "tools": tools, "tool_choice": tool_choice})
        if self._index < len(self._responses):
            resp = self._responses[self._index]
            self._index += 1
            return resp
        return Message(role=Role.ASSISTANT, content=self._default_content)

    async def chat_stream(
        self,
        messages: List[Message],
    ) -> AsyncIterator[str]:
        """流式默认 yield ``default_content`` 的字符。"""
        self.calls.append({"messages": messages, "stream": True})
        for char in self._default_content:
            yield char

    # ---- 测试辅助 ----

    def assert_called_with(
        self,
        messages: Optional[List[Message]] = None,
        **kwargs: Any,
    ) -> None:
        """断言最后一次调用包含指定 messages 与其它参数。

        Args:
            messages: 期望的消息列表（精确相等比较）。传 ``None`` 表示跳过。
            **kwargs: 其它期望字段，如 ``tools=...`` / ``tool_choice=...`` /
                      ``stream=True``，按 ``==`` 与最后一次调用记录比较。
        """
        if not self.calls:
            raise AssertionError("LLM adapter was not called")
        last = self.calls[-1]
        if messages is not None:
            assert (
                last["messages"] == messages
            ), f"Expected messages={messages}, got {last['messages']}"
        for key, expected in kwargs.items():
            actual = last.get(key)
            assert actual == expected, f"Expected {key}={expected!r}, got {actual!r}"

    def reset(self) -> None:
        """重置调用记录和 responses 索引（便于跨测试复用同一实例）。"""
        self._index = 0
        self.calls.clear()


# 静态协议一致性声明（mypy / 文档）：用 Protocol 子类型规则校验结构一致性。
_: LLMPort = MockLLMAdapter(responses=[])  # type: ignore[assignment]
