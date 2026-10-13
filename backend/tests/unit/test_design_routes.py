"""Integration tests for design studio HTTP routes.

Uses httpx.AsyncClient with app=app to exercise all 8 endpoints:
- GET  /api/v1/design/systems
- GET  /api/v1/design/templates
- GET  /api/v1/design/projects
- POST /api/v1/design/projects
- GET  /api/v1/design/projects/:id
- DELETE /api/v1/design/projects/:id
- POST /api/v1/design/projects/:id/generate
- POST /api/v1/design/projects/:id/iterate
"""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.data.design_repo import DesignRepo
from backend.design.design_studio import DesignStudio
from backend.design.generator import DesignGenerator
from backend.design.systems import DesignSystemRegistry
from backend.design.templates import DesignTemplateRegistry

# ---------------------------------------------------------------------------
# Fixture: build a fully-wired DesignStudio backed by tmp SQLite + mock LLM
# ---------------------------------------------------------------------------


def _build_studio(tmp_path):
    db = sqlite3.connect(str(tmp_path / "test.db"))
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("""CREATE TABLE design_projects (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
        system_id TEXT NOT NULL, template_id TEXT NOT NULL,
        brief TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE design_artifacts (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
        version INTEGER NOT NULL, file_path TEXT NOT NULL,
        kind TEXT NOT NULL, title TEXT NOT NULL,
        export_formats TEXT NOT NULL DEFAULT '[]',
        source_prompt TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE(project_id, version))""")
    db.commit()
    repo = DesignRepo(db)

    content_dir = tmp_path / "content"
    sys_dir = content_dir / "systems" / "test-sys"
    sys_dir.mkdir(parents=True)
    (sys_dir / "DESIGN.md").write_text("# Test")
    (sys_dir / "tokens.css").write_text(":root { --bg: #fff; }")
    (sys_dir / "manifest.json").write_text(json.dumps({
        "id": "test-sys", "name": "Test System",
        "category": "general", "description": "test", "tags": [],
    }))

    tpl_dir = content_dir / "templates" / "prototype" / "test-page"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "SKILL.md").write_text(
        "---\nname: test-page\nkind: prototype\n"
        "description: test\ndesign_system_required: true\n---\n"
        "# Test"
    )

    systems_reg = DesignSystemRegistry(content_dir)
    templates_reg = DesignTemplateRegistry(content_dir)

    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock()
    mock_llm.chat.return_value = MagicMock(
        content=(
            '<artifact identifier="test-page" type="text/html"'
            ' title="Test">\n'
            '<html><body>Generated</body></html>'
            '\n</artifact>'
        ),
    )
    generator = DesignGenerator(llm_client=mock_llm)

    return DesignStudio(
        repo=repo,
        generator=generator,
        systems=systems_reg,
        templates=templates_reg,
        workspace_dir=tmp_path / "workspace",
    )


