"""Integration tests for todo REST API."""
from __future__ import annotations

from datetime import datetime, timedelta

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


# --- fix round 1: sort_by / sort_order (spec §7.2, §8.2) ---


def test_list_todos_sort_by_priority(client: TestClient):
    """priority sort must be high→medium→low, not lexicographic."""
    client.post("/api/v1/todos", json={"title": "low", "priority": "low"})
    client.post("/api/v1/todos", json={"title": "high", "priority": "high"})
    client.post("/api/v1/todos", json={"title": "medium", "priority": "medium"})
    resp = client.get("/api/v1/todos", params={"sort_by": "priority"})
    assert [t["title"] for t in resp.json()["items"]] == ["high", "medium", "low"]


def test_list_todos_sort_order_desc(client: TestClient):
    """sort_order=desc inverts the documented sort key."""
    client.post("/api/v1/todos", json={"title": "low", "priority": "low"})
    client.post("/api/v1/todos", json={"title": "high", "priority": "high"})
    resp = client.get(
        "/api/v1/todos", params={"sort_by": "priority", "sort_order": "desc"}
    )
    assert [t["title"] for t in resp.json()["items"]] == ["low", "high"]


def test_list_todos_undated_sorts_last(client: TestClient):
    """Undated todos have no deadline — they must not outrank dated ones."""
    client.post("/api/v1/todos", json={"title": "undated"})
    client.post(
        "/api/v1/todos",
        json={"title": "dated", "due_at": "2099-01-01T00:00:00"},
    )
    resp = client.get("/api/v1/todos", params={"sort_by": "due_at"})
    assert [t["title"] for t in resp.json()["items"]] == ["dated", "undated"]


def test_list_todos_invalid_sort_by_is_422(client: TestClient):
    """An unknown sort key is a client error, not a silent default fallback."""
    resp = client.get("/api/v1/todos", params={"sort_by": "title"})
    assert resp.status_code == 422


def test_list_todos_invalid_sort_order_is_422(client: TestClient):
    resp = client.get("/api/v1/todos", params={"sort_order": "sideways"})
    assert resp.status_code == 422


# --- fix round 1: GET /todos/stats (spec §7.1's 9th endpoint) ---


def test_stats(client: TestClient):
    client.post(
        "/api/v1/todos",
        json={"title": "high prio", "priority": "high",
              "due_at": "2000-01-01T00:00:00"},
    )
    client.post("/api/v1/todos", json={"title": "plain"})
    resp = client.get("/api/v1/todos/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    assert body["by_priority"]["high"] >= 1
    assert body["by_status"]["pending"] >= 2
    assert body["overdue"] >= 1


def test_stats_empty_db_returns_zeroes(client: TestClient):
    resp = client.get("/api/v1/todos/stats")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_stats_route_not_swallowed_by_todo_id(client: TestClient):
    """/todos/stats must not be parsed as todo_id='stats'."""
    resp = client.get("/api/v1/todos/stats")
    assert resp.status_code == 200


# --- fix round 1: reviewer findings C1-C6 (Ruling 10) ---


def test_summary_serialises_todo_rows(client: TestClient):
    """All four summary lists must be non-empty so the Todo→TodoOut coercion
    runs — it is the only exit from _todo_to_dict, so a regression there would
    otherwise pass the whole suite green."""
    now = datetime.now()
    today_end = now.replace(hour=23, minute=59, second=59)
    # Midpoint of [now, today_end] is strictly inside the service's `today`
    # window regardless of the wall-clock hour the suite runs at.
    due_today = now + (today_end - now) / 2

    client.post(
        "/api/v1/todos",
        json={"title": "Overdue", "due_at": (now - timedelta(hours=2)).isoformat()},
    )
    client.post(
        "/api/v1/todos",
        json={"title": "Today", "due_at": due_today.isoformat()},
    )
    client.post(
        "/api/v1/todos",
        json={"title": "Upcoming", "due_at": (now + timedelta(days=3)).isoformat()},
    )
    client.post("/api/v1/todos", json={"title": "High", "priority": "high"})

    resp = client.get("/api/v1/todos/summary")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["overdue"]) >= 1
    assert len(body["today"]) >= 1
    assert len(body["upcoming"]) >= 1
    assert len(body["high_priority"]) >= 1
    assert body["overdue"][0]["title"] == "Overdue"
    assert body["high_priority"][0]["title"] == "High"


