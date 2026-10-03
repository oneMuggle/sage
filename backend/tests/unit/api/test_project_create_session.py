"""POST /projects/{project_id}/sessions — 在项目下显式新建会话（侧栏项目行的「+」）。

与 ``/open`` 的区别是本文件存在的理由：open 优先复用最近活跃会话，本端点每次都新建。
此前桥里有 projects_create_session 这条映射却没有对应的后端路由（404），
IPC 契约门禁（backend/tests/contract/test_ipc_manifest_routes.py）把这个缺口登记为已知缺口。
DB 由 tests/conftest.py 的 autouse ``setup_test_db`` 提供。
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


def _register(client: TestClient, path: Path) -> str:
    resp = client.post("/projects", json={"path": str(path)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_create_session_always_creates_a_new_session(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)
    first = client.post(f"/projects/{pid}/sessions")
    second = client.post(f"/projects/{pid}/sessions")
    assert first.status_code == 201
    assert second.status_code == 201
    a, b = first.json(), second.json()
    assert a["created"] is True
    assert b["created"] is True
    assert a["session"]["id"] != b["session"]["id"]
    assert a["session"]["title"] == "workspace-a"  # 与 open 一致：标题取项目名
    assert a["project"]["id"] == pid


def test_create_session_does_not_reuse_unlike_open(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)
    opened = client.post(f"/projects/{pid}/open").json()
    created = client.post(f"/projects/{pid}/sessions").json()
    assert created["created"] is True
    assert created["session"]["id"] != opened["session"]["id"]  # 已有会话时 open 会复用，这里不会
    # open 之后仍按"复用最近会话"语义工作：不新建
    reopened = client.post(f"/projects/{pid}/open").json()
    assert reopened["created"] is False
    assert reopened["session"]["id"] in {opened["session"]["id"], created["session"]["id"]}


def test_created_sessions_are_bound_to_the_project(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)
    a = client.post(f"/projects/{pid}/sessions").json()
    b = client.post(f"/projects/{pid}/sessions").json()
    listed = client.get(f"/projects/{pid}/sessions").json()["sessions"]
    assert {s["id"] for s in listed} == {a["session"]["id"], b["session"]["id"]}
    # 响应里的项目聚合是新建之后的：1 -> 2
    assert a["project"]["session_count"] == 1
    assert b["project"]["session_count"] == 2


def test_create_session_unknown_project(client) -> None:
    resp = client.post("/projects/nope/sessions")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "project_not_found"


def test_create_session_path_missing(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)
    shutil.rmtree(ws_dir)
    resp = client.post(f"/projects/{pid}/sessions")
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "project_path_missing"
    # 目录没了就不该留下孤儿会话
    assert client.get(f"/projects/{pid}/sessions").json()["sessions"] == []
