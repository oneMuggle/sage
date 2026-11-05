"""项目目录树 / 子项目发现路由测试（P2 of 2026-11-05 设计）。

与 `test_project_routes.py` 共用同一套路由，但单独成文件以控制单文件行数。
DB 由 tests/conftest.py 的 autouse `setup_test_db` 提供。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import project_routes as pr

pytestmark = pytest.mark.unit


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(pr.router)
    return TestClient(app)


@pytest.fixture()
def ws_dir(tmp_path: Path) -> Path:
    d = tmp_path / "workspace-a"
    d.mkdir()
    return d


def _register(client: TestClient, path: Path) -> dict:
    resp = client.post("/projects", json={"path": str(path)})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_tree_discovers_context_file_subprojects(client, ws_dir: Path) -> None:
    (ws_dir / "sub-1").mkdir()
    (ws_dir / "sub-1" / "SAGE.md").write_text("x", encoding="utf-8")
    (ws_dir / "nested" / "deep").mkdir(parents=True)
    (ws_dir / "nested" / "deep" / "CLAUDE.md").write_text("x", encoding="utf-8")

    pid = _register(client, ws_dir)["id"]
    resp = client.get(f"/projects/{pid}/tree")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["project_id"] == pid
    assert body["root"]["role"] == "root"
    assert body["root"]["id"] == pid

    children = {c["name"]: c for c in body["root"]["children"]}
    assert set(children) == {"sub-1", "nested"}
    assert children["sub-1"]["role"] == "project"
    assert children["sub-1"]["discovery_source"] == "context_file"
    assert children["sub-1"]["id"] is not None
    assert children["nested"]["role"] == "folder"

    nested = children["nested"]["children"][0]
    assert nested["name"] == "deep"
    assert nested["role"] == "project"


def test_tree_registers_subprojects_once(client, ws_dir: Path) -> None:
    (ws_dir / "sub-2").mkdir()
    (ws_dir / "sub-2" / "SAGE.md").write_text("x", encoding="utf-8")

    pid = _register(client, ws_dir)["id"]
    first = client.get(f"/projects/{pid}/tree").json()
    sub_id = first["root"]["children"][0]["id"]
    assert sub_id is not None

    second = client.get(f"/projects/{pid}/tree?refresh=true").json()
    assert second["created_project_ids"] == []
    assert second["root"]["children"][0]["id"] == sub_id

    # 子项目出现在项目清单中，且 parent_id 指向根项目
    listing = {p["id"]: p for p in client.get("/projects").json()["projects"]}
    assert listing[sub_id]["parent_id"] == pid
    assert listing[sub_id]["discovery_source"] == "context_file"


def test_tree_rejects_unknown_project(client) -> None:
    assert client.get("/projects/does-not-exist/tree").status_code == 404


def test_tree_missing_directory_returns_410(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    shutil.rmtree(ws_dir)
    assert client.get(f"/projects/{pid}/tree").status_code == 410
