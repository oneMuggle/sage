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
        f"/api/v1/projects/{project_id}/playbook",
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

    audit = await client.get("/api/v1/projects/{}/playbook/audit".format(project["id"]))
    assert audit.status_code == 200
    data = audit.json()
    proposal = next(stage for stage in data["stages"] if stage["id"] == "proposal")
    report = next(item for item in proposal["artifacts"] if item["id"] == "proposal_report")
    assert report["status"] == "present"
    assert report["evidence"]["matches"] == ["01_开题/开题报告.md"]


@pytest.mark.asyncio()
async def test_bind_projects_rules_and_stage_adds_more(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])
    first = await client.get(
        "/api/v1/projects/{}/constraints".format(project["id"])
    )
    assert first.status_code == 200
    contents = [item["content"] for item in first.json()["constraints"]]
    assert any("DOI" in item for item in contents)
    before = len(contents)

    confirmed = await client.post(
        "/api/v1/projects/{}/playbook/stage/confirm".format(project["id"]),
        json={"stage_id": "execution"},
    )
    assert confirmed.status_code == 200, confirmed.text

    second = await client.get(
        "/api/v1/projects/{}/constraints".format(project["id"])
    )
    contents = [item["content"] for item in second.json()["constraints"]]
    assert len(contents) > before
    assert any("随机种子" in item for item in contents)


@pytest.mark.asyncio()
async def test_state_update_waiver_and_manual_done(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])
    response = await client.patch(
        "/api/v1/projects/{}/playbook/state".format(project["id"]),
        json={
            "waivers": ["proposal.proposal_report"],
            "manual_done": ["proposal.literature_matrix_ready"],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["state"]["waivers"] == ["proposal.proposal_report"]
    proposal = next(stage for stage in payload["audit"]["stages"] if stage["id"] == "proposal")
    report = next(item for item in proposal["artifacts"] if item["id"] == "proposal_report")
    assert report["status"] == "waived"
    criterion = next(
        item for item in proposal["exit_criteria"] if item["id"] == "literature_matrix_ready"
    )
    assert criterion["status"] == "done"


@pytest.mark.asyncio()
async def test_unbind_and_version_history(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])
    versions = await client.get(
        "/api/v1/projects/{}/playbook/versions".format(project["id"])
    )
    assert versions.status_code == 200
    assert len(versions.json()["versions"]) == 1
    assert versions.json()["versions"][0]["active"] is True

    unbound = await client.delete(
        "/api/v1/projects/{}/playbook".format(project["id"])
    )
    assert unbound.status_code == 200
    assert unbound.json()["bound"] is False

    versions = await client.get(
        "/api/v1/projects/{}/playbook/versions".format(project["id"])
    )
    assert versions.json()["versions"][0]["active"] is False


@pytest.mark.asyncio()
async def test_cleanup_playbook_rules(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])
    constraints = await client.get(
        "/api/v1/projects/{}/constraints".format(project["id"])
    )
    assert any(
        str(item.get("source", "")).startswith("playbook:")
        for item in constraints.json()["constraints"]
    )
    cleanup = await client.post(
        "/api/v1/projects/{}/playbook/rules/cleanup".format(project["id"])
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["removed"] > 0
    constraints = await client.get(
        "/api/v1/projects/{}/constraints".format(project["id"])
    )
    assert not any(
        str(item.get("source", "")).startswith("playbook:")
        for item in constraints.json()["constraints"]
    )


@pytest.mark.asyncio()
async def test_project_patch_stage_syncs_playbook_state(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])
    patched = await client.patch(
        "/api/v1/projects/{}".format(project["id"]),
        json={"project_stage": "execution"},
    )
    assert patched.status_code == 200, patched.text
    current = await client.get(
        "/api/v1/projects/{}/playbook".format(project["id"])
    )
    assert current.json()["state"]["current_stage"] == "execution"
    constraints = await client.get(
        "/api/v1/projects/{}/constraints".format(project["id"])
    )
    assert any("随机种子" in item["content"] for item in constraints.json()["constraints"])


@pytest.mark.asyncio()
async def test_actions_apply_and_stage_confirm(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])

    applied = await client.post(
        "/api/v1/projects/{}/playbook/actions/apply".format(project["id"]),
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
        "/api/v1/projects/{}/playbook/stage/confirm".format(project["id"]),
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
        "/api/v1/projects/{}/playbook/export?format=json".format(project["id"])
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
        "/api/v1/projects/{}/playbook/export?format=md".format(project["id"])
    )
    assert exported.status_code == 200
    assert "开题" in exported.json()["content"]


@pytest.mark.asyncio()
async def test_author_preview_deterministic(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    response = await client.post(
        f"/api/v1/projects/{project['id']}/playbook/author/preview",
        json={"answers": {"name": "我的规程"}, "use_llm": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source"] == "deterministic"
    assert payload["playbook"]["name"] == "我的规程"
    assert payload["playbook"]["stages"]


@pytest.mark.asyncio()
async def test_audit_ai_falls_back_without_llm(
    client: httpx.AsyncClient, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.orchestration import llm_factory

    project = await _register(client, project_dir)
    await _bind(client, project["id"])
    monkeypatch.setattr(llm_factory, "build_llm_client_from_settings", lambda: None)
    response = await client.post(
        "/api/v1/projects/{}/playbook/audit/ai".format(project["id"]),
        json={"use_llm": True},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["llm_available"] is False
    assert payload["stages"]


@pytest.mark.asyncio()
async def test_wiki_export_creates_and_updates(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])
    first = await client.post(
        "/api/v1/projects/{}/playbook/wiki/export".format(project["id"])
    )
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True
    page = project_dir / "wiki" / "guides" / "playbook-handbook.md"
    assert page.is_file()
    text = page.read_text(encoding="utf-8")
    assert "generator: sage" in text
    assert "开题" in text

    second = await client.post(
        "/api/v1/projects/{}/playbook/wiki/export".format(project["id"])
    )
    assert second.status_code == 200
    assert second.json()["updated"] is True


@pytest.mark.asyncio()
async def test_wiki_export_refuses_user_page(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])
    page = project_dir / "wiki" / "guides" / "playbook-handbook.md"
    page.parent.mkdir(parents=True)
    page.write_text("# 用户手写内容", encoding="utf-8")

    response = await client.post(
        "/api/v1/projects/{}/playbook/wiki/export".format(project["id"])
    )
    assert response.status_code == 409
    assert page.read_text(encoding="utf-8") == "# 用户手写内容"


@pytest.mark.asyncio()
async def test_export_agents_markdown(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    await _bind(client, project["id"])
    exported = await client.get(
        "/api/v1/projects/{}/playbook/export?format=agents".format(project["id"])
    )
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["format"] == "agents"
    assert payload["filename"].endswith("-AGENTS.md")
    assert "AI 协同约定" in payload["content"]


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
