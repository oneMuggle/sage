"""R142 — AgentEventBus 发布-订阅总线单元测试。

覆盖：事件类型分类、AgentEvent 缺省与 __str__、订阅/取消（含重复取消
安全）、publish 等待全部订阅者、未订阅类型静默、steering/follow-up
队列 FIFO 与 clear、两队列互不干扰。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.domain.agent_events import AgentEvent, AgentEventBus, AgentEventType

pytestmark = pytest.mark.unit


def test_all_event_types_classified():
    values = {e.value for e in AgentEventType}
    assert len(values) == 10
    assert {v for v in values if v.startswith("agent_")} == {"agent_start", "agent_end"}
    assert {v for v in values if v.startswith("message_")} == {
        "message_start",
        "message_update",
        "message_end",
    }
    assert {v for v in values if v.startswith("tool_execution_")} == {
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
    }


def test_agent_event_defaults_and_str():
    event = AgentEvent(type=AgentEventType.TURN_START)
    assert event.data == {}
    assert isinstance(event.timestamp, float)
    assert event.timestamp <= time.time() + 1
    assert "turn_start" in str(event)


# ---------------------------------------------------------------------------
# subscribe / publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_subscribe_and_publish_invokes_all_subscribers():
    bus = AgentEventBus()
    seen_a, seen_b = [], []

    async def sub_a(event):
        seen_a.append(event)

    async def sub_b(event):
        seen_b.append(event)

    bus.subscribe(AgentEventType.MESSAGE_START, sub_a)
    bus.subscribe(AgentEventType.MESSAGE_START, sub_b)

    event = AgentEvent(type=AgentEventType.MESSAGE_START, data={"n": 1})
    await bus.publish(event)
    assert seen_a == [event]
    assert seen_b == [event]


@pytest.mark.asyncio()
async def test_publish_unsubscribed_type_is_silent():
    bus = AgentEventBus()
    await bus.publish(AgentEvent(type=AgentEventType.AGENT_END))  # 无订阅者，不抛错


@pytest.mark.asyncio()
async def test_unsubscribe_stops_delivery():
    bus = AgentEventBus()
    seen = []

    async def sub(event):
        seen.append(event)

    unsubscribe = bus.subscribe(AgentEventType.TURN_END, sub)
    unsubscribe()
    await bus.publish(AgentEvent(type=AgentEventType.TURN_END))
    assert seen == []


def test_unsubscribe_twice_is_safe():
    bus = AgentEventBus()

    async def sub(event):
        return None

    unsubscribe = bus.subscribe(AgentEventType.AGENT_START, sub)
    unsubscribe()
    unsubscribe()  # 重复取消不抛错
    assert bus._subscribers[AgentEventType.AGENT_START] == []


@pytest.mark.asyncio()
async def test_subscriber_exception_does_not_break_others():
    """gather(return_exceptions=True)：单个订阅者异常不阻断其他订阅者。"""
    bus = AgentEventBus()
    seen = []

    async def bad(_event):
        raise RuntimeError("subscriber boom")

    async def good(event):
        seen.append(event)

    bus.subscribe(AgentEventType.TURN_START, bad)
    bus.subscribe(AgentEventType.TURN_START, good)
    await bus.publish(AgentEvent(type=AgentEventType.TURN_START))
    assert len(seen) == 1  # good 仍收到事件


# ---------------------------------------------------------------------------
# steering / follow-up 队列
# ---------------------------------------------------------------------------


def test_steering_queue_fifo():
    bus = AgentEventBus()
    bus.add_steering("first")
    bus.add_steering("second")
    assert bus.get_steering() == "first"
    assert bus.get_steering() == "second"
    assert bus.get_steering() is None


def test_follow_up_queue_fifo_and_empty_none():
    bus = AgentEventBus()
    bus.add_follow_up("f1")
    assert bus.get_follow_up() == "f1"
    assert bus.get_follow_up() is None


def test_clear_steering_and_follow_up():
    bus = AgentEventBus()
    bus.add_steering("s")
    bus.add_follow_up("f")
    bus.clear_steering()
    bus.clear_follow_up()
    assert bus.get_steering() is None
    assert bus.get_follow_up() is None


def test_two_queues_independent():
    bus = AgentEventBus()
    bus.add_steering("s1")
    bus.add_follow_up("f1")
    assert bus.get_steering() == "s1"
    assert bus.get_follow_up() == "f1"  # 清 steering 不影响 follow-up


def test_asyncio_loop_reference_usable():
    # 冒烟：模块内 asyncio 引用可用（publish 的 gather 依赖）
    assert asyncio.iscoroutinefunction(AgentEventBus.publish)
