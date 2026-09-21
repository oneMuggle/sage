"""Integration tests for todo REST API."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def todo_service():
    """Ensure TodoService is initialised and clean up global state after."""
    import backend.data.database as db_mod
    import backend.services.todo_service as todo_mod
    from backend.services.todo_service import init_todo_service

    original = todo_mod._global_service
    svc = init_todo_service(db_mod._db)
    yield svc
    todo_mod._global_service = original


@pytest.fixture()
def client(todo_service) -> TestClient:
    """Build a TestClient with the todo router mounted."""
    from backend.api.todo_router import build_router

    app = FastAPI()
    app.include_router(build_router(lambda: todo_service), prefix="/api/v1")
    return TestClient(app)


@pytest.fixture()
def raw_client() -> TestClient:
    """Build a TestClient using get_todo_service (for 503 tests)."""
    from backend.api.todo_router import build_router
    from backend.services.todo_service import get_todo_service

    app = FastAPI()
    app.include_router(build_router(get_todo_service), prefix="/api/v1")
    return TestClient(app)


def test_create_todo(client: TestClient):
    resp = client.post(
        "/api/v1/todos",
        json={"title": "Buy milk", "priority": "medium"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Buy milk"
    assert body["status"] == "pending"
    assert body["priority"] == "medium"
    assert "id" in body


def test_list_todos(client: TestClient):
    client.post("/api/v1/todos", json={"title": "Task 1"})
    client.post("/api/v1/todos", json={"title": "Task 2"})
    resp = client.get("/api/v1/todos")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) >= 2


def test_get_todo(client: TestClient):
    create_resp = client.post("/api/v1/todos", json={"title": "Get me"})
    todo_id = create_resp.json()["id"]
    resp = client.get(f"/api/v1/todos/{todo_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Get me"


def test_get_todo_not_found(client: TestClient):
    resp = client.get("/api/v1/todos/99999")
    assert resp.status_code == 404


def test_update_todo(client: TestClient):
    create_resp = client.post("/api/v1/todos", json={"title": "Original"})
    todo_id = create_resp.json()["id"]
    resp = client.put(f"/api/v1/todos/{todo_id}", json={"title": "Updated"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated"


def test_delete_todo(client: TestClient):
    create_resp = client.post("/api/v1/todos", json={"title": "Delete me"})
    todo_id = create_resp.json()["id"]
    resp = client.delete(f"/api/v1/todos/{todo_id}")
    assert resp.status_code == 204
    resp = client.get(f"/api/v1/todos/{todo_id}")
    assert resp.status_code == 404


def test_complete_todo(client: TestClient):
    create_resp = client.post("/api/v1/todos", json={"title": "Complete me"})
    todo_id = create_resp.json()["id"]
    resp = client.post(f"/api/v1/todos/{todo_id}/complete")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_cancel_todo(client: TestClient):
    create_resp = client.post("/api/v1/todos", json={"title": "Cancel me"})
    todo_id = create_resp.json()["id"]
    resp = client.post(f"/api/v1/todos/{todo_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_summary(client: TestClient):
    client.post("/api/v1/todos", json={"title": "Pending 1"})
    client.post("/api/v1/todos", json={"title": "Pending 2"})
    resp = client.get("/api/v1/todos/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "overdue" in body
    assert "total_pending" in body
    assert body["total_pending"] >= 2


def test_service_not_initialised_returns_503(raw_client: TestClient):
    """When init_todo_service() has not been called, endpoints return 503."""
    import backend.services.todo_service as todo_mod

    original = todo_mod._global_service
    todo_mod._global_service = None
    try:
        resp = raw_client.get("/api/v1/todos")
        assert resp.status_code == 503
    finally:
        todo_mod._global_service = original
