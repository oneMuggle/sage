from __future__ import annotations

import sqlite3

import pytest


class TestDesignMigration:
    @pytest.fixture()
    def conn(self, tmp_path):
        """Create a fresh database for each test."""
        db_path = tmp_path / "test.db"
        c = sqlite3.connect(str(db_path))
        c.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        yield c
        c.close()

    def test_migration_creates_design_projects(self, conn):
        from backend.data.migrations.runner import MIGRATIONS

        design_migration = None
        for _, name, fn in MIGRATIONS:
            if "design" in name.lower():
                design_migration = fn
                break

        assert design_migration is not None, "Design migration not found in MIGRATIONS list"
        design_migration(conn)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='design_projects'"
        )
        assert cursor.fetchone() is not None

    def test_migration_creates_design_artifacts(self, conn):
        from backend.data.migrations.runner import MIGRATIONS

        design_migration = None
        for _, name, fn in MIGRATIONS:
            if "design" in name.lower():
                design_migration = fn
                break

        design_migration(conn)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='design_artifacts'"
        )
        assert cursor.fetchone() is not None

    def test_design_projects_columns(self, conn):
        from backend.data.migrations.runner import MIGRATIONS

        design_migration = None
        for _, name, fn in MIGRATIONS:
            if "design" in name.lower():
                design_migration = fn
                break

        design_migration(conn)

        cursor = conn.execute("PRAGMA table_info(design_projects)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "id", "name", "kind", "system_id", "template_id",
            "brief", "status", "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_design_artifacts_columns(self, conn):
        from backend.data.migrations.runner import MIGRATIONS

        design_migration = None
        for _, name, fn in MIGRATIONS:
            if "design" in name.lower():
                design_migration = fn
                break

        design_migration(conn)

        cursor = conn.execute("PRAGMA table_info(design_artifacts)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "id", "project_id", "version", "file_path", "kind",
            "title", "export_formats", "source_prompt", "created_at",
        }
        assert expected.issubset(columns)

    def test_insert_and_query_project(self, conn):
        from backend.data.migrations.runner import MIGRATIONS

        design_migration = None
        for _, name, fn in MIGRATIONS:
            if "design" in name.lower():
                design_migration = fn
                break

        design_migration(conn)

        conn.execute(
            """INSERT INTO design_projects
               (id, name, kind, system_id, template_id, brief,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("p1", "Test", "prototype", "minimal", "landing-page",
             "brief", "draft", "2026-10-13", "2026-10-13"),
        )
        conn.commit()

        cursor = conn.execute(
            "SELECT name, kind FROM design_projects WHERE id = ?", ("p1",)
        )
        row = cursor.fetchone()
        assert row == ("Test", "prototype")
