"""M3：定时任务自动执行字段（mode / last_result_message_id / last_duration_ms）。

覆盖方案 docs/plans/2026-11-06_scheduled-task-auto-execute.md §3.4-§3.6：

- 旧行读取（JSON ``from_dict`` / SQLite 旧表）默认 ``mode="deliver"``；
- ``database.py`` 迁移幂等：重复 ``init_db()`` 不报错，旧表自动补列；
- 仓储 / API / 工具三层的字段往返；
- pydantic 模型默认值与 ``Literal`` 校验（v1/v2 共用同一行为断言）。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


pytestmark = pytest.mark.unit

SESSION_A = "sess-alpha"


# ---------- dataclass from_dict / to_dict ----------


def _old_json_row(**overrides):
    """升级前写入 JSON 的旧行样本（无 M2 三字段）。"""
    row = {
        "id": "task-old0001",
        "name": "旧提醒",
        "type": "recurring",
        "schedule": {"kind": "recurring", "cron": "0 9 * * *"},
        "session_id": SESSION_A,
        "content": "旧任务内容",
        "enabled": True,
        "created_at": 1770000000000,
        "last_run": None,
        "next_run": 1770086400000,
        "last_attempt": None,
        "last_status": "never",
        "last_error": None,
        "run_count": 0,
        "max_runs": None,
    }
    row.update(overrides)
    return row


class TestScheduledTaskFromDict:
    def test_old_row_defaults_to_deliver(self) -> None:
        from backend.services.scheduler import ScheduledTask

        task = ScheduledTask.from_dict(_old_json_row())

        assert task.mode == "deliver"
        assert task.last_result_message_id is None
        assert task.last_duration_ms is None

    def test_execute_row_roundtrips(self) -> None:
        from backend.services.scheduler import ScheduledTask

        row = _old_json_row(
            mode="execute",
            last_result_message_id="msg-abc123",
            last_duration_ms=1234,
        )
        task = ScheduledTask.from_dict(row)

        assert task.mode == "execute"
        assert task.last_result_message_id == "msg-abc123"
        assert task.last_duration_ms == 1234
        assert task.to_dict() == row

    def test_invalid_stored_mode_falls_back_not_crashes(self) -> None:
        from backend.services.scheduler import ScheduledTask

        # 历史脏数据（手工编辑 JSON）不应让整个调度器启动失败。
        task = ScheduledTask.from_dict(_old_json_row(mode="bogus"))

        assert task.mode == "bogus"


# ---------- database.py 迁移幂等 ----------


def _table_columns(db, table: str = "scheduled_tasks") -> set:
    return {
        row["name"]
        for row in db.get_connection()
        .execute(f"PRAGMA table_info({table})")
        .fetchall()
    }


class TestScheduledTaskSchemaMigration:
    def test_fresh_db_has_m2_columns(self, tmp_path: Path) -> None:
        from backend.data.database import Database

        db = Database(str(tmp_path / "fresh.db"))
        try:
            db.init_db()
            cols = _table_columns(db)
        finally:
            db.close()

        assert {"mode", "last_result_message_id", "last_duration_ms"} <= cols

    def test_init_db_is_idempotent(self, tmp_path: Path) -> None:
        from backend.data.database import Database

        db = Database(str(tmp_path / "idem.db"))
        try:
            db.init_db()
            first = _table_columns(db)
            db.init_db()
            second = _table_columns(db)
        finally:
            db.close()

        assert first == second

    def test_old_table_gains_columns_and_existing_row_reads_deliver(
        self, tmp_path: Path
    ) -> None:
        from backend.data.database import Database

        path = tmp_path / "legacy.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE scheduled_tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('once', 'recurring')),
                schedule TEXT NOT NULL,
                session_id TEXT NOT NULL,
                content TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                last_run INTEGER,
                next_run INTEGER,
                last_attempt INTEGER,
                last_status TEXT NOT NULL DEFAULT 'never',
                last_error TEXT,
                run_count INTEGER NOT NULL DEFAULT 0,
                max_runs INTEGER
            );
            INSERT INTO scheduled_tasks
                (id, name, type, schedule, session_id, content, enabled,
                 created_at, last_status, run_count)
            VALUES
                ('task-legacy01', '升级前的任务', 'once',
                 '{"kind":"once","at":1770086400000}', 'sess-alpha',
                 '升级前内容', 1, 1770000000000, 'never', 0);
            """
        )
        conn.commit()
        conn.close()

        db = Database(str(path))
        try:
            db.init_db()
            row = db.get_connection().execute(
                "SELECT mode, last_result_message_id, last_duration_ms "
                "FROM scheduled_tasks WHERE id='task-legacy01'"
            ).fetchone()
        finally:
            db.close()

        assert row["mode"] == "deliver"
        assert row["last_result_message_id"] is None
        assert row["last_duration_ms"] is None


