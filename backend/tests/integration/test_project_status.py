"""projects.status 生命周期字段（工作台总览页归档）。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from backend.main import app  # noqa: F401 — 确保路由已注册


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    path = tmp_path / "demo-project"
    path.mkdir()
    return path


async def _register(client: httpx.AsyncClient, path: Path) -> dict:
    response = await client.post("/api/v1/projects", json={"path": str(path)})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio()
async def test_new_project_defaults_to_active(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    assert project["status"] == "active"


@pytest.mark.asyncio()
async def test_patch_archives_and_restores(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    archived = await client.patch(
        f"/api/v1/projects/{project['id']}", json={"status": "archived"}
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"

    listed = await client.get("/api/v1/projects")
    assert listed.json()["projects"][0]["status"] == "archived"

    restored = await client.patch(
        f"/api/v1/projects/{project['id']}", json={"status": "active"}
    )
    assert restored.json()["status"] == "active"


@pytest.mark.asyncio()
async def test_patch_rejects_unknown_status(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    response = await client.patch(
        f"/api/v1/projects/{project['id']}", json={"status": "deleted"}
    )
    assert response.status_code == 422
