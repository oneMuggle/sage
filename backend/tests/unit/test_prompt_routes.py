"""R27-A: Prompt 模板库路由单元测试

monkeypatch SettingsRepository 为 dict-backed fake，覆盖 CRUD 全链、
非空/长度校验、404、上限 100。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import prompt_routes
from backend.api.prompt_routes import router

pytestmark = pytest.mark.unit


class _FakeRepo:
    """类级共享存储 —— 路由每次调用都新建 SettingsRepository，状态需跨实例。"""

    store: dict[str, Any] = {}

    def get_json(self, key: str) -> Any:
        return type(self).store.get(key)

    def set_json(self, key: str, value: Any, category: str = "general") -> None:
        type(self).store[key] = value


@pytest.fixture()
def client(monkeypatch):
    _FakeRepo.store.clear()
    monkeypatch.setattr(prompt_routes, "SettingsRepository", _FakeRepo)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_create_and_list(client):
    res = client.post(
        "/prompts/templates",
        json={"name": "周报", "content": "写一份周报：{{内容}}", "description": "周报模板"},
    )
    assert res.status_code == 200
    tpl = res.json()["template"]
    assert tpl["name"] == "周报"
    assert tpl["content"] == "写一份周报：{{内容}}"

    res = client.get("/prompts/templates")
    assert res.status_code == 200
    assert len(res.json()["templates"]) == 1


def test_create_validation(client):
    # 空 name
    assert client.post("/prompts/templates", json={"name": "", "content": "x"}).status_code == 422
    # 空 content
    assert client.post("/prompts/templates", json={"name": "a", "content": ""}).status_code == 422
    # 超长 content
    assert (
        client.post("/prompts/templates", json={"name": "a", "content": "x" * 8001}).status_code
        == 422
    )


def test_update_and_delete(client):
    created = client.post(
        "/prompts/templates", json={"name": "旧名", "content": "旧内容"}
    ).json()["template"]

    res = client.put(
        f"/prompts/templates/{created['id']}", json={"name": "新名", "content": "新内容"}
    )
    assert res.status_code == 200
    assert res.json()["template"]["name"] == "新名"

    res = client.delete(f"/prompts/templates/{created['id']}")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert client.get("/prompts/templates").json()["templates"] == []


def test_update_delete_missing_returns_404(client):
    assert client.put("/prompts/templates/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/prompts/templates/nope").status_code == 404


def test_cap_at_100(client):
    for i in range(100):
        assert (
            client.post("/prompts/templates", json={"name": f"t{i}", "content": f"c{i}"}).status_code
            == 200
        )
    res = client.post("/prompts/templates", json={"name": "overflow", "content": "x"})
    assert res.status_code == 400
    assert client.get("/prompts/templates").json()["templates"].__len__() == 100