# ---------- 仓储层往返 ----------


class TestScheduledTaskRepositoryM2Fields:
    @pytest.fixture()
    def repo(self, tmp_path: Path):
        from backend.data.database import Database
        from backend.services.scheduler_repository import ScheduledTaskRepository

        db = Database(str(tmp_path / "repo.db"))
        db.init_db()
        yield ScheduledTaskRepository(db)
        db.close()

    def test_execute_fields_roundtrip(self, repo) -> None:
        row = _old_json_row(
            mode="execute",
            last_result_message_id="msg-xyz789",
            last_duration_ms=987,
        )

        repo.upsert(row)
        stored = repo.get(row["id"])

        assert stored["mode"] == "execute"
        assert stored["last_result_message_id"] == "msg-xyz789"
        assert stored["last_duration_ms"] == 987

    def test_dict_without_mode_encodes_as_deliver(self, repo) -> None:
        row = _old_json_row()
        row.pop("mode", None)

        repo.upsert(row)
        stored = repo.get(row["id"])

        assert stored["mode"] == "deliver"


# ---------- API 契约 ----------


def _api_client(scheduler) -> TestClient:
    from backend.api.scheduled_router import build_router

    app = FastAPI()
    app.include_router(build_router(lambda: scheduler), prefix="/api/v1")
    return TestClient(app)


@pytest.fixture()
def scheduler(tmp_path: Path):
    from backend.services.scheduler import SchedulerService

    message_repo = MagicMock()
    message_repo.insert = MagicMock(return_value={"id": "msg-1"})
    session_repo = MagicMock()
    session_repo.exists = MagicMock(return_value=True)
    return SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        message_repo=message_repo,
        session_repo=session_repo,
    )


def _create_payload(**overrides) -> dict:
    payload = {
        "name": "自动执行任务",
        "type": "recurring",
        "schedule": {"kind": "recurring", "cron": "*/5 * * * *"},
        "session_id": SESSION_A,
        "content": "检查部署状态并报告",
    }
    payload.update(overrides)
    return payload


class TestScheduledApiModeContract:
    def test_create_defaults_to_execute(self, scheduler) -> None:
        client = _api_client(scheduler)

        r = client.post("/api/v1/scheduled/tasks", json=_create_payload())

        assert r.status_code == 201
        body = r.json()
        assert body["mode"] == "execute"
        assert body["last_result_message_id"] is None
        assert body["last_duration_ms"] is None

    def test_create_explicit_deliver(self, scheduler) -> None:
        client = _api_client(scheduler)

        r = client.post(
            "/api/v1/scheduled/tasks", json=_create_payload(mode="deliver")
        )

        assert r.status_code == 201
        assert r.json()["mode"] == "deliver"

    def test_create_invalid_mode_is_422(self, scheduler) -> None:
        client = _api_client(scheduler)

        r = client.post(
            "/api/v1/scheduled/tasks", json=_create_payload(mode="immediate")
        )

        assert r.status_code == 422

    def test_list_returns_mode_fields(self, scheduler) -> None:
        client = _api_client(scheduler)
        client.post(
            "/api/v1/scheduled/tasks", json=_create_payload(mode="deliver")
        )

        body = client.get("/api/v1/scheduled/tasks").json()

        assert len(body) == 1
        assert body[0]["mode"] == "deliver"
        assert "last_result_message_id" in body[0]
        assert "last_duration_ms" in body[0]

    def test_patch_updates_mode(self, scheduler) -> None:
        client = _api_client(scheduler)
        task_id = client.post(
            "/api/v1/scheduled/tasks", json=_create_payload()
        ).json()["id"]

        r = client.patch(
            f"/api/v1/scheduled/tasks/{task_id}", json={"mode": "deliver"}
        )

        assert r.status_code == 200
        assert r.json()["mode"] == "deliver"
        assert scheduler.get_task(task_id).mode == "deliver"

    def test_task_out_defaults_to_deliver_for_old_payloads(self) -> None:
        """TaskOut 对缺失字段默认 deliver，保证旧客户端/旧行安全。"""
        from backend.api.scheduled_router import TaskOut

        out = TaskOut(
            id="task-old1",
            name="旧任务",
            type="once",
            schedule={"kind": "once", "at": 1770086400000},
            session_id=SESSION_A,
            content="旧内容",
            enabled=True,
            created_at=1770000000000,
        )

        assert out.mode == "deliver"
        assert out.last_result_message_id is None
        assert out.last_duration_ms is None

    def test_task_out_rejects_invalid_mode(self) -> None:
        from pydantic import ValidationError

        from backend.api.scheduled_router import TaskOut

        with pytest.raises(ValidationError):
            TaskOut(
                id="task-x",
                name="bad",
                type="once",
                schedule={"kind": "once", "at": 1770086400000},
                session_id=SESSION_A,
                content="x",
                enabled=True,
                created_at=1770000000000,
                mode="immediate",
            )


