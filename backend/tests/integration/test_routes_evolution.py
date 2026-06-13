"""
进化系统 API 集成测试 — 覆盖 /evolution/logs, /evolution/trigger, /evolution/status。
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.data.database import get_database

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_evolution_logs_empty(client):
    """空库上 /evolution/logs 返回空列表。"""
    resp = await client.get(f"{PREFIX}/evolution/logs")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_evolution_logs_returns_inserted(client):
    """插入 evolution_log 后 /evolution/logs 能查到。"""

    db = get_database()
    now = int(1.7e12)
    db.get_connection().execute(
        """
        INSERT INTO evolution_log
        (id, evolution_type, description, trigger_type, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("ev-001", "memory_pruning", "pruned 10 memories", "manual", "completed", now),
    )
    db.get_connection().commit()

    resp = await client.get(f"{PREFIX}/evolution/logs")
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) >= 1
    assert any(log["id"] == "ev-001" for log in logs)


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_evolution_status_with_mock_scheduler(client):
    """GET /evolution/status 返回调度器任务列表。"""
    mock_scheduler = MagicMock()
    mock_scheduler.get_task_status.return_value = [
        {
            "name": "daily_summary",
            "schedule": "daily",
            "last_run": None,
            "next_run": None,
            "running": False,
        },
        {
            "name": "memory_pruning",
            "schedule": "weekly",
            "last_run": None,
            "next_run": None,
            "running": False,
        },
    ]

    with patch("backend.api.legacy_routes.get_scheduler", return_value=mock_scheduler):
        resp = await client.get(f"{PREFIX}/evolution/status")

    assert resp.status_code == 200
    statuses = resp.json()
    assert len(statuses) == 2
    assert statuses[0]["name"] == "daily_summary"
    assert statuses[1]["name"] == "memory_pruning"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_evolution_status_empty(client):
    """无任务时 /evolution/status 返回空数组。"""
    mock_scheduler = MagicMock()
    mock_scheduler.get_task_status.return_value = []

    with patch("backend.api.legacy_routes.get_scheduler", return_value=mock_scheduler):
        resp = await client.get(f"{PREFIX}/evolution/status")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_evolution_trigger_success(client):
    """POST /evolution/trigger 任务存在时返回 success=True。"""
    mock_scheduler = MagicMock()
    mock_scheduler.get_task_status.return_value = [
        {
            "name": "daily_summary",
            "schedule": "daily",
            "last_run": None,
            "next_run": None,
            "running": False,
        },
    ]
    mock_scheduler.trigger_task.return_value = True

    with patch("backend.api.legacy_routes.get_scheduler", return_value=mock_scheduler):
        resp = await client.post(
            f"{PREFIX}/evolution/trigger",
            json={"task_name": "daily_summary"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "daily_summary" in body["message"]
    mock_scheduler.trigger_task.assert_called_once_with("daily_summary")


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_evolution_trigger_task_not_found(client):
    """POST /evolution/trigger 任务不存在时返回 404。"""
    mock_scheduler = MagicMock()
    mock_scheduler.get_task_status.return_value = [
        {
            "name": "daily_summary",
            "schedule": "daily",
            "last_run": None,
            "next_run": None,
            "running": False,
        },
    ]

    with patch("backend.api.legacy_routes.get_scheduler", return_value=mock_scheduler):
        resp = await client.post(
            f"{PREFIX}/evolution/trigger",
            json={"task_name": "nonexistent_task"},
        )

    assert resp.status_code == 404
    assert "nonexistent_task" in resp.json()["detail"]


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_evolution_trigger_failure(client):
    """POST /evolution/trigger trigger_task 返回 False 时 success=False。"""
    mock_scheduler = MagicMock()
    mock_scheduler.get_task_status.return_value = [
        {
            "name": "daily_summary",
            "schedule": "daily",
            "last_run": None,
            "next_run": None,
            "running": False,
        },
    ]
    mock_scheduler.trigger_task.return_value = False

    with patch("backend.api.legacy_routes.get_scheduler", return_value=mock_scheduler):
        resp = await client.post(
            f"{PREFIX}/evolution/trigger",
            json={"task_name": "daily_summary"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "触发失败" in body["message"]
