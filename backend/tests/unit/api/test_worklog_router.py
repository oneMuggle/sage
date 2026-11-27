"""工作日志 REST 路由测试（P2）。

覆盖：增删改查、状态迁移（confirm/dismiss）、统计快照、404/503 分支，
以及**字面量路径必须排在 ``/worklogs/{worklog_id}`` 之前**这一路由顺序约束
—— 否则 ``GET /worklogs/summary`` 会被整数路径参数吞掉并返回 422。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.worklog_router import build_router
from backend.data.database import Database
from backend.services.worklog_service import WorklogService


@pytest.fixture()
def client():
    """挂在临时 SQLite 上的 TestClient。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=str(Path(tmpdir) / "worklog_router_test.db"))
        db.init_db()
        service = WorklogService(db)
        app = FastAPI()
        app.include_router(build_router(lambda: service))
        yield TestClient(app)
        db.close()


@pytest.fixture()
def uninitialised_client():
    """服务未初始化 —— 依赖注入应返回 503 而不是 AttributeError。"""
    app = FastAPI()
    app.include_router(build_router(lambda: None))
    return TestClient(app)


# ======================================================================
# 路由顺序
# ======================================================================


def test_literal_paths_are_not_swallowed_by_path_param(client):
    """``/worklogs/summary`` 不能落到 ``/worklogs/{worklog_id}`` 上。"""
    response = client.get("/worklogs/summary")

    assert response.status_code == 200
    assert response.json()["total"] == 0


# ======================================================================
# 增删改查
# ======================================================================


def test_create_worklog_returns_201_and_pending(client):
    """新建一律落 pending —— 人工确认前不算数。"""
    response = client.post("/worklogs", json={"content": "完成了登录页"})

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == "完成了登录页"
    assert body["kind"] == "progress"
    assert body["status"] == "pending"
    assert body["id"] > 0


def test_create_worklog_rejects_unknown_kind(client):
    """非法 kind → 422（Pydantic pattern 拦截）。"""
    response = client.post("/worklogs", json={"content": "x", "kind": "whatever"})

    assert response.status_code == 422


def test_create_worklog_rejects_unknown_field(client):
    """``extra='forbid'`` —— 未知字段直接 422。"""
    response = client.post("/worklogs", json={"content": "x", "bogus": 1})

    assert response.status_code == 422


def test_create_worklog_with_invalid_todo_returns_400(client):
    """外键不存在 → 400（服务层 ValueError）。"""
    response = client.post("/worklogs", json={"content": "x", "todo_id": 4242})

    assert response.status_code == 400


def test_list_worklogs_returns_items_and_total(client):
    """列表返回当前页 + 全量 total。"""
    for index in range(3):
        client.post("/worklogs", json={"content": f"第 {index} 件事"})

    response = client.get("/worklogs")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    assert body["limit"] == 50


def test_list_worklogs_filters_by_status(client):
    """status 查询参数生效。"""
    created = client.post("/worklogs", json={"content": "待确认"}).json()
    client.post(f"/worklogs/{created['id']}/confirm")

    response = client.get("/worklogs", params={"status": "pending"})

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_list_worklogs_rejects_unknown_status(client):
    """非法 status → 422。"""
    response = client.get("/worklogs", params={"status": "archived"})

    assert response.status_code == 422


def test_get_worklog_returns_detail(client):
    """按 id 取详情。"""
    created = client.post("/worklogs", json={"content": "x"}).json()

    response = client.get(f"/worklogs/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_worklog_missing_returns_404(client):
    """不存在的 id → 404。"""
    response = client.get("/worklogs/9999")

    assert response.status_code == 404


def test_update_worklog_edits_content(client):
    """编辑正文。"""
    created = client.post("/worklogs", json={"content": "旧正文"}).json()

    response = client.put(f"/worklogs/{created['id']}", json={"content": "新正文"})

    assert response.status_code == 200
    assert response.json()["content"] == "新正文"


def test_update_worklog_absent_key_leaves_column(client):
    """键缺席 = 不动该列。"""
    created = client.post("/worklogs", json={"content": "旧正文", "kind": "done"}).json()

    response = client.put(f"/worklogs/{created['id']}", json={"content": "新正文"})

    assert response.status_code == 200
    assert response.json()["kind"] == "done"


def test_update_worklog_cannot_change_status(client):
    """编辑接口不含 status —— 状态迁移只能走 confirm/dismiss。"""
    created = client.post("/worklogs", json={"content": "x"}).json()

    response = client.put(f"/worklogs/{created['id']}", json={"status": "confirmed"})

    assert response.status_code == 422
    assert client.get(f"/worklogs/{created['id']}").json()["status"] == "pending"


def test_update_worklog_missing_returns_404(client):
    """不存在的 id → 404。"""
    response = client.put("/worklogs/9999", json={"content": "x"})

    assert response.status_code == 404


def test_delete_worklog_returns_204_then_404(client):
    """删除 → 204 空响应体；再取 → 404。"""
    created = client.post("/worklogs", json={"content": "x"}).json()

    deleted = client.delete(f"/worklogs/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    assert client.get(f"/worklogs/{created['id']}").status_code == 404


def test_delete_worklog_missing_returns_404(client):
    """删除不存在的 id → 404。"""
    assert client.delete("/worklogs/9999").status_code == 404


# ======================================================================
# 状态迁移
# ======================================================================


def test_confirm_worklog(client):
    """pending → confirmed。"""
    created = client.post("/worklogs", json={"content": "x"}).json()

    response = client.post(f"/worklogs/{created['id']}/confirm")

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


def test_dismiss_worklog(client):
    """pending → dismissed。"""
    created = client.post("/worklogs", json={"content": "x"}).json()

    response = client.post(f"/worklogs/{created['id']}/dismiss")

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"


def test_confirm_missing_returns_404(client):
    """确认不存在的 id → 404。"""
    assert client.post("/worklogs/9999/confirm").status_code == 404


# ======================================================================
# 统计快照
# ======================================================================


def test_summary_counts_only_confirmed(client):
    """统计只认已确认 —— 待确认候选绝不进报告。"""
    client.post("/worklogs", json={"content": "候选", "kind": "progress"})
    confirmed = client.post("/worklogs", json={"content": "正式", "kind": "done"}).json()
    client.post(f"/worklogs/{confirmed['id']}/confirm")

    body = client.get("/worklogs/summary").json()

    assert body["total"] == 1
    assert body["by_kind"]["done"] == 1
    assert body["by_kind"]["progress"] == 0


# ======================================================================
# 服务未初始化
# ======================================================================


def test_endpoints_return_503_when_service_missing(uninitialised_client):
    """依赖注入拿不到服务 → 503，不抛 AttributeError。"""
    assert uninitialised_client.get("/worklogs").status_code == 503
    assert uninitialised_client.get("/worklogs/summary").status_code == 503
    assert uninitialised_client.post("/worklogs", json={"content": "x"}).status_code == 503