# ---------- LLM 工具透传 ----------


def _bind_session(session_id: str):
    from backend.tools.context import ToolExecutionContext, set_tool_context

    return set_tool_context(
        ToolExecutionContext(
            session_id=session_id,
            stream_id="stream-1",
            binding_generation=0,
            office_doc_scope=frozenset(),
        )
    )


def _future_iso(minutes: int = 30) -> str:
    return (datetime.now() + timedelta(minutes=minutes)).isoformat()


class TestScheduleToolMode:
    def test_default_mode_is_execute(self, scheduler) -> None:
        from backend.tools.context import reset_tool_context
        from backend.tools.schedule_tool import ScheduleTaskTool

        token = _bind_session(SESSION_A)
        try:
            result = ScheduleTaskTool(service_getter=lambda: scheduler).execute(
                name="默认模式",
                prompt="到点执行",
                schedule_kind="once",
                at=_future_iso(),
            )
        finally:
            reset_tool_context(token)

        assert result.success is True
        assert scheduler.list_tasks()[0].mode == "execute"
        assert result.content["mode"] == "execute"

    def test_explicit_deliver_is_passed_through(self, scheduler) -> None:
        from backend.tools.context import reset_tool_context
        from backend.tools.schedule_tool import ScheduleTaskTool

        token = _bind_session(SESSION_A)
        try:
            result = ScheduleTaskTool(service_getter=lambda: scheduler).execute(
                name="仅提醒",
                prompt="到点提醒",
                schedule_kind="once",
                at=_future_iso(),
                mode="deliver",
            )
        finally:
            reset_tool_context(token)

        assert result.success is True
        assert scheduler.list_tasks()[0].mode == "deliver"

    def test_invalid_mode_is_rejected(self, scheduler) -> None:
        from backend.tools.context import reset_tool_context
        from backend.tools.schedule_tool import ScheduleTaskTool

        token = _bind_session(SESSION_A)
        try:
            result = ScheduleTaskTool(service_getter=lambda: scheduler).execute(
                name="坏模式",
                prompt="x",
                schedule_kind="once",
                at=_future_iso(),
                mode="immediate",
            )
        finally:
            reset_tool_context(token)

        assert result.success is False
        assert "mode" in str(result.error)
        assert scheduler.list_tasks() == []

    def test_schema_exposes_mode_enum(self) -> None:
        from backend.tools.schedule_tool import ScheduleTaskTool

        schema = ScheduleTaskTool(service_getter=lambda: None)._build_schema()

        mode = schema.parameters["properties"]["mode"]
        assert mode["enum"] == ["execute", "deliver"]

    def test_list_tool_exposes_mode(self, scheduler) -> None:
        from backend.tools.context import reset_tool_context
        from backend.tools.schedule_tool import (
            ListScheduledTasksTool,
            ScheduleTaskTool,
        )

        token = _bind_session(SESSION_A)
        try:
            ScheduleTaskTool(service_getter=lambda: scheduler).execute(
                name="仅提醒",
                prompt="x",
                schedule_kind="once",
                at=_future_iso(),
                mode="deliver",
            )
            result = ListScheduledTasksTool(service_getter=lambda: scheduler).execute()
        finally:
            reset_tool_context(token)

        assert result.success is True
        assert result.content["tasks"][0]["mode"] == "deliver"
        assert "mode=deliver" in str(result.output)


# ---------- 服务层默认值与校验 ----------


class TestSchedulerServiceMode:
    def test_add_task_defaults_to_execute(self, scheduler) -> None:
        task = scheduler.add_task(
            name="服务默认",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 9 * * *"},
            session_id=SESSION_A,
            content="x",
        )
        assert task.mode == "execute"

    def test_add_task_rejects_invalid_mode(self, scheduler) -> None:
        from backend.services.scheduler import ValidationError

        with pytest.raises(ValidationError):
            scheduler.add_task(
                name="坏模式",
                task_type="recurring",
                schedule={"kind": "recurring", "cron": "0 9 * * *"},
                session_id=SESSION_A,
                content="x",
                mode="immediate",  # type: ignore[arg-type]
            )

    def test_update_task_switches_mode(self, scheduler) -> None:
        task = scheduler.add_task(
            name="切换模式",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 9 * * *"},
            session_id=SESSION_A,
            content="x",
        )

        updated = scheduler.update_task(task.id, mode="deliver")

        assert updated.mode == "deliver"
