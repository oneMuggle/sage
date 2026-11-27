"""待办拖拽排序 / 拖拽嵌套测试（P1）。

覆盖三层：

- ``todo_order`` 的同层次序分配（中点插入 / 整层重排 / 层级约束）；
- ``TodoService.move_todo`` 的委托与 ``sort_order`` 重算；
- ``POST /todos/{id}/move`` 的三态 ``target_parent_id`` 与错误码。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.data.database import Database
from backend.services import todo_order
from backend.services.todo_service import TodoService


@pytest.fixture()
def todo_service():
    """Create TodoService with temporary database"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=str(db_path))
        db.init_db()

        service = TodoService(db)

        yield service

        db.close()


@pytest.fixture()
def client(todo_service) -> TestClient:
    """Build a TestClient with the todo router mounted."""
    from backend.api.todo_router import build_router

    app = FastAPI()
    app.include_router(build_router(lambda: todo_service), prefix="/api/v1")
    return TestClient(app)


# --- sort_order 分配 ---


def test_new_todo_appends_to_layer_end(todo_service):
    first = todo_service.create_todo(title="A")
    second = todo_service.create_todo(title="B")
    third = todo_service.create_todo(title="C")

    assert first.sort_order < second.sort_order < third.sort_order


def test_new_child_appends_to_its_own_layer(todo_service):
    parent = todo_service.create_todo(title="父")
    other = todo_service.create_todo(title="顶层")
    child = todo_service.create_todo(title="子", parent_id=parent.id)

    # 子待办的 sort_order 只与同层（parent_id = parent.id）比较 —— 它是该层第一个。
    assert child.sort_order == todo_order.SORT_STEP
    # 顶层层里已经有「父」，「顶层」排在其后。
    assert other.sort_order == parent.sort_order + todo_order.SORT_STEP


# --- 移动 ---


def test_move_before_reference(todo_service):
    a = todo_service.create_todo(title="A")
    b = todo_service.create_todo(title="B")
    c = todo_service.create_todo(title="C")

    result = todo_service.move_todo(c.id, "before", reference_id=a.id)

    assert result is not None
    assert result["affected"] == 1
    assert result["todo"].id == c.id
    # 落点比参照物小即可，具体数值不重要。
    assert result["todo"].sort_order < a.sort_order


def test_move_after_reference(todo_service):
    a = todo_service.create_todo(title="A")
    b = todo_service.create_todo(title="B")

    result = todo_service.move_todo(b.id, "before", reference_id=a.id)
    assert result is not None
    assert result["todo"].sort_order < a.sort_order


def test_move_without_reference_appends_to_end(todo_service):
    a = todo_service.create_todo(title="A")
    b = todo_service.create_todo(title="B")

    result = todo_service.move_todo(a.id, "after")

    assert result is not None
    assert result["todo"].sort_order > b.sort_order


def test_move_into_parent(todo_service):
    parent = todo_service.create_todo(title="父")
    child = todo_service.create_todo(title="子", parent_id=parent.id)
    other = todo_service.create_todo(title="别的")

    result = todo_service.move_todo(other.id, "after", reference_id=child.id)

    assert result is not None
    assert result["todo"].parent_id == parent.id
    assert result["todo"].sort_order > child.sort_order


def test_move_out_to_top_level(todo_service):
    parent = todo_service.create_todo(title="父")
    child = todo_service.create_todo(title="子", parent_id=parent.id)

    result = todo_service.move_todo(child.id, "after", target_parent_id=None)

    assert result is not None
    assert result["todo"].parent_id is None


def test_move_unknown_todo_returns_none(todo_service):
    assert todo_service.move_todo(9999, "before", reference_id=1) is None


# --- 层级约束 ---


def test_cannot_reference_self(todo_service):
    a = todo_service.create_todo(title="A")

    with pytest.raises(ValueError):
        todo_service.move_todo(a.id, "before", reference_id=a.id)


def test_cannot_become_own_parent(todo_service):
    a = todo_service.create_todo(title="A")

    with pytest.raises(ValueError):
        todo_service.move_todo(a.id, "after", target_parent_id=a.id)


def test_cannot_nest_under_a_subtask(todo_service):
    parent = todo_service.create_todo(title="父")
    child = todo_service.create_todo(title="子", parent_id=parent.id)
    other = todo_service.create_todo(title="别的")

    with pytest.raises(ValueError):
        todo_service.move_todo(other.id, "after", target_parent_id=child.id)


def test_todo_with_children_cannot_be_nested(todo_service):
    parent = todo_service.create_todo(title="父")
    todo_service.create_todo(title="子", parent_id=parent.id)
    other = todo_service.create_todo(title="别的")

    with pytest.raises(ValueError):
        todo_service.move_todo(parent.id, "after", target_parent_id=other.id)


def test_unknown_parent_rejected(todo_service):
    a = todo_service.create_todo(title="A")

    with pytest.raises(ValueError):
        todo_service.move_todo(a.id, "after", target_parent_id=9999)


def test_reference_must_be_in_target_layer(todo_service):
    parent = todo_service.create_todo(title="父")
    child = todo_service.create_todo(title="子", parent_id=parent.id)
    other = todo_service.create_todo(title="别的")

    # 参照物在「父」这一层，目标却是顶层 —— 跨层相对落位没有意义。
    with pytest.raises(ValueError):
        todo_service.move_todo(
            other.id, "after", reference_id=child.id, target_parent_id=None
        )


