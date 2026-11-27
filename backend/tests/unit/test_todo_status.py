"""P0 — 待办状态：词表 / 三态循环 / completed_at 副作用。

覆盖三层：
1. ``todo_status`` 纯函数（三态循环、完成时间戳规则）；
2. ``TodoService.update_todo`` 的状态副作用（完成打戳 / 重开清戳）；
3. ``PUT /todos/{id}`` 的 ``status=completed`` 分派（与 /complete 同语义）。
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.todo_router import build_router
from backend.data.database import Database
from backend.services import todo_status
from backend.services.todo_service import TodoService

pytestmark = pytest.mark.unit


@pytest.fixture()
def todo_service():
    """临时数据库上的 TodoService。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=str(Path(tmpdir) / "test.db"))
        db.init_db()
        service = TodoService(db)
        yield service
        db.close()


@pytest.fixture()
def client(todo_service):
    """只挂载 todo 路由的 TestClient（不带 /api/v1 前缀）。

    必须挂到 ``FastAPI()`` 应用上而不是裸 ``APIRouter``：裸 router 没有
    应用级的 ``RequestValidationError`` 处理器，非法载荷会直接抛异常而
    不是转成 422。
    """
    app = FastAPI()
    app.include_router(build_router(lambda: todo_service))
    return TestClient(app)


# ---------- todo_status 纯函数 ----------


def test_cycle_walks_pending_in_progress_completed():
    assert todo_status.next_cycle_status("pending") == "in_progress"
    assert todo_status.next_cycle_status("in_progress") == "completed"
    assert todo_status.next_cycle_status("completed") == "pending"


def test_cancelled_is_not_part_of_the_cycle():
    assert todo_status.next_cycle_status("cancelled") is None
    assert not todo_status.is_active("cancelled")
    assert todo_status.is_active("pending")
    assert todo_status.is_active("in_progress")


def test_completion_timestamp_stamps_only_completed():
    now = datetime(2026, 11, 27, 9, 30, 0)  # noqa: DTZ001 — 有意用 naive，与服务层 datetime.now() 同口径
    assert todo_status.completion_timestamp("completed", now) == "2026-11-27T09:30:00"
    assert todo_status.completion_timestamp("pending", now) is None
    assert todo_status.completion_timestamp("in_progress", now) is None
    assert todo_status.completion_timestamp("cancelled", now) is None


def test_apply_completion_stamp_only_touches_status_updates():
    updates = {"title": "x"}
    todo_status.apply_completion_stamp(
        updates, datetime(2026, 11, 27, 9, 30, 0)  # noqa: DTZ001 — 同上
    )
    assert "completed_at" not in updates

    updates = {"status": "pending"}
    todo_status.apply_completion_stamp(
        updates, datetime(2026, 11, 27, 9, 30, 0)  # noqa: DTZ001 — 同上
    )
    assert updates["completed_at"] is None


# ---------- 服务层副作用 ----------


def test_update_to_in_progress_keeps_completion_empty(todo_service):
    todo = todo_service.create_todo(title="写方案")
    assert todo.completed_at is None

    updated = todo_service.update_todo(todo.id, status="in_progress")

    assert updated is not None
    assert updated.status == "in_progress"
    assert updated.completed_at is None


def test_reopening_a_completed_todo_clears_completion_time(todo_service):
    todo = todo_service.create_todo(title="写方案")
    completed = todo_service.complete_todo(todo.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.completed_at is not None

    reopened = todo_service.update_todo(todo.id, status="pending")

    assert reopened is not None
    assert reopened.status == "pending"
    assert reopened.completed_at is None


def test_status_change_without_status_key_leaves_completion_alone(todo_service):
    todo = todo_service.create_todo(title="写方案")
    completed = todo_service.complete_todo(todo.id)
    assert completed is not None

    updated = todo_service.update_todo(todo.id, title="写方案 v2")

    assert updated is not None
    assert updated.title == "写方案 v2"
    # 状态没动 → 完成时间不该被顺手清掉。
    assert updated.completed_at == completed.completed_at


# ---------- 路由分派 ----------


def test_router_put_completed_uses_complete_semantics(client, todo_service):
    todo = todo_service.create_todo(title="写方案")

    response = client.put(f"/todos/{todo.id}", json={"status": "completed"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None


def test_router_put_in_progress_marks_started(client, todo_service):
    todo = todo_service.create_todo(title="写方案")

    response = client.put(f"/todos/{todo.id}", json={"status": "in_progress"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["completed_at"] is None


def test_router_put_rejects_unknown_status(client, todo_service):
    todo = todo_service.create_todo(title="写方案")

    response = client.put(f"/todos/{todo.id}", json={"status": "done"})

    assert response.status_code == 422
