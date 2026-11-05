"""文件引用路由测试（P5, 2026-11-05 设计 §9.7）。

DB 由 tests/conftest.py 的 autouse ``setup_test_db`` 提供。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import project_reference_routes as prr, project_routes as pr

pytestmark = pytest.mark.unit


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(pr.router)
    app.include_router(prr.router)
    return TestClient(app)


@pytest.fixture()
def ws_dir(tmp_path: Path) -> Path:
    d = tmp_path / "workspace-ref"
    d.mkdir()
    return d


def _register(client: TestClient, path: Path) -> str:
    resp = client.post("/projects", json={"path": str(path)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_list_empty_for_new_project(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)
    resp = client.get(f"/projects/{pid}/references")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"references": []}


def test_create_and_list_reference(client, ws_dir: Path, tmp_path: Path) -> None:
    pid = _register(client, ws_dir)
    target = tmp_path / "external-cases"
    target.mkdir()

    resp = client.post(
        f"/projects/{pid}/references",
        json={
            "rel_path": "data/cases",
            "target_path": str(target),
            "kind": "directory",
            "alias_name": "cases",
        },
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["project_id"] == pid
    assert created["rel_path"] == "data/cases"
    assert created["kind"] == "directory"
    assert created["alias_name"] == "cases"

    listed = client.get(f"/projects/{pid}/references").json()["references"]
    assert [ref["id"] for ref in listed] == [created["id"]]


def test_duplicate_rel_path_returns_409(client, ws_dir: Path, tmp_path: Path) -> None:
    pid = _register(client, ws_dir)
    payload = {"rel_path": "data/cases", "target_path": str(tmp_path)}
    assert client.post(f"/projects/{pid}/references", json=payload).status_code == 201
    resp = client.post(f"/projects/{pid}/references", json=payload)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "reference_exists"


def test_escaping_rel_path_returns_400(client, ws_dir: Path, tmp_path: Path) -> None:
    pid = _register(client, ws_dir)
    resp = client.post(
        f"/projects/{pid}/references",
        json={"rel_path": "../etc", "target_path": str(tmp_path)},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_reference"


def test_relative_target_returns_400(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)
    resp = client.post(
        f"/projects/{pid}/references",
        json={"rel_path": "data/cases", "target_path": "relative/target"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_reference"


def test_delete_reference(client, ws_dir: Path, tmp_path: Path) -> None:
    pid = _register(client, ws_dir)
    ref = client.post(
        f"/projects/{pid}/references",
        json={"rel_path": "data/cases", "target_path": str(tmp_path)},
    ).json()

    resp = client.delete(f"/projects/{pid}/references/{ref['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"removed": True}
    assert client.get(f"/projects/{pid}/references").json() == {"references": []}


def test_delete_unknown_reference_returns_404(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)
    resp = client.delete(f"/projects/{pid}/references/missing-id")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "reference_not_found"


def test_unknown_project_returns_404(client) -> None:
    resp = client.get("/projects/missing-project/references")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "project_not_found"


def test_scan_registers_symlink_references(client, ws_dir: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside-ref"
    outside.mkdir()
    (outside / "a.md").write_text("x", encoding="utf-8")
    os.symlink(str(outside), str(ws_dir / "linked"))
    pid = _register(client, ws_dir)

    resp = client.post(f"/projects/{pid}/scan")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project_id"] == pid
    assert body["scanned"] is True
    assert body["reference_count"] == 1

    refs = client.get(f"/projects/{pid}/references").json()["references"]
    assert [(ref["rel_path"], ref["kind"]) for ref in refs] == [
        ("linked", "symlink")
    ]
    assert refs[0]["target_path"] == os.path.realpath(str(outside))