def test_failed_move_leaves_database_untouched(todo_service):
    a = todo_service.create_todo(title="A")
    b = todo_service.create_todo(title="B")
    before = b.sort_order

    with pytest.raises(ValueError):
        todo_service.move_todo(a.id, "before", reference_id=a.id)

    assert todo_service.get_todo(b.id).sort_order == before


# --- 间距耗尽 → 整层重排 ---


def test_gap_exhaustion_renormalizes_layer(todo_service):
    """反复在同一个空隙插入，最终触发整层重排（affected > 1）。"""
    anchor = todo_service.create_todo(title="anchor")
    todo_service.create_todo(title="other")

    affected = 0
    for index in range(60):
        # 每插一条都落在 anchor 之后 → 与前一条的间距逐次折半，浮点间距最终耗尽。
        todo = todo_service.create_todo(title=f"ins{index}")
        result = todo_service.move_todo(todo.id, "after", reference_id=anchor.id)
        assert result is not None
        affected = result["affected"]
        if affected > 1:
            break

    assert affected > 1
    # 重排后整层仍是严格递增的。
    order = [t.sort_order for t in todo_service.list_todos(sort_by="manual")]
    assert order == sorted(order)
    assert len(set(order)) == len(order)


# --- 排序查询 ---


def test_list_sorted_by_manual(todo_service):
    a = todo_service.create_todo(title="A")
    b = todo_service.create_todo(title="B")
    c = todo_service.create_todo(title="C")
    todo_service.move_todo(c.id, "before", reference_id=a.id)

    items = todo_service.list_todos(sort_by="manual")

    assert [item.title for item in items] == ["C", "A", "B"]


# --- HTTP 端点 ---


def test_endpoint_move(todo_service, client: TestClient):
    a = client.post("/api/v1/todos", json={"title": "A"}).json()
    b = client.post("/api/v1/todos", json={"title": "B"}).json()

    resp = client.post(
        f"/api/v1/todos/{b['id']}/move",
        json={"position": "before", "reference_id": a["id"]},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["todo"]["id"] == b["id"]
    assert body["affected"] == 1
    assert body["todo"]["sort_order"] < a["sort_order"]


def test_endpoint_move_unknown_todo_returns_404(client: TestClient):
    resp = client.post(
        "/api/v1/todos/9999/move",
        json={"position": "before", "reference_id": 1},
    )

    assert resp.status_code == 404


def test_endpoint_illegal_move_returns_400(todo_service, client: TestClient):
    a = client.post("/api/v1/todos", json={"title": "A"}).json()

    resp = client.post(
        f"/api/v1/todos/{a['id']}/move",
        json={"position": "before", "reference_id": a["id"]},
    )

    assert resp.status_code == 400


def test_endpoint_rejects_unknown_field(client: TestClient):
    a = client.post("/api/v1/todos", json={"title": "A"}).json()

    resp = client.post(
        f"/api/v1/todos/{a['id']}/move",
        json={"position": "before", "reference_id": a["id"], "bogus": 1},
    )

    assert resp.status_code == 422


def test_endpoint_rejects_invalid_position(client: TestClient):
    a = client.post("/api/v1/todos", json={"title": "A"}).json()

    resp = client.post(
        f"/api/v1/todos/{a['id']}/move",
        json={"position": "sideways"},
    )

    assert resp.status_code == 422


def test_endpoint_target_parent_omitted_follows_reference_layer(
    todo_service, client: TestClient
):
    """省略 target_parent_id → 目标层跟随参照待办所在层。"""
    parent = client.post("/api/v1/todos", json={"title": "父"}).json()
    child = client.post(
        "/api/v1/todos", json={"title": "子", "parent_id": parent["id"]}
    ).json()
    other = client.post("/api/v1/todos", json={"title": "别的"}).json()

    resp = client.post(
        f"/api/v1/todos/{other['id']}/move",
        json={"position": "after", "reference_id": child["id"]},
    )

    assert resp.status_code == 200
    assert resp.json()["todo"]["parent_id"] == parent["id"]


def test_endpoint_target_parent_null_moves_to_top_layer(
    todo_service, client: TestClient
):
    """显式 target_parent_id=null → 强制回顶层（与省略语义不同）。"""
    parent = client.post("/api/v1/todos", json={"title": "父"}).json()
    child = client.post(
        "/api/v1/todos", json={"title": "子", "parent_id": parent["id"]}
    ).json()

    resp = client.post(
        f"/api/v1/todos/{child['id']}/move",
        json={"position": "after", "target_parent_id": None},
    )

    assert resp.status_code == 200
    assert resp.json()["todo"]["parent_id"] is None


def test_endpoint_target_parent_id_nests(todo_service, client: TestClient):
    parent = client.post("/api/v1/todos", json={"title": "父"}).json()
    other = client.post("/api/v1/todos", json={"title": "别的"}).json()

    resp = client.post(
        f"/api/v1/todos/{other['id']}/move",
        json={"position": "after", "target_parent_id": parent["id"]},
    )

    assert resp.status_code == 200
    assert resp.json()["todo"]["parent_id"] == parent["id"]


def test_endpoint_list_supports_manual_sort(client: TestClient):
    a = client.post("/api/v1/todos", json={"title": "A"}).json()
    b = client.post("/api/v1/todos", json={"title": "B"}).json()
    client.post(
        f"/api/v1/todos/{b['id']}/move",
        json={"position": "before", "reference_id": a["id"]},
    )

    resp = client.get("/api/v1/todos", params={"sort_by": "manual"})

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["B", "A"]


def test_endpoint_list_rejects_unknown_sort_by(client: TestClient):
    resp = client.get("/api/v1/todos", params={"sort_by": "bogus"})

    assert resp.status_code == 422