def test_update_todo_not_found_returns_404(client: TestClient):
    resp = client.put("/api/v1/todos/99999", json={"title": "Ghost"})
    assert resp.status_code == 404


def test_cancel_todo_not_found_returns_404(client: TestClient):
    """cancel_todo re-fetches with get_todo; without a None guard it 500s."""
    resp = client.post("/api/v1/todos/99999/cancel")
    assert resp.status_code == 404


def test_cancel_returns_404_when_row_vanishes(client, todo_service, monkeypatch):
    """The row may disappear between the UPDATE and the re-fetch (a
    concurrent DELETE). Without the second None guard, ``_todo_to_dict(None)``
    raises AttributeError → an opaque 500."""

    monkeypatch.setattr(todo_service, "cancel_todo", lambda _id: True)
    monkeypatch.setattr(todo_service, "get_todo", lambda _id: None)

    resp = client.post("/api/v1/todos/1/cancel")
    assert resp.status_code == 404


def test_list_invalid_status_is_422(client: TestClient):
    """An unknown status filter is a client error, not a silent empty list."""
    resp = client.get("/api/v1/todos", params={"status": "bogus"})
    assert resp.status_code == 422


def test_list_invalid_priority_is_422(client: TestClient):
    resp = client.get("/api/v1/todos", params={"priority": "bogus"})
    assert resp.status_code == 422


def test_create_todo_rejects_unknown_field(client: TestClient):
    """CreateTodoIn must forbid extras, matching UpdateTodoIn."""
    resp = client.post("/api/v1/todos", json={"title": "X", "bogus": 1})
    assert resp.status_code == 422


def test_list_limit_offset_and_filters(client: TestClient):
    """limit/offset are echoed, and a filter actually filters."""
    for i in range(4):
        client.post("/api/v1/todos", json={"title": f"Low {i}", "priority": "low"})
    client.post("/api/v1/todos", json={"title": "High", "priority": "high"})

    page = client.get("/api/v1/todos", params={"limit": 2, "offset": 1})
    body = page.json()
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["items"]) == 2

    filtered = client.get("/api/v1/todos", params={"priority": "high"})
    titles = [t["title"] for t in filtered.json()["items"]]
    assert titles == ["High"]


def test_list_total_is_match_count_not_page_length(client: TestClient):
    """`total` must describe the whole match set, not the returned page."""
    for i in range(5):
        client.post("/api/v1/todos", json={"title": f"T{i}"})

    resp = client.get("/api/v1/todos", params={"limit": 2})
    body = resp.json()

    assert len(body["items"]) == 2
    assert body["total"] == 5


def test_list_status_all_includes_completed(client: TestClient):
    """status=all must widen to every status, not silently degrade to
    pending/in_progress (Ruling 7, re-introduced through the REST face)."""
    created = client.post("/api/v1/todos", json={"title": "Done"})
    todo_id = created.json()["id"]
    client.post(f"/api/v1/todos/{todo_id}/complete")

    resp = client.get("/api/v1/todos", params={"status": "all"})
    titles = [t["title"] for t in resp.json()["items"]]
    assert "Done" in titles


def test_put_explicit_null_clears_nullable_field(client: TestClient):
    """PUT must be able to clear a nullable field — parity with the LLM tool,
    which passes **kwargs and can clear."""
    created = client.post(
        "/api/v1/todos",
        json={"title": "X", "description": "to be cleared"},
    )
    todo_id = created.json()["id"]

    resp = client.put(f"/api/v1/todos/{todo_id}", json={"description": None})

    assert resp.status_code == 200
    assert resp.json()["description"] is None
    # and the row really is cleared, not just the echoed response
    assert client.get(f"/api/v1/todos/{todo_id}").json()["description"] is None


def test_put_absent_key_leaves_field_unchanged(client: TestClient):
    """exclude_unset must keep "key absent" distinct from "explicit null"."""
    created = client.post(
        "/api/v1/todos",
        json={"title": "X", "description": "keep me"},
    )
    todo_id = created.json()["id"]

    resp = client.put(f"/api/v1/todos/{todo_id}", json={"title": "Renamed"})

    assert resp.status_code == 200
    assert resp.json()["title"] == "Renamed"
    assert resp.json()["description"] == "keep me"
