"""register_project 默认 allowed_paths 预填逻辑的单元测试。

从 `test_project_routes.py` 拆出，保持单文件 ≤800 行（架构行数棘轮）。
"""

from __future__ import annotations

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


def _register(client: TestClient, path: Path, **extra) -> dict:
    resp = client.post("/projects", json={"path": str(path), **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_register_prefills_default_allowed_paths(client, ws_dir: Path, monkeypatch) -> None:
    """未提供 allowed_paths 时预填默认值（工作区外访问减少审批）。"""
    monkeypatch.setattr(pr, "default_allowed_paths", lambda: ["~/Documents/**"])

    body = _register(client, ws_dir)

    assert body["allowed_paths"] == ["~/Documents/**"]


def test_register_respects_explicit_empty_allowed_paths(
    client, ws_dir: Path, monkeypatch
) -> None:
    """显式 [] 表示用户选择清空，不预填默认值。"""
    monkeypatch.setattr(pr, "default_allowed_paths", lambda: ["~/Documents/**"])

    body = _register(client, ws_dir, allowed_paths=[])

    assert body["allowed_paths"] == []


def test_register_keeps_explicit_allowed_paths(client, ws_dir: Path, monkeypatch) -> None:
    """显式自定义列表不被默认值覆盖。"""
    monkeypatch.setattr(pr, "default_allowed_paths", lambda: ["~/Documents/**"])

    body = _register(client, ws_dir, allowed_paths=["/data/**"])

    assert body["allowed_paths"] == ["/data/**"]
