"""Integration tests for the projects registry HTTP routes (项目模块 P1)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from backend.data import database as database_module
from backend.data.database import Database
from backend.main import app


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
def project_dir(tmp_path: Path) -> Path:
    path = tmp_path / "demo-project"
    path.mkdir()
    return path


@pytest_asyncio.fixture()
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


async def _register(client: httpx.AsyncClient, path: Path) -> dict:
    response = await client.post("/api/v1/projects", json={"path": str(path)})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio()
async def test_list_projects_empty(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/projects")
    assert response.status_code == 200
    assert response.json() == {"projects": []}


@pytest.mark.asyncio()
async def test_register_project_is_idempotent_by_path(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    first = await _register(client, project_dir)
    assert first["name"] == "demo-project"
    assert Path(first["path"]).is_absolute()

    # 同一目录重复登记 → 幂等（同一行，不新增）
    second = await _register(client, project_dir)
    assert second["id"] == first["id"]

    listed = (await client.get("/api/v1/projects")).json()["projects"]
    assert len(listed) == 1
    assert listed[0]["session_count"] == 0
    assert listed[0]["last_session_id"] is None


@pytest.mark.asyncio()
async def test_register_rejects_missing_directory(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    response = await client.post(
        "/api/v1/projects", json={"path": str(tmp_path / "does-not-exist")}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_workspace_path"


@pytest.mark.asyncio()
async def test_remove_project_then_404(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    response = await client.delete(f"/api/v1/projects/{project['id']}")
    assert response.status_code == 200
    assert response.json() == {"removed": True}

    again = await client.delete(f"/api/v1/projects/{project['id']}")
    assert again.status_code == 404
    assert again.json()["detail"]["code"] == "project_not_found"


@pytest.mark.asyncio()
async def test_open_project_binds_session_and_reuses_it(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)

    first = await client.post(f"/api/v1/projects/{project['id']}/open")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["created"] is True
    assert body["session"]["title"] == "demo-project"
    session_id = body["session"]["id"]

    # 打开即绑定：会话工作区 = 项目目录
    binding = await client.get(f"/api/v1/sessions/{session_id}/workspace")
    assert binding.status_code == 200
    assert binding.json()["binding"]["workspace_path"] == str(project_dir.resolve())

    # 再次打开 → 复用最近会话，不新建
    second = await client.post(f"/api/v1/projects/{project['id']}/open")
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["session"]["id"] == session_id

    listed = (await client.get("/api/v1/projects")).json()["projects"]
    assert listed[0]["session_count"] == 1
    assert listed[0]["last_session_id"] == session_id


@pytest.mark.asyncio()
async def test_project_sessions_listing(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    opened = await client.post(f"/api/v1/projects/{project['id']}/open")
    session_id = opened.json()["session"]["id"]

    response = await client.get(f"/api/v1/projects/{project['id']}/sessions")
    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert [s["id"] for s in sessions] == [session_id]


@pytest.mark.asyncio()
async def test_open_project_with_missing_directory_returns_410(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    shutil.rmtree(project_dir)

    response = await client.post(f"/api/v1/projects/{project['id']}/open")
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "project_path_missing"

    # 清单仍保留该项目（用户决定移除或重选目录）
    listed = (await client.get("/api/v1/projects")).json()["projects"]
    assert len(listed) == 1


@pytest.mark.asyncio()
async def test_remove_project_keeps_bound_sessions(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    """移除项目只删注册行：会话与其工作区绑定不受影响。"""
    project = await _register(client, project_dir)
    opened = await client.post(f"/api/v1/projects/{project['id']}/open")
    session_id = opened.json()["session"]["id"]

    await client.delete(f"/api/v1/projects/{project['id']}")

    binding = await client.get(f"/api/v1/sessions/{session_id}/workspace")
    assert binding.status_code == 200
    assert binding.json()["binding"] is not None
