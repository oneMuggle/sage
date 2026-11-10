"""目标完成/失败通知队列的单元测试。"""

from backend.domain.autonomous_goals import Goal, GoalStatus
from backend.services.goal_notifications import (
    GoalNotificationQueue,
    get_goal_notification_queue,
    reset_goal_notification_queue,
)


def _goal(status: GoalStatus, name: str = "整理文献", error=None) -> Goal:
    return Goal(id="g1", name=name, description="", status=status, last_error=error)


def test_completed_goal_pushes_success_title():
    queue = GoalNotificationQueue()
    queue.push(_goal(GoalStatus.COMPLETED))
    items = queue.drain()
    assert len(items) == 1
    assert items[0]["kind"] == "goal"
    assert items[0]["status"] == "succeeded"
    assert "整理文献" in items[0]["title"]
    assert items[0]["title"].startswith("✅")


def test_failed_goal_pushes_failure_title_with_error():
    queue = GoalNotificationQueue()
    queue.push(_goal(GoalStatus.FAILED, error="模型超时"))
    items = queue.drain()
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["title"].startswith("❌")
    assert items[0]["body"] == "模型超时"


def test_non_terminal_status_is_ignored():
    queue = GoalNotificationQueue()
    for status in (GoalStatus.PENDING, GoalStatus.RUNNING, GoalStatus.PAUSED):
        queue.push(_goal(status))
    assert queue.drain() == []


def test_drain_empties_queue():
    queue = GoalNotificationQueue()
    queue.push(_goal(GoalStatus.COMPLETED))
    queue.drain()
    assert queue.drain() == []


def test_singleton_is_resettable():
    first = get_goal_notification_queue()
    first.push(_goal(GoalStatus.COMPLETED))
    reset_goal_notification_queue()
    second = get_goal_notification_queue()
    assert second is not first
    assert second.drain() == []