@pytest.fixture()
def studio(tmp_path):
    return _build_studio(tmp_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse_frames(raw: str) -> list[tuple[str, str]]:
    """Parse SSE text into [(event, data_str), ...] frames."""
    frames: list[tuple[str, str]] = []
    event_type = None
    data_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith("event: "):
            event_type = line[len("event: "):]
        elif line.startswith("data: "):
            data_lines.append(line[len("data: "):])
        elif line == "" and event_type is not None:
            frames.append((event_type, "\n".join(data_lines)))
            event_type = None
            data_lines = []
    if event_type is not None:
        frames.append((event_type, "\n".join(data_lines)))
    return frames


@pytest.mark.asyncio()
class TestDesignRoutes:
    # ---------------------------------------------------------------
    # GET /api/v1/design/systems
    # ---------------------------------------------------------------

    async def test_list_systems(self, studio):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get("/api/v1/design/systems")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["id"] == "test-sys"
        assert body[0]["category"] == "general"

    async def test_list_systems_filter_by_category(self, studio):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/design/systems?category=general",
                )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Non-matching category
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/design/systems?category=nonexistent",
                )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_systems_studio_not_initialised(self):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=None,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get("/api/v1/design/systems")
        assert resp.status_code == 404

    # ---------------------------------------------------------------
    # GET /api/v1/design/templates
    # ---------------------------------------------------------------

    async def test_list_templates(self, studio):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get("/api/v1/design/templates")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["kind"] == "prototype"

    async def test_list_templates_filter_by_kind(self, studio):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/design/templates?kind=prototype",
                )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    # ---------------------------------------------------------------
    # GET /api/v1/design/projects
    # ---------------------------------------------------------------

    async def test_list_projects_empty(self, studio):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get("/api/v1/design/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_projects_with_filter(self, studio):
        from backend.main import app

        studio.create_project(
            "P1", "prototype", "test-sys", "test-page", "brief1",
        )
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/design/projects?kind=prototype",
                )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    # ---------------------------------------------------------------
    # POST /api/v1/design/projects
    # ---------------------------------------------------------------

    async def test_create_project(self, studio):
        from backend.main import app

        payload = {
            "name": "My Page",
            "kind": "prototype",
            "system_id": "test-sys",
            "template_id": "test-page",
            "brief": "Build a landing page",
        }
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/design/projects", json=payload,
                )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "My Page"
        assert body["kind"] == "prototype"
        assert body["status"] == "draft"
        assert "id" in body

    async def test_create_project_invalid_kind(self, studio):
        from backend.main import app

        payload = {
            "name": "Bad", "kind": "video",
            "system_id": "test-sys", "template_id": "test-page",
            "brief": "x",
        }
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/design/projects", json=payload,
                )
        assert resp.status_code == 400

    async def test_create_project_system_not_found(self, studio):
        from backend.main import app

        payload = {
            "name": "X", "kind": "prototype",
            "system_id": "no-such-system", "template_id": "test-page",
            "brief": "x",
        }
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/design/projects", json=payload,
                )
        assert resp.status_code == 404

    async def test_create_project_template_not_found(self, studio):
        from backend.main import app

        payload = {
            "name": "X", "kind": "prototype",
            "system_id": "test-sys", "template_id": "no-such-tpl",
            "brief": "x",
        }
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/design/projects", json=payload,
                )
        assert resp.status_code == 404

    async def test_create_project_studio_not_initialised(self):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=None,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/design/projects",
                    json={
                        "name": "X", "kind": "prototype",
                        "system_id": "a", "template_id": "b",
                        "brief": "x",
                    },
                )
        assert resp.status_code == 404

    # ---------------------------------------------------------------
    # GET /api/v1/design/projects/:project_id
    # ---------------------------------------------------------------

    async def test_get_project(self, studio):
        from backend.main import app

        project = studio.create_project(
            "Detail", "prototype", "test-sys", "test-page", "brief",
        )
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get(
                    f"/api/v1/design/projects/{project.id}",
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == project.id
        assert body["name"] == "Detail"
        assert body["latest_artifact"] is None

    async def test_get_project_not_found(self, studio):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/design/projects/nonexistent",
                )
        assert resp.status_code == 404

    # ---------------------------------------------------------------
    # DELETE /api/v1/design/projects/:project_id
    # ---------------------------------------------------------------

    async def test_delete_project(self, studio):
        from backend.main import app

        project = studio.create_project(
            "ToDelete", "prototype", "test-sys", "test-page", "brief",
        )
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.request(
                    "DELETE", f"/api/v1/design/projects/{project.id}",
                )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}

        # Confirm gone
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp2 = await client.get(
                    f"/api/v1/design/projects/{project.id}",
                )
        assert resp2.status_code == 404

    async def test_delete_project_not_found(self, studio):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.request(
                    "DELETE", "/api/v1/design/projects/nonexistent",
                )
        assert resp.status_code == 404

    # ---------------------------------------------------------------
    # POST /api/v1/design/projects/:id/generate  (SSE)
    # ---------------------------------------------------------------

    async def test_generate_sse_stream(self, studio):
        from backend.main import app

        project = studio.create_project(
            "Gen", "prototype", "test-sys", "test-page", "brief",
        )
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    f"/api/v1/design/projects/{project.id}/generate",
                    json={"brief": "Generate a test page"},
                )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        frames = _sse_frames(resp.text)
        event_types = [f[0] for f in frames]
        assert "progress" in event_types
        assert "complete" in event_types
        # Last frame should be 'complete' with an artifact payload
        last_event, last_data = frames[-1]
        assert last_event == "complete"
        artifact = json.loads(last_data)["artifact"]
        assert artifact["project_id"] == project.id
        assert artifact["version"] == 1

    async def test_generate_uses_project_brief_when_omitted(self, studio):
        from backend.main import app

        project = studio.create_project(
            "GenDefault", "prototype", "test-sys", "test-page",
            "Default brief",
        )
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    f"/api/v1/design/projects/{project.id}/generate",
                    json={},
                )
        assert resp.status_code == 200
        frames = _sse_frames(resp.text)
        last_event, last_data = frames[-1]
        assert last_event == "complete"
        assert json.loads(last_data)["artifact"]["version"] == 1

    async def test_generate_project_not_found(self, studio):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/design/projects/nonexistent/generate",
                    json={"brief": "x"},
                )
        assert resp.status_code == 404

    # ---------------------------------------------------------------
    # POST /api/v1/design/projects/:id/iterate  (SSE)
    # ---------------------------------------------------------------

    async def test_iterate_sse_stream(self, studio):
        from backend.main import app

        project = studio.create_project(
            "Iter", "prototype", "test-sys", "test-page", "brief",
        )
        # Pre-generate v1
        await studio.generate(project.id, "v1 brief")

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    f"/api/v1/design/projects/{project.id}/iterate",
                    json={"feedback": "Make it brighter"},
                )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        frames = _sse_frames(resp.text)
        event_types = [f[0] for f in frames]
        assert "progress" in event_types
        assert "complete" in event_types
        _, last_data = frames[-1]
        artifact = json.loads(last_data)["artifact"]
        assert artifact["version"] == 2

    async def test_iterate_project_not_found(self, studio):
        from backend.main import app

        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/design/projects/nonexistent/iterate",
                    json={"feedback": "x"},
                )
        assert resp.status_code == 404

    async def test_iterate_no_artifact_returns_error_stream(self, studio):
        """Iterating a project with no artifact yields an error SSE frame."""
        from backend.main import app

        project = studio.create_project(
            "IterEmpty", "prototype", "test-sys", "test-page", "brief",
        )
        with patch(
            "backend.api.v1.design_routes.get_design_studio",
            return_value=studio,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    f"/api/v1/design/projects/{project.id}/iterate",
                    json={"feedback": "x"},
                )
        assert resp.status_code == 200
        frames = _sse_frames(resp.text)
        event_types = [f[0] for f in frames]
        assert "error" in event_types
