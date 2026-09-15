"""Integration tests for the wiki ↔ projects registry bridge on win7 (P12).

对齐 main P6（#775）。win7 分支 wiki/files 已由 P11（#843）解锁，
端点级用例在 Windows 真实执行。
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
from backend.data.project_repo import ProjectRepository
from backend.main import app

pytestmark = pytest.mark.integration


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest.fixture()
def conn(db: Database) -> sqlite3.Connection:
    return db.get_connection()


@pytest_asyncio.fixture()
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


@pytest.mark.asyncio()
async def test_open_wiki_project_touches_registry_last_opened_at(
    client: httpx.AsyncClient, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """打开已登记的 wiki 项目 → 200 且 projects.last_opened_at 刷新。"""
    project = tmp_path / "bridge-project"
    (project / "wiki").mkdir(parents=True)
    registered = ProjectRepository().register(str(project), now_ms=1_000)
    assert registered.last_opened_at == 1_000

    response = await client.post(
        "/api/v1/wiki/project/open", json={"path": str(project)}
    )
    assert response.status_code == 200, response.text

    after = ProjectRepository().get(registered.id)
    assert after is not None
    assert after.last_opened_at > 1_000


@pytest.mark.asyncio()
async def test_create_wiki_project_registers_into_projects(
    client: httpx.AsyncClient, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """创建 wiki 项目 → projects 注册表同步新增（双登记）。"""
    base = tmp_path / "created-wiki"
    assert ProjectRepository().list() == []

    response = await client.post(
        "/api/v1/wiki/project/create",
        json={"name": "created", "base_path": str(base)},
    )
    assert response.status_code == 200, response.text

    rows = ProjectRepository().list()
    assert len(rows) == 1
    assert rows[0].path == str(base.resolve())


@pytest.mark.asyncio()
async def test_registered_project_passes_wiki_authorization(
    client: httpx.AsyncClient, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """P12 核心：注册表命中（recents 为空）即可通过 wiki 授权门禁。"""
    project = tmp_path / "authz-bridge"
    (project / "wiki").mkdir(parents=True)
    ProjectRepository().register(str(project))

    response = await client.get(
        "/api/v1/wiki/list", params={"path": ".", "project_path": str(project)}
    )
    # 未桥接前这里会 403 项目未授权；桥接后授权通过（200 或业务 4xx，
    # 只要不是 403 未授权即视为通过）。
    assert response.status_code != 403 or "项目未授权" not in response.text
