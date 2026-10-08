# ruff: noqa: UP006, UP007, UP035 — Python 3.8 typing compatibility
"""R187 data repository contract tests for ProjectRepository and project session helpers."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.data.database import Database
from backend.data.project_repo import (
    ProjectNotFoundError,
    ProjectPathMissingError,
    ProjectRepository,
    create_project_session,
    open_project,
    register_quietly,
)
from backend.data.session_repo import SessionRepository

pytestmark = pytest.mark.unit


@pytest.fixture()
def isolated_project_env(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "project_r187.db"))
    db.init_db()
    with patch("backend.data.project_repo.get_database", return_value=db), patch(
        "backend.data.session_repo.get_database", return_value=db
    ):
        yield ProjectRepository(), SessionRepository(), db, tmp_path


def test_register_is_idempotent_and_detects_git_vcs_mode(isolated_project_env) -> None:
    repo, _, _, tmp_path = isolated_project_env
    ws = tmp_path / "alpha_proj"
    (ws / ".git").mkdir(parents=True)

    p1 = repo.register(
        str(ws),
        now_ms=1_000,
        allowed_paths=["~/docs/**"],
        project_type="coding",
        detected_type="coding",
    )
    assert p1.name == "alpha_proj"
    assert p1.vcs_mode == "git"
    assert p1.allowed_paths == ["~/docs/**"]
    assert p1.created_at == 1_000
    assert p1.last_opened_at == 1_000

    # Re-registering same directory keeps id and refreshes last_opened_at
    p2 = repo.register(str(ws), now_ms=2_500)
    assert p2.id == p1.id
    assert p2.last_opened_at == 2_500
    assert p2.project_type == "coding"
    assert repo.get_project_for_workspace(p1.path) is not None


def test_metadata_updates_search_touch_and_remove(isolated_project_env) -> None:
    repo, _, _, tmp_path = isolated_project_env
    ws = tmp_path / "research_notes"
    ws.mkdir()
    proj = repo.register(str(ws), now_ms=100)

    assert repo.update_description(proj.id, "研究笔记项目") is True
    assert repo.update_instructions(proj.id, "始终附上引用来源") is True
    assert repo.update_allowed_paths(proj.id, ["/tmp/shared"]) is True
    assert repo.update_project_type(proj.id, "research") is True
    assert repo.update_project_stage(proj.id, "writing") is True
    assert repo.touch(proj.id, now_ms=900) is True

    updated = repo.get(proj.id)
    assert updated is not None
    assert updated.description == "研究笔记项目"
    assert updated.instructions == "始终附上引用来源"
    assert updated.allowed_paths == ["/tmp/shared"]
    assert updated.project_type == "research"
    assert updated.project_stage == "writing"
    assert updated.last_opened_at == 900

    hits = repo.search("research_notes")
    assert [h.id for h in hits] == [proj.id]

    assert repo.remove(proj.id) is True
    assert repo.get(proj.id) is None
    assert repo.remove(proj.id) is False


def test_open_project_and_create_project_session_lifecycle(isolated_project_env) -> None:
    repo, _, _, tmp_path = isolated_project_env
    ws = tmp_path / "workspace_one"
    ws.mkdir()
    proj = repo.register(str(ws), now_ms=1_000)

    # First open creates a bound session
    opened_proj, s1, created1 = open_project(proj.id, now_ms=2_000)
    assert created1 is True
    assert opened_proj.id == proj.id
    assert s1.title == "workspace_one"

    # Second open reuses the most recent active session
    _, s2, created2 = open_project(proj.id, now_ms=3_000)
    assert created2 is False
    assert s2.id == s1.id

    # Explicit create_project_session always creates a fresh bound session
    _, s3 = create_project_session(proj.id, now_ms=4_000)
    assert s3.id != s1.id

    sessions = repo.sessions_for_project(proj.path)
    assert {s.id for s in sessions} == {s1.id, s3.id}
    stats = repo.session_stats()
    assert stats[proj.path][0] == 2

    # Removing directory from disk causes open_project to raise ProjectPathMissingError
    shutil.rmtree(ws)
    with pytest.raises(ProjectPathMissingError):
        open_project(proj.id, now_ms=5_000)

    with pytest.raises(ProjectNotFoundError):
        open_project("non-existent-project-id")


def test_register_quietly_swallows_invalid_path(isolated_project_env) -> None:
    _, _, _, tmp_path = isolated_project_env
    missing = tmp_path / "does_not_exist"
    assert register_quietly(str(missing)) is None
