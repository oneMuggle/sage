# backend/tests/unit/test_design_studio.py
from __future__ import annotations

import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.data.design_repo import DesignRepo
from backend.design.design_studio import DesignStudio
from backend.design.errors import (
    DesignGenerationError,
    DesignProjectNotFoundError,
    DesignSystemNotFoundError,
    DesignTemplateNotFoundError,
)
from backend.design.systems import DesignSystemRegistry
from backend.design.templates import DesignTemplateRegistry


class TestDesignStudio:
    @pytest.fixture()
    def studio(self, tmp_path):
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

        systems_dir = content_dir / "systems" / "test"
        systems_dir.mkdir(parents=True)
        (systems_dir / "DESIGN.md").write_text("# Test")
        (systems_dir / "tokens.css").write_text(":root { --bg: #fff; }")
        (systems_dir / "manifest.json").write_text(json.dumps({
            "id": "test", "name": "Test", "category": "general",
            "description": "test", "tags": [],
        }))

        template_dir = content_dir / "templates" / "prototype" / "test-page"
        template_dir.mkdir(parents=True)
        (template_dir / "SKILL.md").write_text(
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
            )
        )

        from backend.design.generator import DesignGenerator
        generator = DesignGenerator(llm_client=mock_llm)

        return DesignStudio(
            repo=repo,
            generator=generator,
            systems=systems_reg,
            templates=templates_reg,
            workspace_dir=tmp_path / "workspace",
        )

    def test_create_project(self, studio):
        project = studio.create_project(
            name="Test Project",
            kind="prototype",
            system_id="test",
            template_id="test-page",
            brief="Create a test page",
        )
        assert project.name == "Test Project"
        assert project.status == "draft"

    def test_list_projects(self, studio):
        studio.create_project(
            "P1", "prototype", "test", "test-page", "brief1",
        )
        studio.create_project(
            "P2", "prototype", "test", "test-page", "brief2",
        )
        projects = studio.list_projects()
        assert len(projects) == 2

    @pytest.mark.asyncio()
    async def test_generate_creates_artifact(self, studio):
        project = studio.create_project(
            "Test", "prototype", "test", "test-page", "Create a page",
        )
        artifact = await studio.generate(
            project.id, "Generate a test page",
        )
        assert artifact.version == 1
        assert "Generated" in artifact.html_content

    @pytest.mark.asyncio()
    async def test_iterate_increments_version(self, studio):
        project = studio.create_project(
            "Test", "prototype", "test", "test-page", "Create a page",
        )
        await studio.generate(project.id, "v1 brief")
        artifact = await studio.iterate(project.id, "Make it better")
        assert artifact.version == 2

    @pytest.mark.asyncio()
    async def test_generate_twice_does_not_collide_on_version(self, studio):
        """回归：第二次 generate() 必须递增版本，不能撞 UNIQUE(project_id, version)。"""
        project = studio.create_project(
            "Test", "prototype", "test", "test-page", "Create a page",
        )
        first = await studio.generate(project.id, "v1 brief")
        assert first.version == 1
        second = await studio.generate(project.id, "v2 brief")
        assert second.version == 2
        assert second.file_path.endswith("/v2.html")

    @pytest.mark.asyncio()
    async def test_generate_marks_project_complete(self, studio):
        project = studio.create_project(
            "Test", "prototype", "test", "test-page", "Create a page",
        )
        await studio.generate(project.id, "brief")
        assert studio.get_project(project.id).status == "complete"

    @pytest.mark.asyncio()
    async def test_generate_marks_project_error_and_reraises(self, studio):
        project = studio.create_project(
            "Test", "prototype", "test", "test-page", "Create a page",
        )
        boom = DesignGenerationError("llm exploded")
        studio._generator._llm.chat.side_effect = boom

        with pytest.raises(DesignGenerationError) as excinfo:
            await studio.generate(project.id, "brief")

        assert excinfo.value is boom
        assert studio.get_project(project.id).status == "error"

    @pytest.mark.asyncio()
    async def test_generate_persists_expected_file_path(self, studio, tmp_path):
        project = studio.create_project(
            "Test", "prototype", "test", "test-page", "Create a page",
        )
        artifact = await studio.generate(project.id, "brief")
        expected = str(
            tmp_path / "workspace" / "design" / project.id / "v1.html"
        )
        assert artifact.file_path == expected

    @pytest.mark.asyncio()
    async def test_iterate_without_artifacts_raises(self, studio):
        project = studio.create_project(
            "Test", "prototype", "test", "test-page", "Create a page",
        )
        with pytest.raises(DesignProjectNotFoundError):
            await studio.iterate(project.id, "Make it better")

    def test_create_project_rejects_unknown_ids(self, studio):
        with pytest.raises(DesignSystemNotFoundError):
            studio.create_project(
                "Bad", "prototype", "no-such-system", "test-page", "b",
            )
        with pytest.raises(DesignTemplateNotFoundError):
            studio.create_project(
                "Bad", "prototype", "test", "no-such-template", "b",
            )
        assert studio.list_projects() == []
