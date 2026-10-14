from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from backend.data.design_repo import DesignRepo
from backend.design.errors import DesignProjectNotFoundError


class TestDesignRepo:
    @pytest.fixture()
    def repo(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            CREATE TABLE design_projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                kind TEXT NOT NULL, system_id TEXT NOT NULL,
                template_id TEXT NOT NULL, brief TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE design_artifacts (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                version INTEGER NOT NULL, file_path TEXT NOT NULL,
                kind TEXT NOT NULL, title TEXT NOT NULL,
                export_formats TEXT NOT NULL DEFAULT '[]',
                source_prompt TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(project_id, version)
            )
        """)
        conn.commit()
        return DesignRepo(conn)

    @pytest.fixture()
    def now(self):
        return datetime.now(timezone.utc)  # noqa: UP017

    def test_create_and_get_project(self, repo, now):
        repo.create_project(
            id="p1", name="Test Page", kind="prototype",
            system_id="minimal", template_id="landing-page",
            brief="Create a landing page",
            created_at=now, updated_at=now,
        )
        project = repo.get_project("p1")
        assert project.id == "p1"
        assert project.name == "Test Page"
        assert project.status == "draft"

    def test_get_project_not_found(self, repo):
        with pytest.raises(DesignProjectNotFoundError):
            repo.get_project("nonexistent")

    def test_list_projects(self, repo, now):
        repo.create_project(
            "p1", "Page 1", "prototype", "minimal", "landing-page",
            "brief1", now, now,
        )
        repo.create_project(
            "p2", "Page 2", "deck", "corporate", "html-ppt",
            "brief2", now, now,
        )
        projects = repo.list_projects()
        assert len(projects) == 2

    def test_update_project_status(self, repo, now):
        repo.create_project(
            "p1", "Test", "prototype", "minimal", "landing-page",
            "brief", now, now,
        )
        repo.update_project_status("p1", "generating")
        project = repo.get_project("p1")
        assert project.status == "generating"

    def test_delete_project(self, repo, now):
        repo.create_project(
            "p1", "Test", "prototype", "minimal", "landing-page",
            "brief", now, now,
        )
        repo.delete_project("p1")
        with pytest.raises(DesignProjectNotFoundError):
            repo.get_project("p1")

    def test_create_and_get_artifact(self, repo, now, tmp_path):
        repo.create_project(
            "p1", "Test", "prototype", "minimal", "landing-page",
            "brief", now, now,
        )
        repo.create_artifact(
            id="a1", project_id="p1", version=1,
            html_content="<html></html>", title="v1",
            file_path=str(tmp_path / "v1.html"),
            kind="html", export_formats=["html", "pdf"],
            source_prompt="Generate...", created_at=now,
        )
        artifact = repo.get_artifact("a1")
        assert artifact.project_id == "p1"
        assert artifact.version == 1

    def test_list_artifacts_for_project(self, repo, now, tmp_path):
        repo.create_project(
            "p1", "Test", "prototype", "minimal", "landing-page",
            "brief", now, now,
        )
        repo.create_artifact(
            "a1", "p1", 1, "<html>v1</html>", "v1",
            str(tmp_path / "v1.html"), "html", ["html"], "", now,
        )
        repo.create_artifact(
            "a2", "p1", 2, "<html>v2</html>", "v2",
            str(tmp_path / "v2.html"), "html", ["html"], "", now,
        )
        artifacts = repo.list_artifacts("p1")
        assert len(artifacts) == 2

    def test_get_latest_artifact(self, repo, now, tmp_path):
        repo.create_project(
            "p1", "Test", "prototype", "minimal", "landing-page",
            "brief", now, now,
        )
        repo.create_artifact(
            "a1", "p1", 1, "<html>v1</html>", "v1",
            str(tmp_path / "v1.html"), "html", ["html"], "", now,
        )
        repo.create_artifact(
            "a2", "p1", 2, "<html>v2</html>", "v2",
            str(tmp_path / "v2.html"), "html", ["html"], "", now,
        )
        latest = repo.get_latest_artifact("p1")
        assert latest.version == 2
