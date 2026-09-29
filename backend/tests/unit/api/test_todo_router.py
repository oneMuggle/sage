"""R75 — todo 路由单元测试。

build_router 工厂 + 假 TodoService。从 router.routes 取出闭包端点后
直接调用（Query 默认参数显式传纯值——R66 沉淀）。覆盖：清单分页与
status=all 逃生口、create 字段透传、summary/stats 透传、get/update/
delete/complete/cancel 的命中与 404、update 的 exclude_unset 三态语义、
cancel 后行消失的 404 防御、载荷校验（extra=forbid / 枚举）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import todo_router as tr

pytestmark = pytest.mark.unit


def _todo_dump(todo_id=1, title="t", status="pending", priority="medium"):
    return {
        "id": todo_id, "title": title, "description": None,
        "status": status, "priority": priority,
        "effective_urgency": None, "due_at": None, "completed_at": None,
        "project_tag": None, "project_id": None, "is_recurring": False,
        "recurrence_rule": None, "parent_id": None,
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
    }


def _fake_todo(todo_id=1, status="pending"):
    dump = _todo_dump(todo_id=todo_id, status=status)
    return SimpleNamespace(model_dump=lambda: dump)


def _fake_service():
    class _Svc:
        def __init__(self):
            self.calls = {}

        def list_todos(self, **kwargs):
            self.calls["list"] = kwargs
            return [_fake_todo(1)]

        def count_todos(self, **kwargs):
            self.calls["count"] = kwargs
            return 7

        def create_todo(self, **kwargs):
            self.calls["create"] = kwargs
            return _fake_todo(9, status="pending")

        def get_startup_summary(self):
            return {"overdue": [], "today": [], "upcoming": [], "high_priority": []}

        def get_todo_stats(self):
            return {"total": 3, "by_status": {}, "by_priority": {}}

        def get_todo(self, todo_id):
            return _fake_todo(todo_id) if todo_id == 1 else None

        def update_todo(self, todo_id, **changes):
            self.calls["update"] = (todo_id, changes)
            return _fake_todo(todo_id) if todo_id == 1 else None

        def delete_todo(self, todo_id):
            self.calls["delete"] = todo_id
            return todo_id == 1

        def complete_todo(self, todo_id):
            return _fake_todo(todo_id, status="completed") if todo_id == 1 else None

        def cancel_todo(self, todo_id):
            self.calls["cancel"] = todo_id
            return todo_id == 1

    return _Svc()


@pytest.fixture()
def routes():
    svc = _fake_service()
    router = tr.build_router(lambda: svc)
    out = {}
    for route in router.routes:
        for method in route.methods:
            out[(method, route.path)] = route.endpoint
    return out, svc


# ---------------------------------------------------------------------------
# 清单 / 创建 / 汇总
# ---------------------------------------------------------------------------


def test_list_todos_maps_items_and_total(routes):
    eps, svc = routes
    out = eps[("GET", "/todos")](
        status=None, project_tag=None, priority=None, include_completed=False,
        sort_by="due_at", sort_order="asc", limit=50, offset=0, svc=svc,
    )
    assert out["total"] == 7
    assert out["limit"] == 50
    assert out["offset"] == 0
    assert out["items"][0]["id"] == 1
    assert svc.calls["list"]["include_completed"] is False
    assert svc.calls["count"]["include_completed"] is False


def test_list_todos_status_all_sets_include_completed(routes):
    eps, svc = routes
    eps[("GET", "/todos")](
        status="all", project_tag=None, priority=None, include_completed=False,
        sort_by="due_at", sort_order="asc", limit=10, offset=2, svc=svc,
    )
    assert svc.calls["list"]["include_completed"] is True
    assert svc.calls["count"]["include_completed"] is True


def test_create_todo_delegates_fields(routes):
    eps, svc = routes
    payload = tr.CreateTodoIn(
        title=" 买牛奶 ", description="d", due_at="2026-10-01",
        priority="high", project_tag="home", recurrence_rule="RRULE:FREQ=DAILY",
    )
    out = eps[("POST", "/todos")](payload, svc=svc)
    assert out["id"] == 9
    call = svc.calls["create"]
    assert call["title"] == " 买牛奶 "  # 路由层不做 strip，交由服务层
    assert call["priority"] == "high"
    assert call["recurrence_rule"] == "RRULE:FREQ=DAILY"


def test_summary_and_stats_passthrough(routes):
    eps, svc = routes
    assert eps[("GET", "/todos/summary")](svc=svc)["today"] == []
    assert eps[("GET", "/todos/stats")](svc=svc)["total"] == 3


# ---------------------------------------------------------------------------
# get / update / delete / complete / cancel
# ---------------------------------------------------------------------------


def test_get_todo_hit(routes):
    eps, svc = routes
    out = eps[("GET", "/todos/{todo_id}")](1, svc=svc)
    assert out["id"] == 1


def test_get_todo_miss_404(routes):
    eps, svc = routes
    with pytest.raises(HTTPException) as ei:
        eps[("GET", "/todos/{todo_id}")](42, svc=svc)
    assert ei.value.status_code == 404


def test_update_todo_exclude_unset_semantics(routes):
    eps, svc = routes
    payload = tr.UpdateTodoIn(description=None)  # 显式 null → 清空
    eps[("PUT", "/todos/{todo_id}")](1, payload, svc=svc)
    todo_id, changes = svc.calls["update"]
    assert todo_id == 1
    assert changes == {"description": None}  # 未提交的键不出现在 changes


def test_update_todo_miss_404(routes):
    eps, svc = routes
    with pytest.raises(HTTPException) as ei:
        eps[("PUT", "/todos/{todo_id}")](42, tr.UpdateTodoIn(title="x"), svc=svc)
    assert ei.value.status_code == 404


def test_delete_todo_hit_returns_204(routes):
    eps, svc = routes
    resp = eps[("DELETE", "/todos/{todo_id}")](1, svc=svc)
    assert resp.status_code == 204
    assert svc.calls["delete"] == 1


def test_delete_todo_miss_404(routes):
    eps, svc = routes
    with pytest.raises(HTTPException) as ei:
        eps[("DELETE", "/todos/{todo_id}")](42, svc=svc)
    assert ei.value.status_code == 404


def test_complete_todo_hit_and_miss(routes):
    eps, svc = routes
    out = eps[("POST", "/todos/{todo_id}/complete")](1, svc=svc)
    assert out["status"] == "completed"
    with pytest.raises(HTTPException) as ei:
        eps[("POST", "/todos/{todo_id}/complete")](42, svc=svc)
    assert ei.value.status_code == 404


def test_cancel_todo_hit(routes):
    eps, svc = routes
    out = eps[("POST", "/todos/{todo_id}/cancel")](1, svc=svc)
    assert out["id"] == 1


def test_cancel_todo_miss_404(routes):
    eps, svc = routes
    with pytest.raises(HTTPException) as ei:
        eps[("POST", "/todos/{todo_id}/cancel")](42, svc=svc)
    assert ei.value.status_code == 404


def test_cancel_todo_row_vanished_404(routes, monkeypatch):
    # cancel 成功但重取时行已被并发删除 → 404 而非 500
    eps, svc = routes
    monkeypatch.setattr(svc, "get_todo", lambda todo_id: None)
    with pytest.raises(HTTPException) as ei:
        eps[("POST", "/todos/{todo_id}/cancel")](1, svc=svc)
    assert ei.value.status_code == 404


# ---------------------------------------------------------------------------
# 载荷校验
# ---------------------------------------------------------------------------


def test_create_todo_rejects_bad_priority():
    with pytest.raises(ValidationError):
        tr.CreateTodoIn(title="t", priority="urgent")


def test_create_todo_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        tr.CreateTodoIn(title="t", unknown="x")


def test_create_todo_rejects_blank_title():
    with pytest.raises(ValidationError):
        tr.CreateTodoIn(title="")


def test_update_todo_rejects_bad_status():
    with pytest.raises(ValidationError):
        tr.UpdateTodoIn(status="done")
