"""Unit tests for :mod:`backend.services.default_workspace`.

Cover the priority chain with an in-memory SQLite DB and real temp dirs —
no subprocess, no Electron IPC — so the tests stay fast and deterministic.

2026-11-20: scratch → default (~/Sage/) 语义变更。所有 fallthrough 测试
断言 source=DEFAULT（而非 SCRATCH）。测试通过 monkeypatch Path.home() 隔离，
避免创建真实 ~/Sage/。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.office.errors import OfficePathError
from backend.office.session_workspace import bind_session_workspace
from backend.services.default_workspace import (
    DEFAULT_WORKSPACE_DIRNAME,
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


@pytest.fixture()
def isolated_home(monkeypatch, tmp_path: Path):
    """Redirect Path.home() to tmp_path so ~/Sage/ is isolated per test."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


# ----------------------------------------------------------------------
# priority 1: explicit project path wins
# ----------------------------------------------------------------------


def test_explicit_project_path_wins(resolver, project_dir):
    result = resolver.resolve_default_workspace(project_path=str(project_dir))

    assert result is not None
    assert result.path == str(project_dir.resolve())
    assert result.source == WorkspaceSource.PROJECT
    assert result.is_fallback is False


def test_explicit_invalid_path_falls_through(resolver, isolated_home):
    """A bad project path must not halt resolution — the chain moves on."""
    result = resolver.resolve_default_workspace(
        project_path="/definitely/does/not/exist"
    )

    assert result is not None
    assert result.source == WorkspaceSource.DEFAULT
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


def test_session_binding_with_dead_path_skips(resolver, session_id, tmp_path, isolated_home):
    """A stale binding (directory deleted) must not block the next priority."""
    # Bind the session to a directory, then delete it.
    dead = tmp_path / "dead-binding"
    dead.mkdir()
    bind_session_workspace(resolver.db.get_connection(), session_id, str(dead))
    dead.rmdir()

    result = resolver.resolve_default_workspace(session_id=session_id)

    # Falls through to default workspace.
    assert result is not None
    assert result.source == WorkspaceSource.DEFAULT
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


def test_stale_preference_retained(resolver, tmp_path, isolated_home):
    """A transiently unusable remembered path is kept, not silently forgotten."""
    dead = tmp_path / "gone"
    dead.mkdir()
    resolver.remember_workspace(str(dead))
    dead.rmdir()

    assert resolver.settings.get(LAST_WORKSPACE_KEY) is not None

    result = resolver.resolve_default_workspace()

    # Falls to default workspace, but resolution must not mutate the stored preference:
    # an unmounted drive can come back, and only an explicit forget clears it.
    assert result is not None
    assert result.source == WorkspaceSource.DEFAULT
    assert resolver.settings.get(LAST_WORKSPACE_KEY) is not None


# ----------------------------------------------------------------------
# priority 5: default workspace (~/Sage/)
# ----------------------------------------------------------------------


def test_default_workspace_created_when_nothing_else(resolver, isolated_home):
    result = resolver.resolve_default_workspace()

    assert result is not None
    assert result.source == WorkspaceSource.DEFAULT
    assert result.is_fallback is True
    # The default dir was created under isolated_home (~/Sage/).
    default_dir = isolated_home / DEFAULT_WORKSPACE_DIRNAME
    assert Path(result.path) == default_dir.resolve()
    assert default_dir.exists()
    assert default_dir.is_dir()


def test_default_workspace_is_idempotent(resolver, isolated_home):
    """Two consecutive resolutions must return the same default path."""
    a = resolver.resolve_default_workspace()
    b = resolver.resolve_default_workspace()
    assert a is not None
    assert b is not None
    assert a.path == b.path


def test_resolve_to_default_returns_default_workspace(resolver, isolated_home):
    """resolve_to_default() bypasses the chain and resolves to ~/Sage/."""
    result = resolver.resolve_to_default()

    assert result is not None
    default_dir = isolated_home / DEFAULT_WORKSPACE_DIRNAME
    assert Path(result.path) == default_dir.resolve()
    assert result.source == WorkspaceSource.DEFAULT
    assert result.is_fallback is False  # explicit choice, not a fallback
    assert default_dir.exists()


def test_resolve_to_default_is_idempotent(resolver, isolated_home):
    """Two consecutive resolve_to_default() calls return the same path."""
    a = resolver.resolve_to_default()
    b = resolver.resolve_to_default()
    assert a is not None
    assert b is not None
    assert a.path == b.path
    assert a.source == WorkspaceSource.DEFAULT


def test_default_workspace_path_returns_home_sage(resolver, isolated_home):
    """default_workspace_path() returns ~/Sage/ without creating it."""
    path = resolver.default_workspace_path()
    assert path == isolated_home / DEFAULT_WORKSPACE_DIRNAME


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
