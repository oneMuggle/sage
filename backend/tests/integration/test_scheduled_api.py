"""Integration tests for scheduled_router against an in-process FastAPI app."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.scheduled_router import build_router
from backend.services.scheduler import SchedulerService


@pytest.fixture()
def message_repo() -> MagicMock:
    repo = MagicMock()
    repo.insert = MagicMock(return_value={"id": "msg-1"})
    return repo


@pytest.fixture()
def session_repo() -> MagicMock:
    repo = MagicMock()
    repo.exists = MagicMock(return_value=True)
    return repo


@pytest.fixture()
def scheduler(tmp_path: Path, message_repo: MagicMock, session_repo: MagicMock) -> SchedulerService:
    return SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        message_repo=message_repo,
        session_repo=session_repo,
    )


@pytest.fixture()
def client(scheduler: SchedulerService) -> TestClient:
    app = FastAPI()
    app.include_router(build_router(lambda: scheduler), prefix="/api/v1")
    return TestClient(app)


class TestScheduledApi:
    def test_health_ok(self, client: TestClient) -> None:
        r = client.get("/api/v1/scheduled/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_list_starts_empty(self, client: TestClient) -> None:
        r = client.get("/api/v1/scheduled/tasks")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_recurring_task(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Daily brief",
                "type": "recurring",
                "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                "session_id": "s-1",
                "content": "good morning",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "Daily brief"
        assert body["enabled"] is True
        assert body["id"].startswith("task-")

    def test_create_rejects_bad_cron(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Bad",
                "type": "recurring",
                "schedule": {"kind": "recurring", "cron": "not a cron"},
                "session_id": "s-1",
                "content": "x",
            },
        )
        assert r.status_code == 422
        assert "cron" in r.text.lower()

    def test_create_one_shot_in_past_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Past",
                "type": "once",
                "schedule": {"kind": "once", "at": 1},
                "session_id": "s-1",
                "content": "x",
            },
        )
        assert r.status_code == 422

    def test_update_task(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Old",
                "type": "recurring",
                "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                "session_id": "s-1",
                "content": "x",
            },
        ).json()
        r = client.patch(
            f"/api/v1/scheduled/tasks/{created['id']}",
            json={"name": "New", "enabled": False},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "New"
        assert r.json()["enabled"] is False

    def test_update_missing_returns_404(self, client: TestClient) -> None:
        r = client.patch(
            "/api/v1/scheduled/tasks/task-missing",
            json={"name": "x"},
        )
        assert r.status_code == 404

    def test_delete_task(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Temp",
                "type": "recurring",
                "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                "session_id": "s-1",
                "content": "x",
            },
        ).json()
        r = client.delete(f"/api/v1/scheduled/tasks/{created['id']}")
        assert r.status_code == 204
        assert client.get("/api/v1/scheduled/tasks").json() == []

    def test_delete_missing_returns_404(self, client: TestClient) -> None:
        r = client.delete("/api/v1/scheduled/tasks/task-missing")
        assert r.status_code == 404

    def test_run_now_inserts_message(self, client: TestClient, message_repo: MagicMock) -> None:
        created = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Manual",
                "type": "recurring",
                "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                "session_id": "s-1",
                "content": "go",
            },
        ).json()
        r = client.post(f"/api/v1/scheduled/tasks/{created['id']}/run")
        assert r.status_code == 200
        message_repo.insert.assert_called_once()
