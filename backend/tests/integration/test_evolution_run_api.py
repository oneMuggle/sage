"""R17-B: /scheduled/evolution 手动触发端点集成测试（异步契约）。

evolution job 注册在 APScheduler 的 "evolution/<name>" 下（不走 JSON 持久化的
用户任务表），这里用真实 SchedulerService + MagicMock 任务验证路由行为。

2026-11-26 起触发改为异步：POST 立即返回 202 + running 快照，
进度与终态经 GET /scheduled/evolution/tasks 的 ``run`` 字段轮询。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.scheduled_router import build_router
from backend.scheduler.evolution_run_registry import get_evolution_run_registry
from backend.services.scheduler import SchedulerService


@pytest.fixture(autouse=True)
def _reset_run_registry() -> None:
    registry = get_evolution_run_registry()
    registry.reset()
    yield
    registry.reset()


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


def _register(scheduler: SchedulerService, stats: object = None) -> MagicMock:
    task = MagicMock()
    if stats is not None:
        task.run.return_value = stats
    scheduler.register_evolution_task(
        "memory_consolidation", task=task, cron_expr="30 4 * * 0"
    )
    return task


def _run_snapshot(client: TestClient, name: str) -> dict:
    tasks = client.get("/api/v1/scheduled/evolution/tasks").json()["tasks"]
    entry = next(t for t in tasks if t["name"] == name)
    return entry["run"]


def _wait_for_state(client: TestClient, name: str, state: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = _run_snapshot(client, name)
        if last is not None and last.get("state") == state:
            return last
        time.sleep(0.02)
    raise AssertionError(f"run for {name} did not reach {state}, last={last}")


class TestEvolutionRunApi:
    def test_list_registered_tasks(self, scheduler: SchedulerService, client: TestClient) -> None:
        _register(scheduler)

        r = client.get("/api/v1/scheduled/evolution/tasks")
        assert r.status_code == 200
        assert r.json() == {
            "tasks": [
                {
                    "name": "memory_consolidation",
                    "job_id": "evolution/memory_consolidation",
                    "run": None,
                }
            ]
        }

    def test_run_returns_202_with_running_snapshot(
        self, scheduler: SchedulerService, client: TestClient
    ) -> None:
        gate = threading.Event()
        task = _register(scheduler)

        def _blocked_run() -> dict:
            assert gate.wait(5), "test task was never released"
            return {"promoted": 2, "decayed": 3, "total": 5}

        task.run.side_effect = _blocked_run

        r = client.post("/api/v1/scheduled/evolution/memory_consolidation/run")
        assert r.status_code == 202
        body = r.json()
        assert body["ok"] is True
        assert body["started"] is True
        assert body["run"]["state"] == "running"
        assert body["run"]["trigger"] == "manual"

        # 运行中：GET 也能看到 running 快照（切页后重入恢复的依据）
        snapshot = _run_snapshot(client, "memory_consolidation")
        assert snapshot["state"] == "running"
        assert snapshot["run_id"] == body["run"]["run_id"]

        gate.set()
        finished = _wait_for_state(client, "memory_consolidation", "succeeded")
        assert finished["result"] == {"promoted": 2, "decayed": 3, "total": 5}
        assert finished["duration_ms"] is not None

    def test_second_run_while_running_attaches(
        self, scheduler: SchedulerService, client: TestClient
    ) -> None:
        gate = threading.Event()
        task = _register(scheduler)
        task.run.side_effect = lambda: (gate.wait(5), {"total": 1})[1]

        first = client.post("/api/v1/scheduled/evolution/memory_consolidation/run").json()
        second = client.post("/api/v1/scheduled/evolution/memory_consolidation/run").json()

        assert first["started"] is True
        assert second["started"] is False
        assert second["run"]["run_id"] == first["run"]["run_id"]
        assert task.run.call_count == 1

        gate.set()
        _wait_for_state(client, "memory_consolidation", "succeeded")

    def test_run_wraps_scalar_result_as_total(
        self, scheduler: SchedulerService, client: TestClient
    ) -> None:
        _register(scheduler, 4)

        r = client.post("/api/v1/scheduled/evolution/memory_consolidation/run")
        assert r.status_code == 202

        finished = _wait_for_state(client, "memory_consolidation", "succeeded")
        assert finished["result"] == {"total": 4}

    def test_cancel_running_task_sets_flag(
        self, scheduler: SchedulerService, client: TestClient
    ) -> None:
        gate = threading.Event()
        task = _register(scheduler)
        task.run.side_effect = lambda: (gate.wait(5), {"total": 1})[1]

        client.post("/api/v1/scheduled/evolution/memory_consolidation/run")
        r = client.post("/api/v1/scheduled/evolution/memory_consolidation/cancel")

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["cancelled"] is True
        assert body["run"]["cancel_requested"] is True

        gate.set()
        _wait_for_state(client, "memory_consolidation", "succeeded")

    def test_cancel_when_not_running_is_noop(
        self, scheduler: SchedulerService, client: TestClient
    ) -> None:
        _register(scheduler)

        r = client.post("/api/v1/scheduled/evolution/memory_consolidation/cancel")

        assert r.status_code == 200
        body = r.json()
        assert body["cancelled"] is False
        assert body["run"] is None

    def test_cancel_unknown_task_is_404(self, client: TestClient) -> None:
        r = client.post("/api/v1/scheduled/evolution/no_such_task/cancel")
        assert r.status_code == 404
        assert r.json()["detail"]["type"] == "task_not_found"

    def test_run_unknown_task_is_404(self, client: TestClient) -> None:
        r = client.post("/api/v1/scheduled/evolution/no_such_task/run")
        assert r.status_code == 404
        assert r.json()["detail"]["type"] == "task_not_found"

    def test_run_internal_failure_marks_failed(
        self, scheduler: SchedulerService, client: TestClient
    ) -> None:
        task = _register(scheduler)
        task.run.side_effect = RuntimeError("memory manager missing")

        r = client.post("/api/v1/scheduled/evolution/memory_consolidation/run")
        assert r.status_code == 202

        failed = _wait_for_state(client, "memory_consolidation", "failed")
        assert "memory manager missing" in (failed["error"] or "")

    def test_scheduler_uninitialised_is_503(self) -> None:
        app = FastAPI()
        app.include_router(build_router(lambda: None), prefix="/api/v1")
        client = TestClient(app)

        assert client.get("/api/v1/scheduled/evolution/tasks").status_code == 503
        assert client.post("/api/v1/scheduled/evolution/memory_consolidation/run").status_code == 503
