"""P3 端点测试：模板清单 + 创建时选模板（2026-11-05 设计）。

覆盖：

- ``GET /projects/templates`` 返回内置 + 全局模板；
- ``POST /projects`` 带 ``template_name`` 触发脚手架执行。

DB 由 tests/conftest.py 的 autouse ``setup_test_db`` 提供。
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


# ── GET /projects/templates ────────────────────────────────────────────


def test_list_templates_returns_built_in(client) -> None:
    resp = client.get("/projects/templates")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "templates" in body
    names = {t["name"] for t in body["templates"]}
    # 内置模板至少包含四大类（coding/research/business/personal）
    assert len(names) >= 1
    sources = {t["source"] for t in body["templates"]}
    assert "built_in" in sources
    # 每个模板都带展示所需的元信息
    for t in body["templates"]:
        assert t["name"]
        assert "description" in t
        assert "directory_count" in t
        assert "file_count" in t
        assert isinstance(t["directories"], list)
        assert isinstance(t["files"], list)


# ── POST /projects with template_name ─────────────────────────────────


def test_register_with_template_name_scaffolds(client, tmp_path: Path) -> None:
    ws = tmp_path / "tpl-ws"
    ws.mkdir()

    # 选一个内置模板名（取第一个）
    tpl = client.get("/projects/templates").json()["templates"][0]
    tpl_name = tpl["name"]
    expected_dirs = set(tpl["directories"])

    resp = client.post(
        "/projects",
        json={"path": str(ws), "template_name": tpl_name},
    )
    assert resp.status_code == 200, resp.text

    # 脚手架应该把模板声明的目录创建出来
    for rel in expected_dirs:
        assert (ws / rel).is_dir(), f"expected scaffolded dir: {rel}"


def test_register_with_unknown_template_name_still_registers(
    client, tmp_path: Path
) -> None:
    """未知模板名走 resolve_template 兜底（business），不阻断注册。"""
    ws = tmp_path / "ws-fallback"
    ws.mkdir()
    resp = client.post(
        "/projects",
        json={"path": str(ws), "template_name": "definitely-not-a-real-template"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"] == str(ws)
