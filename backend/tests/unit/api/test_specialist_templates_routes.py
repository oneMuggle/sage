# ruff: noqa: UP006, UP007 — release/win7 Python 3.8 兼容
"""M4-T2 — 内置模板库路由测试（GET /specialists/templates、
POST /specialists/templates/{id}/instantiate）。

使用真实临时库（conftest autouse ``setup_test_db``）与最小 FastAPI app，
``SAGE_SPECIALISTS_DIR`` 指向 tmp_path 避免污染用户目录。覆盖：
- 列表返回 6 个模板（sage-guide 首位），不含 system_prompt
- 一键实例化 201 + 返回 id/name/template_id/dropped_bindings
- 未知模板 404；非法 id 404
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.specialist_routes import router as specialist_router

pytestmark = pytest.mark.unit


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    root = tmp_path / "specialists"
    root.mkdir()
    monkeypatch.setenv("SAGE_SPECIALISTS_DIR", str(root))
    app = FastAPI()
    app.include_router(specialist_router)
    return TestClient(app)


def test_list_templates_returns_six(client: TestClient) -> None:
    resp = client.get("/specialists/templates")
    assert resp.status_code == 200, resp.text
    templates = resp.json()["templates"]
    assert [t["id"] for t in templates] == [
        "sage-guide",
        "writing",
        "research",
        "coding",
        "presentation",
        "office",
    ]
    for t in templates:
        assert "system_prompt" not in t


def test_instantiate_returns_201_and_profile_ref(client: TestClient) -> None:
    resp = client.post("/specialists/templates/writing/instantiate")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"].startswith("specialist-writing-")
    assert body["name"] == "写作专家"
    assert body["template_id"] == "writing"
    assert body["dropped_bindings"] == 0


def test_instantiate_unknown_template_404(client: TestClient) -> None:
    resp = client.post("/specialists/templates/nonexistent/instantiate")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["type"] == "template_not_found"


def test_instantiate_invalid_id_404(client: TestClient) -> None:
    resp = client.post("/specialists/templates/..%2Fetc/instantiate")
    assert resp.status_code == 404, resp.text
