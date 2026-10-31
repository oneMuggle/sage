"""Integration tests for playbook HTTP routes (2026-10-31)."""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from backend.data import database as database_module
from backend.data.database import Database
from backend.main import app


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


async def _bind(client: httpx.AsyncClient, project_id: str) -> dict:
    response = await client.put(
        "/api/v1/projects/%s/playbook" % project_id,
        json={"playbook_id": "cn-research-grant"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio()
async def test_builtin_list_and_detail(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/playbooks/builtin")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["playbooks"]}
    assert {"cn-research-grant", "coding-project"} <= ids

    detail = await client.get("/api/v1/playbooks/builtin/cn-research-grant")
    assert detail.status_code == 200
    assert detail.json()["playbook"]["stages"][0]["id"] == "proposal"

    missing = await client.get("/api/v1/playbooks/builtin/nope")
    assert missing.status_code == 404


@pytest.mark.asyncio()
async def test_bind_and_audit_reflect_files(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    bound = await _bind(client, project["id"])
    assert bound["bound"] is True
    assert bound["version"] == 1
    assert bound["state"]["current_stage"] == "proposal"
    assert bound["audit"]["overall"]["required_total"] > 0

    proposal_dir = project_dir / "01_开题"
    proposal_dir.mkdir()
    (proposal_dir / "开题报告.md").write_text(
        "研究问题\n科学假设\n技术路线", encoding="utf-8"
    )

    audit = await client.get("/api/v1/projects/%s/playbook/audit" % project["id"])
    assert audit.status_code == 200
    data = audit.json()
    proposal = next(stage for stage in data["stages"] if stage["id"] == "proposal")
    report = next(item for item in proposal["artifacts"] if item["id"] == "proposal_report")
    assert report["status"] == "present"
    assert report["evidence"]["matches"] == ["01_开题/开题报告.md"]


@pytest.mark.asyncio()
async def test_actions_apply_and_stage_confirm(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])

    applied = await client.post(
        "/api/v1/projects/%s/playbook/actions/apply" % project["id"],
        json={
            "actions": [
                {"type": "create_folder", "payload": {"path": "02_实施/数据"}},
                {
                    "type": "create_doc_stub",
                    "payload": {
                        "path": "02_实施/实验记录.md",
                        "template": "experiment_log",
                    },
                },
            ]
        },
    )
    assert applied.status_code == 200, applied.text
    assert "create_folder" in applied.json()["applied"]
    assert (project_dir / "02_实施" / "数据").is_dir()
    assert (project_dir / "02_实施" / "实验记录.md").is_file()

    confirmed = await client.post(
        "/api/v1/projects/%s/playbook/stage/confirm" % project["id"],
        json={"stage_id": "execution"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["state"]["current_stage"] == "execution"

    project_after = await client.get("/api/v1/projects")
    assert project_after.status_code == 200
    listed = next(
        item for item in project_after.json()["projects"] if item["id"] == project["id"]
    )
    assert listed["project_stage"] == "execution"


@pytest.mark.asyncio()
async def test_export_and_import_preview(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])

    exported = await client.get(
        "/api/v1/projects/%s/playbook/export?format=json" % project["id"]
    )
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["format"] == "json"
    envelope = payload["content"]
    assert envelope["format"] == "sage.playbook"
    assert envelope["scaffold"]["directories"]

    preview = await client.post(
        "/api/v1/playbooks/import/preview",
        json={"envelope": envelope, "project_id": project["id"]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["playbook"]["id"] == "cn-research-grant"

    imported = await client.post(
        "/api/v1/playbooks/import",
        json={
            "envelope": envelope,
            "project_id": project["id"],
            "conflict": "save_as_new",
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["version"] == 2


@pytest.mark.asyncio()
async def test_export_markdown(client: httpx.AsyncClient, project_dir: Path) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])
    exported = await client.get(
        "/api/v1/projects/%s/playbook/export?format=md" % project["id"]
    )
    assert exported.status_code == 200
    assert "开题" in exported.json()["content"]


@pytest.mark.asyncio()
async def test_import_rejects_unsafe_scaffold(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    envelope = {
        "format": "sage.playbook",
        "schema_version": "1.0",
        "playbook": {
            "schema_version": "1.0",
            "id": "evil",
            "name": "evil",
            "stages": [{"id": "s1", "label": "S1", "artifacts": []}],
        },
        "scaffold": {"include": True, "directories": ["../escape"]},
    }
    response = await client.post(
        "/api/v1/playbooks/import/preview",
        json={"envelope": envelope, "project_id": project["id"]},
    )
    assert response.status_code == 400
    assert not (project_dir.parent / "escape").exists()
