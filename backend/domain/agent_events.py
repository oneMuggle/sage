"""
Agent 事件发布-订阅架构 (A23 from pi)

标准化的 Agent 事件流，支持 steering 和 follow-up 队列。

事件类型：
- agent_start / agent_end
- turn_start / turn_end
- message_start / message_update / message_end
- tool_execution_start / tool_execution_update / tool_execution_end

使用示例：
    event_bus = AgentEventBus()

    async def on_message_start(event: AgentEvent):
        print(f"Message started: {event.data}")

    event_bus.subscribe(AgentEventType.MESSAGE_START, on_message_start)

    # 在 ChatService 中
    await event_bus.publish(AgentEvent(
        type=AgentEventType.TURN_START,
        data={"user_message": "Hello"},
        timestamp=time.time()
    ))
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional


class AgentEventType(Enum):
    """Agent 事件类型"""

    # Agent 生命周期
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"

    # Turn 生命周期
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # Message 生命周期
    MESSAGE_START = "message_start"
    MESSAGE_UPDATE = "message_update"
    MESSAGE_END = "message_end"

    # Tool 执行生命周期
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_UPDATE = "tool_execution_update"
    TOOL_EXECUTION_END = "tool_execution_end"


@dataclass
class AgentEvent:
    """Agent 事件"""

    type: AgentEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __str__(self) -> str:
        return f"AgentEvent({self.type.value}, {self.data})"


# 订阅者回调类型
SubscriberCallback = Callable[[AgentEvent], Coroutine[Any, Any, None]]


class AgentEventBus:
    """
    Agent 事件发布-订阅总线

    支持：
    - 订阅特定事件类型
    - 发布事件（等待所有订阅者完成）
    - steering 队列（打断当前执行）
    - follow-up 队列（当前 turn 结束后处理）

    From pi's packages/agent/src/agent.ts event system.
    """

    def __init__(self) -> None:
        self._subscribers: dict[AgentEventType, list[SubscriberCallback]] = {}
        self._steering_queue: list[str] = []
        self._follow_up_queue: list[str] = []

    def subscribe(
        self,
        event_type: AgentEventType,
        callback: SubscriberCallback,
    ) -> Callable[[], None]:
        """
        订阅事件

        Args:
            event_type: 要订阅的事件类型
            callback: 异步回调函数

        Returns:
            取消订阅的函数
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        self._subscribers[event_type].append(callback)

        # 返回取消订阅函数
        def unsubscribe() -> None:
            if event_type in self._subscribers:
                with contextlib.suppress(ValueError):
                    self._subscribers[event_type].remove(callback)

        return unsubscribe

    async def publish(self, event: AgentEvent) -> None:
        """
        发布事件，等待所有订阅者完成

        Args:
            event: 要发布的事件
        """
        if event.type in self._subscribers:
            tasks = [callback(event) for callback in self._subscribers[event.type]]
            await asyncio.gather(*tasks, return_exceptions=True)

    def add_steering(self, message: str) -> None:
        """
        添加 steering 消息（打断当前执行）

        Args:
            message: 要注入的消息
        """
        self._steering_queue.append(message)

    def add_follow_up(self, message: str) -> None:
        """
        添加 follow-up 消息（当前 turn 结束后处理）

        Args:
            message: 要注入的消息
        """
        self._follow_up_queue.append(message)

    def get_steering(self) -> Optional[str]:
        """
        获取下一个 steering 消息

        Returns:
            下一个 steering 消息，或 None
        """
        if self._steering_queue:
            return self._steering_queue.pop(0)
        return None

    def get_follow_up(self) -> Optional[str]:
        """
        获取下一个 follow-up 消息

        Returns:
            下一个 follow-up 消息，或 None
        """
        if self._follow_up_queue:
            return self._follow_up_queue.pop(0)
        return None

    def clear_steering(self) -> None:
        """清空 steering 队列"""
        self._steering_queue.clear()

    def clear_follow_up(self) -> None:
        """清空 follow-up 队列"""
        self._follow_up_queue.clear()
