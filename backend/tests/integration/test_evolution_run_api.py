"""R17-B: /scheduled/evolution 手动触发端点集成测试。

evolution job 注册在 APScheduler 的 "evolution/<name>" 下（不走 JSON 持久化的
用户任务表），这里用真实 SchedulerService + MagicMock 任务验证路由行为。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.scheduled_router import build_router
from backend.services.scheduler import SchedulerService


@pytest.fixture()
def scheduler(tmp_path: Path) -> SchedulerService:
    return SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        message_repo=MagicMock(),
        session_repo=MagicMock(),
    )


@pytest.fixture()
def client(scheduler: SchedulerService) -> TestClient:
    app = FastAPI()
    app.include_router(build_router(lambda: scheduler), prefix="/api/v1")
    return TestClient(app)


def _register(scheduler: SchedulerService, stats: dict | None = None) -> MagicMock:
    task = MagicMock()
    if stats is not None:
        task.run.return_value = stats
    scheduler.register_evolution_task(
        "memory_consolidation", task=task, cron_expr="30 4 * * 0"
    )
    return task


class TestEvolutionRunApi:
    def test_list_registered_tasks(self, scheduler: SchedulerService, client: TestClient) -> None:
        _register(scheduler)

        r = client.get("/api/v1/scheduled/evolution/tasks")
        assert r.status_code == 200
        assert r.json() == {
            "tasks": [
                {"name": "memory_consolidation", "job_id": "evolution/memory_consolidation"}
            ]
        }

    def test_run_returns_task_stats(
        self, scheduler: SchedulerService, client: TestClient
    ) -> None:
        task = _register(scheduler, {"promoted": 2, "decayed": 3, "total": 5})

        r = client.post("/api/v1/scheduled/evolution/memory_consolidation/run")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["result"] == {"promoted": 2, "decayed": 3, "total": 5}
        task.run.assert_called_once()

    def test_run_unknown_task_is_404(self, client: TestClient) -> None:
        r = client.post("/api/v1/scheduled/evolution/no_such_task/run")
        assert r.status_code == 404
        assert r.json()["detail"]["type"] == "task_not_found"

    def test_run_internal_failure_surfaces_ok_false(
        self, scheduler: SchedulerService, client: TestClient
    ) -> None:
        task = _register(scheduler)
        task.run.side_effect = RuntimeError("memory manager missing")

        r = client.post("/api/v1/scheduled/evolution/memory_consolidation/run")
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert r.json()["result"] == {}

    def test_scheduler_uninitialised_is_503(self) -> None:
        app = FastAPI()
        app.include_router(build_router(lambda: None), prefix="/api/v1")
        client = TestClient(app)

        assert client.get("/api/v1/scheduled/evolution/tasks").status_code == 503
        assert client.post("/api/v1/scheduled/evolution/memory_consolidation/run").status_code == 503
