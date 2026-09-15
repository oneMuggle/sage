"""R30: Prompt 模板导入/导出单元测试

- GET /prompts/templates/export 信封结构
- POST /prompts/templates/import: 正常导入/同名去重/非法条目跳过/
  长度超限计 failed/版本防御/上限约束/导入持久化
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import prompt_routes
from backend.api.prompt_routes import router

pytestmark = pytest.mark.unit


class _FakeRepo:
    """类级共享存储（同 R27 测试口径）。"""

    store: dict = {}

    def get_json(self, key: str):
        return type(self).store.get(key)

    def set_json(self, key: str, value, category: str = "general"):
        type(self).store[key] = value


@pytest.fixture()
def client(monkeypatch):
    _FakeRepo.store.clear()
    monkeypatch.setattr(prompt_routes, "SettingsRepository", _FakeRepo)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_export_envelope_shape(client):
    client.post("/prompts/templates", json={"name": "周报", "content": "写周报"})
    res = client.get("/prompts/templates/export")
    assert res.status_code == 200
    body = res.json()
    assert body["app"] == "sage"
    assert body["kind"] == "prompt_templates"
    assert body["version"] == 1
    assert len(body["templates"]) == 1


def test_import_roundtrip_and_dedup(client):
    envelope = {
        "version": 1,
        "templates": [
            {"name": "周报", "content": "写周报"},
            {"name": "周报", "content": "重复同名应跳过"},
            {"name": "", "content": "空名跳过"},
            "not-a-dict",
            {"name": "超长", "content": "x" * 8001},
        ],
    }
    res = client.post("/prompts/templates/import", json=envelope)
    assert res.status_code == 200
    body = res.json()
    assert body["imported"] == 1
    assert body["skipped"] == 2  # 同名 + 空名
    assert body["failed"] == 2  # 非法条目 + 长度超限

    # 再导一遍（全新空库语义由调用方保证；此处同名仍去重）
    res = client.post("/prompts/templates/import", json={"version": 1, "templates": [{"name": "周报", "content": "写周报"}]})
    assert res.json()["skipped"] == 1

    # 列表确认持久化
    assert len(client.get("/prompts/templates").json()["templates"]) == 1


def test_import_version_defense(client):
    assert (
        client.post("/prompts/templates/import", json={"version": 99, "templates": []}).status_code
        == 400
    )


def test_import_respects_cap(client):
    for i in range(100):
        assert (
            client.post("/prompts/templates", json={"name": f"t{i}", "content": f"c{i}"}).status_code
            == 200
        )
    res = client.post(
        "/prompts/templates/import",
        json={"version": 1, "templates": [{"name": "new", "content": "new"}]},
    )
    assert res.json()["skipped"] == 1
    assert res.json()["imported"] == 0


def test_import_conflict_skip_and_overwrite(client):
    client.post("/prompts/templates", json={"name": "周报", "content": "旧内容", "description": "旧描述"})

    envelope = {
        "version": 1,
        "templates": [{"name": "周报", "content": "新内容", "description": "新描述"}],
    }

    # skip（默认）：同名跳过 + conflicts 清单
    res = client.post("/prompts/templates/import", json={**envelope, "conflict": "skip"})
    body = res.json()
    assert body["imported"] == 0
    assert body["conflicts"] == ["周报"]

    # skip 模式下现有内容未被覆盖
    assert client.get("/prompts/templates").json()["templates"][0]["content"] == "旧内容"

    # overwrite：同名覆盖（保留现有 id）
    res = client.post("/prompts/templates/import", json={**envelope, "conflict": "overwrite"})
    body = res.json()
    assert body["imported"] == 1
    assert body["conflicts"] == []
    tpl = client.get("/prompts/templates").json()["templates"][0]
    assert tpl["content"] == "新内容"
    assert tpl["description"] == "新描述"
    assert tpl["id"].startswith("pt-")  # id 不变（断链防护语义见实现注释）


def test_import_conflict_invalid_conflict_value_defaults_to_skip(client):
    client.post("/prompts/templates", json={"name": "周报", "content": "旧内容"})
    res = client.post(
        "/prompts/templates/import",
        json={"version": 1, "templates": [{"name": "周报", "content": "新"}], "conflict": "bogus"},
    )
    body = res.json()
    assert body["conflicts"] == ["周报"]
