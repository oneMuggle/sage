"""
Agent 事件系统测试 (A23 from pi)

测试 Agent 事件发布-订阅架构。
"""


import pytest

from backend.domain.agent_events import AgentEvent, AgentEventBus, AgentEventType


class TestAgentEventBus:
    """AgentEventBus 测试套件"""

    @pytest.mark.asyncio()
    async def test_subscribe_and_publish(self):
        """订阅和发布事件"""
        bus = AgentEventBus()
        received_events = []

        async def on_event(event: AgentEvent):
            received_events.append(event)

        bus.subscribe(AgentEventType.MESSAGE_START, on_event)

        event = AgentEvent(
            type=AgentEventType.MESSAGE_START,
            data={"content": "Hello"}
        )
        await bus.publish(event)

        assert len(received_events) == 1
        assert received_events[0].type == AgentEventType.MESSAGE_START
        assert received_events[0].data["content"] == "Hello"

    @pytest.mark.asyncio()
    async def test_multiple_subscribers(self):
        """多个订阅者"""
        bus = AgentEventBus()
        count = 0

        async def subscriber1(event: AgentEvent):
            nonlocal count
            count += 1

        async def subscriber2(event: AgentEvent):
            nonlocal count
            count += 1

        bus.subscribe(AgentEventType.TURN_START, subscriber1)
        bus.subscribe(AgentEventType.TURN_START, subscriber2)

        await bus.publish(AgentEvent(type=AgentEventType.TURN_START))

        assert count == 2

    @pytest.mark.asyncio()
    async def test_unsubscribe(self):
        """取消订阅"""
        bus = AgentEventBus()
        received = []

        async def on_event(event: AgentEvent):
            received.append(event)

        unsubscribe = bus.subscribe(AgentEventType.AGENT_START, on_event)

        await bus.publish(AgentEvent(type=AgentEventType.AGENT_START))
        assert len(received) == 1

        unsubscribe()
        await bus.publish(AgentEvent(type=AgentEventType.AGENT_START))
        assert len(received) == 1  # 不再接收

    @pytest.mark.asyncio()
    async def test_different_event_types(self):
        """不同事件类型"""
        bus = AgentEventBus()
        events = []

        async def on_turn_start(event: AgentEvent):
            events.append("turn_start")

        async def on_message_start(event: AgentEvent):
            events.append("message_start")

        bus.subscribe(AgentEventType.TURN_START, on_turn_start)
        bus.subscribe(AgentEventType.MESSAGE_START, on_message_start)

        await bus.publish(AgentEvent(type=AgentEventType.TURN_START))
        await bus.publish(AgentEvent(type=AgentEventType.MESSAGE_START))

        assert events == ["turn_start", "message_start"]

    def test_steering_queue(self):
        """steering 队列"""
        bus = AgentEventBus()

        assert bus.get_steering() is None

        bus.add_steering("Stop")
        assert bus.get_steering() == "Stop"
        assert bus.get_steering() is None

    def test_follow_up_queue(self):
        """follow-up 队列"""
        bus = AgentEventBus()

        assert bus.get_follow_up() is None

        bus.add_follow_up("Continue")
        assert bus.get_follow_up() == "Continue"
        assert bus.get_follow_up() is None

    def test_clear_queues(self):
        """清空队列"""
        bus = AgentEventBus()

        bus.add_steering("Stop")
        bus.add_follow_up("Continue")

        bus.clear_steering()
        bus.clear_follow_up()

        assert bus.get_steering() is None
        assert bus.get_follow_up() is None

    def test_event_str(self):
        """事件字符串表示"""
        event = AgentEvent(
            type=AgentEventType.MESSAGE_START,
            data={"content": "Hello"}
        )
        assert "message_start" in str(event)
        assert "Hello" in str(event)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
