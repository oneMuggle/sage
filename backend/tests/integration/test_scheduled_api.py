"""Integration tests for scheduled_router against an in-process FastAPI app."""
from __future__ import annotations

import time
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


class TestScheduledAuditContracts:
    @staticmethod
    def payload(**overrides):
        return dict(name="Audit", type="recurring", schedule={"kind": "recurring", "cron": "0 8 * * *"}, session_id="s-1", content="before", **overrides)

    def test_disabled_creation_has_no_job(self, client, scheduler):
        response = client.post("/api/v1/scheduled/tasks", json=self.payload(enabled=False))
        assert response.status_code == 201
        task = response.json()
        assert task["enabled"] is False
        assert task["next_run"] is None
        assert scheduler._scheduler.get_job(task["id"]) is None

    def test_full_edit_persists_and_reschedules(self, client, scheduler):
        created = client.post("/api/v1/scheduled/tasks", json=self.payload()).json()
        at = int(time.time() * 1000) + 120000
        updates = {"name": "Changed", "type": "once", "schedule": {"kind": "once", "at": at}, "content": "after", "session_id": "s-2", "enabled": True}
        response = client.patch("/api/v1/scheduled/tasks/" + created["id"], json=updates)
        assert response.status_code == 200, response.text
        saved = client.get("/api/v1/scheduled/tasks").json()[0]
        for key, value in updates.items():
            if key == "schedule":
                assert saved[key]["kind"] == "once"
                assert saved[key]["at"] == at
            else:
                assert saved[key] == value
        assert saved["next_run"] == at
        assert scheduler._scheduler.get_job(created["id"]).args[0].content == "after"

    def test_mismatched_type_is_422_not_500(self, client):
        payload = self.payload()
        payload["type"] = "once"
        assert client.post("/api/v1/scheduled/tasks", json=payload).status_code == 422
        created = client.post("/api/v1/scheduled/tasks", json=self.payload()).json()
        response = client.patch("/api/v1/scheduled/tasks/" + created["id"], json={"type": "once"})
        assert response.status_code == 422
        assert client.get("/api/v1/scheduled/tasks").json()[0]["type"] == "recurring"

    def test_invalid_session_is_rejected_on_create_and_edit(self, client, session_repo):
        created = client.post("/api/v1/scheduled/tasks", json=self.payload()).json()
        session_repo.exists.return_value = False
        assert client.post("/api/v1/scheduled/tasks", json=self.payload()).status_code == 422
        assert client.patch("/api/v1/scheduled/tasks/" + created["id"], json={"session_id": "gone"}).status_code == 422

    def test_failed_once_is_visible_persistent_and_manually_retryable(self, client, scheduler, message_repo, session_repo):
        payload = self.payload()
        payload.update(type="once", schedule={"kind": "once", "at": int(time.time() * 1000) + 60000})
        created = client.post("/api/v1/scheduled/tasks", json=payload).json()
        message_repo.insert.side_effect = RuntimeError("temporary DB failure")
        failed = client.post("/api/v1/scheduled/tasks/" + created["id"] + "/run").json()
        assert failed["last_status"] == "failed"
        assert failed["last_attempt"] is not None
        assert failed["last_run"] is None
        assert failed["last_error"]
        assert failed["enabled"] is False
        restarted = SchedulerService(scheduler._store_path, message_repo, session_repo)
        assert restarted.get_task(created["id"]).last_status == "failed"
        assert restarted._scheduler.get_job(created["id"]) is None
        message_repo.insert.side_effect = None
        succeeded = client.post("/api/v1/scheduled/tasks/" + created["id"] + "/run").json()
        assert succeeded["last_status"] == "succeeded"
        assert succeeded["last_run"] is not None
        assert succeeded["last_error"] is None

    def test_missing_session_records_failure_not_success(self, client, session_repo, message_repo):
        created = client.post("/api/v1/scheduled/tasks", json=self.payload()).json()
        session_repo.exists.return_value = False
        result = client.post("/api/v1/scheduled/tasks/" + created["id"] + "/run").json()
        assert result["last_status"] == "failed"
        assert result["last_run"] is None
        message_repo.insert.assert_not_called()

    def test_queued_old_schedule_does_not_fire_new_schedule_early(self, scheduler, message_repo):
        task = scheduler.add_task("Audit", "recurring", {"kind": "recurring", "cron": "0 8 * * *"}, "s", "x")
        scheduler.update_task(task.id, schedule={"kind": "recurring", "cron": "0 9 * * *"})
        scheduler._fire_scheduled(task)
        message_repo.insert.assert_not_called()

    def test_overlapping_manual_attempt_is_rejected(self, scheduler, message_repo):
        from backend.services.scheduler import ValidationError
        task = scheduler.add_task("Audit", "recurring", {"kind": "recurring", "cron": "0 8 * * *"}, "s", "x")
        def during_insert(**kwargs):
            with pytest.raises(ValidationError, match="already running"):
                scheduler.run_now(task.id)
            with pytest.raises(ValidationError, match="task is running"):
                scheduler.update_task(task.id, content="race")
        message_repo.insert.side_effect = during_insert
        scheduler.run_now(task.id)
        assert message_repo.insert.call_count == 1

    def test_edit_paused_past_once_without_changing_schedule(self, scheduler):
        task = scheduler.add_task("Audit", "once", {"kind": "once", "at": int(time.time() * 1000) + 60000}, "s", "x", enabled=False)
        task.schedule["at"] = 1
        changed = scheduler.update_task(task.id, name="Renamed", content="new")
        assert changed.name == "Renamed"
        assert changed.next_run is None
        from backend.services.scheduler import ValidationError
        with pytest.raises(ValidationError, match="future"):
            scheduler.update_task(task.id, enabled=True)

    def test_unknown_fields_are_rejected(self, client):
        created = client.post("/api/v1/scheduled/tasks", json=self.payload()).json()
        assert client.patch("/api/v1/scheduled/tasks/" + created["id"], json={"unimplemented": True}).status_code == 422
