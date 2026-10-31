"""Unit tests for playbook snapshots and project playbook state (2026-10-31)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.data import database as database_module
from backend.data.database import Database
from backend.data.playbook_repo import PlaybookRepository
from backend.data.project_repo import ProjectRepository
from backend.services.playbook_library import get_builtin


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest.fixture()
def project(db: Database, tmp_path: Path):
    root = tmp_path / "demo"
    root.mkdir()
    return ProjectRepository().register(str(root), project_type="research")


def test_bind_and_read_snapshot(project) -> None:
    repo = PlaybookRepository()
    snap = repo.create_snapshot(
        project.id,
        get_builtin("cn-research-grant"),
        source="builtin:cn-research-grant@1",
    )
    assert snap.version == 1
    active = repo.get_active(project.id)
    assert active is not None
    assert active.spec["id"] == "cn-research-grant"
    assert active.spec_hash
    assert active.source == "builtin:cn-research-grant@1"


def test_versions_keep_history_and_activate_latest(project) -> None:
    repo = PlaybookRepository()
    repo.create_snapshot(project.id, get_builtin("cn-research-grant"), source="custom")
    repo.create_snapshot(project.id, get_builtin("coding-project"), source="custom")
    versions = repo.list_versions(project.id)
    assert [item.version for item in versions] == [2, 1]
    active = repo.get_active(project.id)
    assert active is not None
    assert active.spec["id"] == "coding-project"


def test_state_round_trip(project) -> None:
    repo = PlaybookRepository()
    state = {"current_stage": "proposal", "stage_history": []}
    assert repo.update_state(project.id, state) is True
    assert repo.get_state(project.id)["current_stage"] == "proposal"


def test_unknown_project_returns_none(db: Database) -> None:
    repo = PlaybookRepository()
    assert repo.get_active("missing") is None
    assert repo.get_state("missing") == {}
