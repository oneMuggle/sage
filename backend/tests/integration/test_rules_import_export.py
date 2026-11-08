# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""规则导入/导出端点集成测试（M6，2026-11-07）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from backend.api import rules_routes  # noqa: F401 — 确保路由注册
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


def _constraint(category: str, content: str) -> dict:
    return {
        "category": category,
        "content": content,
        "priority": 5,
        "enabled": True,
        "trigger_pattern": None,
    }


async def test_export_json_default_format(client: httpx.AsyncClient, project_dir):
    project = await _register(client, project_dir)
    await client.post(
        f"/api/v1/projects/{project['id']}/rules",
        json={"layer": "constraint", "content": "统一使用 ruff", "category": "风格"},
    )

    response = await client.get(f"/api/v1/projects/{project['id']}/rules/export")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "sage.rules"
    assert body["filename"].endswith(".sagerules.json")
    content = body["content"]
    assert isinstance(content, str)
    payload = json.loads(content)
    assert payload["format"] == "sage.rules"
    assert any(
        item["content"] == "统一使用 ruff"
        for item in payload["layers"]["constraints"]
    )


async def test_export_md_returns_markdown_content(
    client: httpx.AsyncClient, project_dir
):
    project = await _register(client, project_dir)
    await client.post(
        f"/api/v1/projects/{project['id']}/rules",
        json={"layer": "constraint", "content": "统一使用 ruff"},
    )

    response = await client.get(
        f"/api/v1/projects/{project['id']}/rules/export?format=md"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"].endswith(".sagerules.md")
    assert "ruff" in body["content"]


async def test_export_agents_includes_project_rules(
    client: httpx.AsyncClient, project_dir
):
    project = await _register(client, project_dir)
    await client.post(
        f"/api/v1/projects/{project['id']}/rules",
        json={"layer": "constraint", "content": "一行一个 commit"},
    )

    response = await client.get(
        f"/api/v1/projects/{project['id']}/rules/export?format=agents"
    )

    assert response.status_code == 200, response.text
    assert "commit" in response.json()["content"]


async def test_preview_returns_candidates_without_writing(
    client: httpx.AsyncClient, project_dir
):
    project = await _register(client, project_dir)
    envelope = {
        "format": "sage.rules",
        "version": 1,
        "layers": {
            "constraints": [
                {
                    "category": "风格",
                    "content": "统一使用 ruff",
                    "priority": 5,
                    "enabled": True,
                    "trigger_pattern": None,
                },
            ],
            "project_docs": {},
            "global_rules": "",
        },
    }

    response = await client.post(
        "/api/v1/rules/import/preview",
        json={"envelope": envelope, "project_id": project["id"]},
    )

    assert response.status_code == 200, response.text
    candidates = response.json()["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["status"] == "new"
    # preview 不写库
    rules_resp = await client.get(f"/api/v1/projects/{project['id']}/rules")
    assert rules_resp.json()["rules"] == []


async def test_preview_rejects_wrong_format(
    client: httpx.AsyncClient, project_dir
):
    project = await _register(client, project_dir)

    response = await client.post(
        "/api/v1/rules/import/preview",
        json={
            "envelope": {"format": "sage.playbook", "version": 1, "layers": {}},
            "project_id": project["id"],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "rules_import_invalid"


async def test_apply_writes_selected_constraints_only(
    client: httpx.AsyncClient, project_dir
):
    project = await _register(client, project_dir)
    envelope = {
        "format": "sage.rules",
        "version": 1,
        "layers": {
            "constraints": [
                _constraint("风格", "统一使用 ruff"),
                _constraint("提交", "一行一个 commit"),
            ],
            "project_docs": {},
            "global_rules": "",
        },
    }

    preview = await client.post(
        "/api/v1/rules/import/preview",
        json={"envelope": envelope, "project_id": project["id"]},
    )
    first_id = preview.json()["candidates"][0]["id"]

    apply_response = await client.post(
        "/api/v1/rules/import/apply",
        json={
            "envelope": envelope,
            "project_id": project["id"],
            "selected": [first_id],
            "overwrite": False,
        },
    )

    assert apply_response.status_code == 200, apply_response.text
    body = apply_response.json()
    assert body["applied"] == 1
    assert body["failed"] == 0

    rules_resp = await client.get(f"/api/v1/projects/{project['id']}/rules")
    contents = [
        rule["content"]
        for rule in rules_resp.json()["rules"]
        if rule["layer"] == "constraint"
    ]
    assert "统一使用 ruff" in contents
    assert "一行一个 commit" not in contents


async def test_apply_records_activity_event(
    client: httpx.AsyncClient, project_dir
):
    project = await _register(client, project_dir)
    envelope = {
        "format": "sage.rules",
        "version": 1,
        "layers": {
            "constraints": [
                {
                    "category": "风格",
                    "content": "统一使用 ruff",
                    "priority": 5,
                    "enabled": True,
                    "trigger_pattern": None,
                },
            ],
            "project_docs": {},
            "global_rules": "",
        },
    }

    await client.post(
        "/api/v1/rules/import/apply",
        json={
            "envelope": envelope,
            "project_id": project["id"],
            "selected": ["import-constraint-0"],
            "overwrite": False,
        },
    )

    events = PlaybookEventRepository().list_recent(project["id"])
    event = next(item for item in events if item.event == "rules_import")
    assert event.payload["applied"] == 1


async def test_apply_duplicate_is_skipped_without_error(
    client: httpx.AsyncClient, project_dir
):
    project = await _register(client, project_dir)
    await client.post(
        f"/api/v1/projects/{project['id']}/rules",
        json={"layer": "constraint", "category": "风格", "content": "统一使用 ruff"},
    )
    envelope = {
        "format": "sage.rules",
        "version": 1,
        "layers": {
            "constraints": [
                {
                    "category": "风格",
                    "content": "统一使用 ruff",
                    "priority": 5,
                    "enabled": True,
                    "trigger_pattern": None,
                },
            ],
            "project_docs": {},
            "global_rules": "",
        },
    }

    preview = await client.post(
        "/api/v1/rules/import/preview",
        json={"envelope": envelope, "project_id": project["id"]},
    )
    candidate_id = preview.json()["candidates"][0]["id"]
    assert preview.json()["candidates"][0]["status"] == "duplicate"

    response = await client.post(
        "/api/v1/rules/import/apply",
        json={
            "envelope": envelope,
            "project_id": project["id"],
            "selected": [candidate_id],
            "overwrite": False,
        },
    )

    body = response.json()
    assert body["applied"] == 0
    assert body["results"][0]["status"] == "skipped"


async def test_apply_rejects_doc_candidate_outside_whitelist(
    client: httpx.AsyncClient, project_dir
):
    """R47(k)：doc 导入只允许 SAGE.md；CLAUDE.md/AGENTS.md 应 failed。"""
    project = await _register(client, project_dir)
    envelope = {
        "format": "sage.rules",
        "version": 1,
        "layers": {
            "constraints": [],
            "project_docs": {"CLAUDE.md": "some content"},
            "global_rules": "",
        },
    }

    response = await client.post(
        "/api/v1/rules/import/apply",
        json={
            "envelope": envelope,
            "project_id": project["id"],
            "selected": ["import-doc-CLAUDE.md"],
            "overwrite": False,
        },
    )

    body = response.json()
    assert body["results"][0]["status"] == "failed"
    # 文件没有被创建
    assert not (project_dir / "CLAUDE.md").exists()
