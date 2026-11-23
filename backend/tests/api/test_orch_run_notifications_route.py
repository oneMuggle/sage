"""pending 通知端点包含 orch_runs 键的回归测试（M4.3a）。"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import backend.services.scheduler as scheduler_mod
from backend.main import app
from backend.services.orch_run_notifications import (
    get_orch_run_notification_queue,
)
from backend.services.scheduler import SchedulerService


@pytest.fixture(autouse=True)
def scheduler(monkeypatch, tmp_path):
    """路由依赖进程级 SchedulerService；测试期注入一个隔离实例。

    与 ``test_goal_notifications_route.py`` 同构：monkeypatch 模块全局即可生效。
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
    """每个用例前后清空进程级编排通知单例，避免用例间串味。"""
    queue = get_orch_run_notification_queue()
    queue.drain()
    yield
    queue.drain()


def test_pending_notifications_includes_orch_runs_key():
    client = TestClient(app)
    resp = client.get("/api/v1/scheduled/notifications/pending")
    assert resp.status_code == 200
    body = resp.json()
    assert "orch_runs" in body
    assert isinstance(body["orch_runs"], list)
    # 既有五键语义不变
    for key in (
        "scheduled_tasks",
        "todo_reminders",
        "background_tasks",
        "goal_notifications",
        "project_health",
    ):
        assert key in body


def test_pending_notifications_drains_orch_run_notifications():
    """队列里的编排终态通知经端点排空并原样返回（含深链锚点）。"""
    get_orch_run_notification_queue().push(
        "orch-route-1",
        "completed",
        session_id="s-42",
        task_id="task-7",
        body="3 个任务完成",
    )

    client = TestClient(app)
    resp = client.get("/api/v1/scheduled/notifications/pending")
    assert resp.status_code == 200
    items = resp.json()["orch_runs"]
    assert len(items) == 1
    assert items[0]["kind"] == "orch_run_completed"
    assert items[0]["run_id"] == "orch-route-1"
    assert items[0]["session_id"] == "s-42"
    assert items[0]["task_id"] == "task-7"

    # 端点是排空语义：第二次拉取为空
    resp2 = client.get("/api/v1/scheduled/notifications/pending")
    assert resp2.json()["orch_runs"] == []
