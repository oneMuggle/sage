"""``BackgroundNotificationQueue`` 单元测试（2026-11-06 Phase 1）。"""

from __future__ import annotations

import pytest

from backend.services.background_notifications import (
    BackgroundNotificationQueue,
    get_background_notification_queue,
)

pytestmark = pytest.mark.unit


class TestBackgroundNotificationQueue:
    def test_push_then_drain_returns_all(self) -> None:
        q = BackgroundNotificationQueue()
        q.push(shell_id="sh-1", command="sleep 5", exit_code=0, session_id="s-1")
        q.push(shell_id="sh-2", command="pytest -q", exit_code=1)
        items = q.drain()
        assert [i["shell_id"] for i in items] == ["sh-1", "sh-2"]
        assert items[0]["status"] == "succeeded"
        assert items[0]["title"].startswith("✅")
        assert items[0]["exit_code"] == 0
        assert items[0]["session_id"] == "s-1"
        assert items[1]["status"] == "failed"
        assert items[1]["title"].startswith("❌")
        assert items[1]["exit_code"] == 1
        assert items[1]["session_id"] == ""

    def test_drain_is_atomic(self) -> None:
        q = BackgroundNotificationQueue()
        q.push("sh-1", "cmd", 0)
        assert len(q.drain()) == 1
        assert q.drain() == []

    def test_empty_command_falls_back_to_shell_id(self) -> None:
        q = BackgroundNotificationQueue()
        q.push("sh-empty", "", 0)
        item = q.drain()[0]
        assert "sh-empty" in item["title"]

    def test_newlines_in_command_are_collapsed(self) -> None:
        q = BackgroundNotificationQueue()
        q.push("sh-nl", "echo\nfoo\nbar", 2)
        title = q.drain()[0]["title"]
        assert "\n" not in title

    def test_bounded_queue_drops_oldest(self) -> None:
        q = BackgroundNotificationQueue(maxlen=3)
        for i in range(5):
            q.push(f"sh-{i}", f"cmd-{i}", 0)
        items = q.drain()
        assert [i["shell_id"] for i in items] == ["sh-2", "sh-3", "sh-4"]

    def test_singleton_factory_returns_same_instance(self) -> None:
        a = get_background_notification_queue()
        b = get_background_notification_queue()
        assert a is b


class TestEvolutionNotifications:
    """2026-11-26 P1: 手动触发的进化任务终态通知。"""

    def test_push_evolution_success_item_shape(self) -> None:
        q = BackgroundNotificationQueue()
        q.push_evolution("memory_reflection", "记忆整理", "succeeded", "deduped: 2")
        item = q.drain()[0]
        assert item["kind"] == "evolution_task"
        assert item["task_name"] == "memory_reflection"
        assert item["status"] == "succeeded"
        assert item["title"] == "✅ 记忆整理完成"
        assert item["body"] == "deduped: 2"
        assert item["created_at"]

    def test_push_evolution_cancelled_and_failed_titles(self) -> None:
        q = BackgroundNotificationQueue()
        q.push_evolution("memory_reflection", "记忆整理", "cancelled", "")
        q.push_evolution("memory_pruning", "记忆修剪", "failed", "boom")
        items = q.drain()
        assert items[0]["title"] == "⏹ 记忆整理已取消"
        assert items[1]["title"] == "❌ 记忆修剪失败"
        assert items[1]["body"] == "boom"

    def test_push_evolution_truncates_body(self) -> None:
        q = BackgroundNotificationQueue()
        q.push_evolution("memory_pruning", "记忆修剪", "succeeded", "x" * 500)
        assert len(q.drain()[0]["body"]) == 200
