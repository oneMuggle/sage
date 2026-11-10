"""pending 通知端点包含 goal_notifications 键的回归测试。"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import backend.services.scheduler as scheduler_mod
from backend.domain.autonomous_goals import Goal, GoalStatus
from backend.main import app
from backend.services.goal_notifications import (
    get_goal_notification_queue,
    reset_goal_notification_queue,
)
from backend.services.scheduler import SchedulerService


@pytest.fixture(autouse=True)
def scheduler(monkeypatch, tmp_path):
    """路由依赖进程级 SchedulerService；测试期注入一个隔离实例。

    ``backend/api/scheduled_router.py`` 在 import 时就捕获了
    ``backend.services.scheduler.get_scheduler_service`` 函数对象，该函数在
    调用时读取模块全局 ``_global_service``，因此 monkeypatch 该全局即可生效。
    """
    svc = SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        message_repo=MagicMock(),
        session_repo=MagicMock(),
    )
    monkeypatch.setattr(scheduler_mod, "_global_service", svc)
    return svc


@pytest.fixture(autouse=True)
def _clean_queue():
    """每个用例前后清空进程级目标通知单例，避免用例间串味。"""
    reset_goal_notification_queue()
    yield
    reset_goal_notification_queue()


def test_pending_notifications_includes_goal_key():
    client = TestClient(app)
    resp = client.get("/api/v1/scheduled/notifications/pending")
    assert resp.status_code == 200
    body = resp.json()
    assert "goal_notifications" in body
    assert isinstance(body["goal_notifications"], list)
    # 既有三键语义不变
    assert "scheduled_tasks" in body
    assert "todo_reminders" in body
    assert "background_tasks" in body


def test_pending_notifications_drains_goal_notifications():
    """队列里的目标终态通知经端点排空并原样返回。"""
    get_goal_notification_queue().push(
        Goal(id="g-route-1", name="路由目标", description="", status=GoalStatus.COMPLETED)
    )

    client = TestClient(app)
    resp = client.get("/api/v1/scheduled/notifications/pending")
    assert resp.status_code == 200
    items = resp.json()["goal_notifications"]
    assert len(items) == 1
    assert items[0]["goal_id"] == "g-route-1"
    assert items[0]["status"] == "succeeded"

    # 端点是排空语义：第二次拉取为空
    resp2 = client.get("/api/v1/scheduled/notifications/pending")
    assert resp2.json()["goal_notifications"] == []
