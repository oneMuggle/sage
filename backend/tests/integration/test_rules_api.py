"""规则中心聚合读接口集成测试（M3，2026-11-07）。"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from backend.data import database as database_module
from backend.data.database import Database
from backend.main import app


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch: pytest.MonkeyPatch):
    """隔离全局规则：`Path.home()` 在 POSIX 读 HOME，避免读到开发机的 ~/.sage/SAGE.md。"""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


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


async def test_list_rules_aggregates_constraints(client: httpx.AsyncClient, project_dir):
    project = await _register(client, project_dir)
    created = await client.post(
        f"/api/v1/projects/{project['id']}/constraints",
        json={"category": "coding_style", "content": "使用双引号", "priority": 6},
    )
    assert created.status_code == 201, created.text

    response = await client.get(f"/api/v1/projects/{project['id']}/rules")

    assert response.status_code == 200, response.text
    rules = response.json()["rules"]
    assert len(rules) == 1
    assert rules[0]["layer"] == "constraint"
    assert rules[0]["source_label"] == "项目规则"
    assert rules[0]["editable"] == "full"
    assert rules[0]["priority"] == 6


async def test_list_rules_includes_project_docs(client: httpx.AsyncClient, project_dir):
    (project_dir / "SAGE.md").write_text("# 项目规则\n\n跑 pytest。\n", encoding="utf-8")
    (project_dir / "CLAUDE.md").write_text("# 工具\n\n用 conda。\n", encoding="utf-8")
    project = await _register(client, project_dir)

    response = await client.get(f"/api/v1/projects/{project['id']}/rules")

    docs = [rule for rule in response.json()["rules"] if rule["layer"] == "doc"]
    by_id = {rule["id"]: rule for rule in docs}
    assert by_id["doc:SAGE.md#0"]["editable"] == "full"
    assert by_id["doc:CLAUDE.md#0"]["editable"] == "readonly"


async def test_effective_returns_injection_order(client: httpx.AsyncClient, project_dir):
    (project_dir / "SAGE.md").write_text("# 项目规则\n\n跑 pytest。\n", encoding="utf-8")
    project = await _register(client, project_dir)
    await client.post(
        f"/api/v1/projects/{project['id']}/constraints",
        json={"category": "coding_style", "content": "使用双引号"},
    )

    response = await client.get(f"/api/v1/projects/{project['id']}/rules/effective")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [entry["layer"] for entry in payload["entries"]] == ["doc", "constraint"]
    assert payload["conflicts"] == []


async def test_missing_project_returns_404(client: httpx.AsyncClient):
    response = await client.get("/api/v1/projects/nope/rules")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project_not_found"


async def test_missing_project_path_returns_410(client: httpx.AsyncClient, project_dir):
    project = await _register(client, project_dir)
    project_dir.rmdir()

    response = await client.get(f"/api/v1/projects/{project['id']}/rules")

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "project_path_missing"
