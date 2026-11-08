"""AI 规则 patch 端点（M5，2026-11-07）。"""

from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from backend.api import project_rules_routes as rules_routes
from backend.data import database as database_module
from backend.data.database import Database
from backend.data.playbook_event_repo import PlaybookEventRepository
from backend.main import app


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch: pytest.MonkeyPatch):
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


async def _rules(client: httpx.AsyncClient, project_id: str) -> dict:
    response = await client.get(f"/api/v1/projects/{project_id}/rules")
    assert response.status_code == 200, response.text
    return {rule["id"]: rule for rule in response.json()["rules"]}


async def test_preview_requires_an_instruction(client: httpx.AsyncClient, project_dir):
    project = await _register(client, project_dir)

    response = await client.post(
        f"/api/v1/projects/{project['id']}/rules/patches/preview",
        json={"instruction": "   "},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_instruction"


async def test_preview_returns_service_output(
    client: httpx.AsyncClient, project_dir, monkeypatch: pytest.MonkeyPatch
):
    project = await _register(client, project_dir)
    await client.post(
        f"/api/v1/projects/{project['id']}/rules",
        json={"layer": "constraint", "content": "统一使用 ruff"},
    )
    captured = {}

    async def fake_preview(project_obj, instruction, entries, *, focus_rule_id=None, llm_client=None):
        captured["instruction"] = instruction
        captured["layers"] = {entry.layer for entry in entries}
        return {"llm_available": True, "message": "", "operations": [{"op_id": "op-1"}]}

    monkeypatch.setattr(rules_routes, "preview_patch", fake_preview)

    response = await client.post(
        f"/api/v1/projects/{project['id']}/rules/patches/preview",
        json={"instruction": "把风格统一"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["operations"] == [{"op_id": "op-1"}]
    assert captured["instruction"] == "把风格统一"
    assert "constraint" in captured["layers"]


async def test_preview_maps_schema_failure_to_422(
    client: httpx.AsyncClient, project_dir, monkeypatch: pytest.MonkeyPatch
):
    project = await _register(client, project_dir)

    async def boom(*args, **kwargs):
        raise rules_routes.PatchSchemaError("AI 返回格式不正确，请重试或手动编辑")

    monkeypatch.setattr(rules_routes, "preview_patch", boom)

    response = await client.post(
        f"/api/v1/projects/{project['id']}/rules/patches/preview",
        json={"instruction": "把风格统一"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "patch_schema_invalid"


async def test_apply_updates_a_constraint(client: httpx.AsyncClient, project_dir):
    project = await _register(client, project_dir)
    base = f"/api/v1/projects/{project['id']}/rules"
    await client.post(base, json={"layer": "constraint", "category": "风格", "content": "统一使用 flake8"})
    rules = await _rules(client, project["id"])
    rule_id, rule = next(iter(rules.items()))

    response = await client.post(
        f"{base}/patches/apply",
        json={
            "instruction": "换成 ruff",
            "operations": [
                {
                    "op_id": "op-1",
                    "action": "update",
                    "layer": "constraint",
                    "rule_id": rule_id,
                    "before": {"content": rule["content"]},
                    "after": {"content": "统一使用 ruff"},
                    "expected_updated_at": rule["updated_at"],
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] == 1
    assert body["failed"] == 0
    assert body["results"][0]["status"] == "applied"
    assert (await _rules(client, project["id"]))[rule_id]["content"] == "统一使用 ruff"


async def test_apply_conflict_does_not_overwrite(client: httpx.AsyncClient, project_dir):
    project = await _register(client, project_dir)
    base = f"/api/v1/projects/{project['id']}/rules"
    await client.post(base, json={"layer": "constraint", "content": "统一使用 flake8"})
    rules = await _rules(client, project["id"])
    rule_id, rule = next(iter(rules.items()))

    response = await client.post(
        f"{base}/patches/apply",
        json={
            "instruction": "换成 ruff",
            "operations": [
                {
                    "op_id": "op-1",
                    "action": "update",
                    "layer": "constraint",
                    "rule_id": rule_id,
                    "after": {"content": "统一使用 ruff"},
                    "expected_updated_at": int(rule["updated_at"]) - 1,
                }
            ],
        },
    )

    body = response.json()
    assert body["applied"] == 0
    assert body["results"][0]["status"] == "conflict"
    assert body["results"][0]["current"]["content"] == "统一使用 flake8"
    assert (await _rules(client, project["id"]))[rule_id]["content"] == "统一使用 flake8"


async def test_apply_rejects_the_readonly_playbook_layer(
    client: httpx.AsyncClient, project_dir
):
    project = await _register(client, project_dir)

    response = await client.post(
        f"/api/v1/projects/{project['id']}/rules/patches/apply",
        json={
            "instruction": "改规程规则",
            "operations": [
                {
                    "op_id": "op-1",
                    "action": "update",
                    "layer": "playbook",
                    "rule_id": "playbook:design:0",
                    "after": {"content": "随便"},
                }
            ],
        },
    )

    body = response.json()
    assert body["applied"] == 0
    assert body["results"][0]["status"] == "invalid"


async def test_apply_partial_success_keeps_going(client: httpx.AsyncClient, project_dir):
    project = await _register(client, project_dir)
    base = f"/api/v1/projects/{project['id']}/rules"
    await client.post(base, json={"layer": "constraint", "content": "统一使用 flake8"})
    rules = await _rules(client, project["id"])
    rule_id, rule = next(iter(rules.items()))

    response = await client.post(
        f"{base}/patches/apply",
        json={
            "instruction": "统一风格",
            "operations": [
                {
                    "op_id": "op-1",
                    "action": "update",
                    "layer": "constraint",
                    "rule_id": rule_id,
                    "after": {"content": "统一使用 ruff"},
                    "expected_updated_at": rule["updated_at"],
                },
                {
                    "op_id": "op-2",
                    "action": "delete",
                    "layer": "constraint",
                    "rule_id": "constraint:00000000-0000-4000-8000-000000000000",
                },
            ],
        },
    )

    body = response.json()
    assert body["applied"] == 1
    assert body["failed"] == 1
    assert [item["status"] for item in body["results"]] == ["applied", "invalid"]


async def test_apply_updates_a_project_doc_section(client: httpx.AsyncClient, project_dir):
    project = await _register(client, project_dir)
    base = f"/api/v1/projects/{project['id']}/rules"
    created = await client.post(base, json={"layer": "doc", "category": "风格", "content": "使用黑体"})
    assert created.status_code == 201, created.text
    rules = await _rules(client, project["id"])
    doc_id = next(rule_id for rule_id in rules if rule_id.startswith("doc:"))

    response = await client.post(
        f"{base}/patches/apply",
        json={
            "instruction": "换字体",
            "operations": [
                {
                    "op_id": "op-1",
                    "action": "update",
                    "layer": "doc",
                    "rule_id": doc_id,
                    "before": {"content": rules[doc_id]["content"]},
                    "after": {"content": "使用宋体"},
                }
            ],
        },
    )

    assert response.json()["applied"] == 1
    assert (await _rules(client, project["id"]))[doc_id]["content"] == "使用宋体"


async def test_apply_records_an_activity_event(client: httpx.AsyncClient, project_dir):
    project = await _register(client, project_dir)
    base = f"/api/v1/projects/{project['id']}/rules"
    await client.post(base, json={"layer": "constraint", "content": "统一使用 flake8"})
    rules = await _rules(client, project["id"])
    rule_id, rule = next(iter(rules.items()))

    response = await client.post(
        f"{base}/patches/apply",
        json={
            "instruction": "换成 ruff",
            "operations": [
                {
                    "op_id": "op-1",
                    "action": "update",
                    "layer": "constraint",
                    "rule_id": rule_id,
                    "after": {"content": "统一使用 ruff"},
                    "expected_updated_at": rule["updated_at"],
                }
            ],
        },
    )
    assert response.json()["applied"] == 1

    events = PlaybookEventRepository().list_recent(project["id"])
    event = next(item for item in events if item.event == "rules_ai_apply")
    assert event.payload["applied"] == 1
    assert event.payload["instruction"] == "换成 ruff"
