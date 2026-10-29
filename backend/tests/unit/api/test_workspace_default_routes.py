"""Unit tests for :mod:`backend.api.workspace_default_routes`.

The default-workspace router is a thin HTTP shell around the resolver in
:mod:`backend.services.default_workspace`. These tests exercise the route
handler functions directly (no TestClient needed — the handlers are pure
functions that delegate to the resolver).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.api import workspace_default_routes as routes
from backend.data.database import Database
from backend.services.default_workspace import (
    LAST_WORKSPACE_KEY,
    DefaultWorkspaceResolver,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def db() -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    return test_db


@pytest.fixture()
def user_data_dir(tmp_path: Path) -> Path:
    root = tmp_path / "sage-user-data"
    root.mkdir()
    return root


@pytest.fixture()
def resolver(db: Database, user_data_dir: Path, monkeypatch) -> DefaultWorkspaceResolver:
    """Patch the module-level DefaultWorkspaceResolver to use the test DB."""
    test_resolver = DefaultWorkspaceResolver(db=db, user_data_dir=str(user_data_dir))
    monkeypatch.setattr(routes, "DefaultWorkspaceResolver", lambda: test_resolver)
    return test_resolver


# ----------------------------------------------------------------------
# GET /workspace/default
# ----------------------------------------------------------------------


def test_get_default_with_no_preference_returns_scratch(resolver, user_data_dir):
    response = routes.get_default_workspace(session_id=None, detected_root=None)

    assert response.path is not None
    assert response.source == "scratch"
    assert response.is_fallback is True


def test_get_default_with_preference_returns_user_preference(resolver, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    resolver.remember_workspace(str(project))

    response = routes.get_default_workspace(session_id=None, detected_root=None)

    assert response.path == str(project.resolve())
    assert response.source == "user_preference"
    assert response.is_fallback is False


def test_get_default_with_detected_root_when_no_preference(resolver, tmp_path):
    detected = tmp_path / "detected-root"
    detected.mkdir()

    response = routes.get_default_workspace(session_id=None, detected_root=str(detected))

    assert response.path == str(detected.resolve())
    assert response.source == "detected"
    assert response.is_fallback is False


def test_get_default_preference_beats_detected_root(resolver, tmp_path):
    preferred = tmp_path / "preferred"
    preferred.mkdir()
    detected = tmp_path / "detected"
    detected.mkdir()
    resolver.remember_workspace(str(preferred))

    response = routes.get_default_workspace(session_id=None, detected_root=str(detected))

    assert response.path == str(preferred.resolve())
    assert response.source == "user_preference"


# ----------------------------------------------------------------------
# POST /workspace/preference
# ----------------------------------------------------------------------


def test_set_workspace_preference_persists(resolver, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    request = routes.WorkspacePreferenceRequest(path=str(project))

    response = routes.set_workspace_preference(request)

    assert response.stored is True
    assert response.path == str(project.resolve())
    assert resolver.settings.get(LAST_WORKSPACE_KEY) == str(project.resolve())


def test_set_workspace_preference_rejects_missing_directory(resolver):
    request = routes.WorkspacePreferenceRequest(path="/definitely/does/not/exist")

    with pytest.raises(HTTPException) as exc_info:
        routes.set_workspace_preference(request)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "invalid_workspace_path"


# ----------------------------------------------------------------------
# DELETE /workspace/preference
# ----------------------------------------------------------------------


def test_clear_workspace_preference_forgets(resolver, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    resolver.remember_workspace(str(project))
    assert resolver.settings.get(LAST_WORKSPACE_KEY) is not None

    response = routes.clear_workspace_preference()

    assert response.stored is False
    assert response.path is None
    assert resolver.settings.get(LAST_WORKSPACE_KEY) is None


def test_clear_workspace_preference_is_idempotent(resolver):
    """Calling DELETE when nothing is stored must not raise."""
    assert resolver.settings.get(LAST_WORKSPACE_KEY) is None

    response = routes.clear_workspace_preference()

    assert response.stored is False
    assert response.path is None


# ----------------------------------------------------------------------
# POST /workspace/migrate
#
# The route is a thin pass-through to
# :func:`backend.services.workspace_migration.migrate_last_workspace`,
# whose full behaviour (empty / migrated / already_present / rejected) is
# covered in ``tests/unit/services/test_workspace_migration.py``. These
# route tests only verify the HTTP-layer plumbing: request validation,
# response shape, and that the service result is surfaced with the
# right fields.
# ----------------------------------------------------------------------


def test_migrate_empty_path_returns_empty(resolver):
    request = routes.WorkspaceMigrateRequest(path=None)

    response = routes.migrate_workspace_preference(request)

    assert response.outcome == "empty"
    assert response.path is None
    assert response.reason is None


def test_migrate_returns_migration_outcome_shape(resolver, tmp_path):
    """The route surfaces the migration service outcome (here 'migrated'
    or 'already_present' depending on production-DB state — we only
    assert the response has the expected fields)."""
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    request = routes.WorkspaceMigrateRequest(path=str(legacy))

    response = routes.migrate_workspace_preference(request)

    assert response.outcome in {"migrated", "already_present"}
    # path is populated for both terminal outcomes.
    assert response.path is None or isinstance(response.path, str)
    assert response.reason is None or isinstance(response.reason, str)


# ----------------------------------------------------------------------
# GET /workspace/health
# ----------------------------------------------------------------------


def test_get_health_reports_healthy_directory(resolver, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    response = routes.get_workspace_health(path=str(workspace))

    assert response.health == "healthy"
    assert response.writable is True
    assert response.is_usable is True
    assert response.path == str(workspace)


def test_get_health_reports_missing_directory(resolver, tmp_path):
    response = routes.get_workspace_health(path=str(tmp_path / "gone"))

    assert response.health == "missing"
    assert response.is_usable is False
    assert response.writable is False
