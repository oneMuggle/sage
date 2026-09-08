# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""U2' 检查点端点集成测试（GET/POST /sessions/{id}/workspace/checkpoints[/restore]）。

沿用 test_workspace_revert_routes.py 的 fixture 模式（内存 DB + ASGITransport
+ 真实临时目录）；快照存储经 SAGE_USER_DATA_DIR 隔离到 tmp_path。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from backend.data import database as database_module
from backend.data.database import Database
from backend.main import app
from backend.office.session_workspace import bind_session_workspace


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest.fixture()
def conn(db: Database) -> sqlite3.Connection:
    return db.get_connection()


@pytest.fixture()
def session_id(conn: sqlite3.Connection) -> str:
    value = "session-checkpoint"
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (value, "Checkpoint", 1, 1),
    )
    conn.commit()
    return value


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    (path / "app.py").write_text("print('v1')\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def isolated_user_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """快照落盘目录隔离（_user_data_root 每次调用时读 env）。"""
    root = tmp_path / "sage-user-data"
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(root))
    return root


@pytest_asyncio.fixture()
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


@pytest.fixture()
def bound_session(conn: sqlite3.Connection, session_id: str, workspace: Path) -> str:
    bind_session_workspace(conn, session_id, str(workspace))
    return session_id


@pytest.mark.asyncio()
async def test_create_list_restore_roundtrip(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    created = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/checkpoints", json={}
    )
    assert created.status_code == 200
    body = created.json()
    checkpoint_id = body["checkpoint_id"]
    assert checkpoint_id
    assert body["files"] >= 1

    listing = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/checkpoints"
    )
    assert listing.status_code == 200
    entries = listing.json()["checkpoints"]
    assert [entry["checkpoint_id"] for entry in entries] == [checkpoint_id]
    assert entries[0]["files"] == body["files"]

    # 工作区被改掉后恢复到快照态
    (workspace / "app.py").write_text("print('v2-broken')\n", encoding="utf-8")
    restored = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/checkpoints/restore",
        json={"checkpoint_id": checkpoint_id},
    )
    assert restored.status_code == 200
    assert restored.json()["restored"] >= 1
    assert "v1" in (workspace / "app.py").read_text(encoding="utf-8")


@pytest.mark.asyncio()
async def test_list_empty(client: httpx.AsyncClient, bound_session: str) -> None:
    response = await client.get(f"/api/v1/sessions/{bound_session}/workspace/checkpoints")
    assert response.status_code == 200
    assert response.json()["checkpoints"] == []


@pytest.mark.asyncio()
async def test_restore_invalid_id_400(client: httpx.AsyncClient, bound_session: str) -> None:
    response = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/checkpoints/restore",
        json={"checkpoint_id": "../escape"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_checkpoint_id"


@pytest.mark.asyncio()
async def test_restore_missing_snapshot_404(
    client: httpx.AsyncClient, bound_session: str
) -> None:
    response = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/checkpoints/restore",
        json={"checkpoint_id": "20990101-000000-dead00"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "checkpoint_not_found"


@pytest.mark.asyncio()
async def test_requires_binding(
    client: httpx.AsyncClient, session_id: str, workspace: Path
) -> None:
    listing = await client.get(f"/api/v1/sessions/{session_id}/workspace/checkpoints")
    assert listing.status_code == 403
    created = await client.post(
        f"/api/v1/sessions/{session_id}/workspace/checkpoints", json={}
    )
    assert created.status_code == 403
    restored = await client.post(
        f"/api/v1/sessions/{session_id}/workspace/checkpoints/restore",
        json={"checkpoint_id": "20990101-000000-dead00"},
    )
    assert restored.status_code == 403
