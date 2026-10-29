"""Unit tests for :mod:`backend.services.default_workspace`.

Cover the priority chain with an in-memory SQLite DB and real temp dirs —
no subprocess, no Electron IPC — so the tests stay fast and deterministic.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.office.errors import OfficePathError
from backend.office.session_workspace import bind_session_workspace
from backend.services.default_workspace import (
    LAST_WORKSPACE_KEY,
    DefaultWorkspaceResolver,
    WorkspaceSource,
)


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------


@pytest.fixture()
def user_data_dir(tmp_path: Path) -> Path:
    """Isolated per-user data dir so scratch lives under one place per test."""
    root = tmp_path / "sage-user-data"
    root.mkdir()
    return root


@pytest.fixture()
def db() -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    return test_db


@pytest.fixture()
def resolver(db: Database, user_data_dir: Path) -> DefaultWorkspaceResolver:
    return DefaultWorkspaceResolver(db=db, user_data_dir=str(user_data_dir))


@pytest.fixture()
def conn(db: Database) -> sqlite3.Connection:
    return db.get_connection()


@pytest.fixture()
def session_id(conn: sqlite3.Connection, tmp_path: Path) -> str:
    value = "session-workspace-test"
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (value, "Workspace test", 1, 1),
    )
    conn.commit()
    return value


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    return path


@pytest.fixture()
def another_dir(tmp_path: Path) -> Path:
    path = tmp_path / "another"
    path.mkdir()
    return path


# ----------------------------------------------------------------------
# priority 1: explicit project path wins
# ----------------------------------------------------------------------


def test_explicit_project_path_wins(resolver, project_dir):
    result = resolver.resolve_default_workspace(project_path=str(project_dir))

    assert result is not None
    assert result.path == str(project_dir.resolve())
    assert result.source == WorkspaceSource.PROJECT
    assert result.is_fallback is False


def test_explicit_invalid_path_falls_through(resolver, user_data_dir):
    """A bad project path must not halt resolution — the chain moves on."""
    result = resolver.resolve_default_workspace(
        project_path="/definitely/does/not/exist"
    )

    assert result is not None
    assert result.source == WorkspaceSource.SCRATCH
    assert result.is_fallback is True


# ----------------------------------------------------------------------
# priority 2: session binding beats user preference
# ----------------------------------------------------------------------


def test_session_binding_beats_user_preference(resolver, another_dir, session_id):
    """An existing session's live binding outranks the remembered preference."""
    # Bind the session to another_dir.
    bind_session_workspace(resolver.db.get_connection(), session_id, str(another_dir))

    # Create a project dir and write preference to it (a *different* path).
    project_dir = another_dir.parent / "project"
    project_dir.mkdir(exist_ok=True)
    resolver.settings.set(LAST_WORKSPACE_KEY, str(project_dir))

    result = resolver.resolve_default_workspace(session_id=session_id)

    assert result is not None
    assert result.source == WorkspaceSource.SESSION_BINDING
    # The binding (another_dir) beats the preference (project_dir).
    assert Path(result.path) == another_dir.resolve()


def test_session_binding_with_dead_path_skips(resolver, session_id, tmp_path):
    """A stale binding (directory deleted) must not block the next priority."""
    # Bind the session to a directory, then delete it.
    dead = tmp_path / "dead-binding"
    dead.mkdir()
    bind_session_workspace(resolver.db.get_connection(), session_id, str(dead))
    dead.rmdir()

    result = resolver.resolve_default_workspace(session_id=session_id)

    # Falls through to scratch.
    assert result is not None
    assert result.source == WorkspaceSource.SCRATCH
    assert result.is_fallback is True


# ----------------------------------------------------------------------
# priority 3: user preference survives project_path=None / session_id=None
# ----------------------------------------------------------------------


def test_user_preference_hits(resolver, project_dir):
    resolver.remember_workspace(str(project_dir))

    result = resolver.resolve_default_workspace()

    assert result is not None
    assert result.path == str(project_dir.resolve())
    assert result.source == WorkspaceSource.USER_PREFERENCE


def test_stale_preference_retained(resolver, tmp_path):
    """A transiently unusable remembered path is kept, not silently forgotten."""
    dead = tmp_path / "gone"
    dead.mkdir()
    resolver.remember_workspace(str(dead))
    dead.rmdir()

    assert resolver.settings.get(LAST_WORKSPACE_KEY) is not None

    result = resolver.resolve_default_workspace()

    # Falls to scratch, but resolution must not mutate the stored preference:
    # an unmounted drive can come back, and only an explicit forget clears it.
    assert result is not None
    assert result.source == WorkspaceSource.SCRATCH
    assert resolver.settings.get(LAST_WORKSPACE_KEY) is not None


# ----------------------------------------------------------------------
# priority 4: scratch workspace
# ----------------------------------------------------------------------


def test_scratch_workspace_created_when_nothing_else(resolver, user_data_dir):
    result = resolver.resolve_default_workspace()

    assert result is not None
    assert result.source == WorkspaceSource.SCRATCH
    assert result.is_fallback is True
    # The scratch dir was created under the isolated user_data_dir.
    scratch = user_data_dir / "workspaces" / "default"
    assert Path(result.path) == scratch.resolve()
    assert scratch.exists()
    assert scratch.is_dir()


def test_scratch_workspace_is_idempotent(resolver):
    """Two consecutive resolutions must return the same scratch path."""
    a = resolver.resolve_default_workspace()
    b = resolver.resolve_default_workspace()
    assert a is not None and b is not None
    assert a.path == b.path


# ----------------------------------------------------------------------
# remember / forget / scratch path helpers
# ----------------------------------------------------------------------


def test_remember_workspace_persists(resolver, project_dir):
    canonical = resolver.remember_workspace(str(project_dir))

    assert canonical == str(project_dir.resolve())
    assert resolver.settings.get(LAST_WORKSPACE_KEY) == canonical


def test_remember_workspace_rejects_missing_dir(resolver, tmp_path):
    with pytest.raises(OfficePathError):
        resolver.remember_workspace(str(tmp_path / "no-such-dir"))


def test_forget_workspace_clears(resolver, project_dir):
    resolver.remember_workspace(str(project_dir))
    resolver.forget_workspace()

    assert resolver.settings.get(LAST_WORKSPACE_KEY) is None


def test_scratch_workspace_path_uses_env(
    monkeypatch,
    db: Database,
    tmp_path: Path,
):
    """scratch_workspace_path honours SAGE_USER_DATA_DIR when not injected."""
    root = tmp_path / "env-root"
    root.mkdir()
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(root))

    r = DefaultWorkspaceResolver(db=db)  # no user_data_dir passed

    assert r.scratch_workspace_path() == root / "workspaces" / "default"
