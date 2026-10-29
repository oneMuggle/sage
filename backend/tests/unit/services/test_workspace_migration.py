"""Unit tests for :mod:`backend.services.workspace_migration`.

The migration moves the legacy localStorage value into ``preferences``. It
must be idempotent, non-blocking, and conservative: existing preferences win,
and unusable paths are rejected without raising.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.data.database import Database
from backend.services.default_workspace import (
    LAST_WORKSPACE_KEY,
    DefaultWorkspaceResolver,
)
from backend.services.workspace_migration import (
    MigrationOutcome,
    MigrationResult,
    migrate_last_workspace,
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
def resolver(db: Database, user_data_dir: Path) -> DefaultWorkspaceResolver:
    return DefaultWorkspaceResolver(db=db, user_data_dir=str(user_data_dir))


# ----------------------------------------------------------------------
# outcome — empty
# ----------------------------------------------------------------------


def test_empty_path_returns_empty_outcome(resolver):
    result = migrate_last_workspace(None, resolver=resolver)

    assert result == MigrationResult(outcome=MigrationOutcome.EMPTY)


def test_empty_string_returns_empty_outcome(resolver):
    result = migrate_last_workspace("", resolver=resolver)

    assert result == MigrationResult(outcome=MigrationOutcome.EMPTY)


# ----------------------------------------------------------------------
# outcome — migrated
# ----------------------------------------------------------------------


def test_migrated_when_no_existing_preference(resolver, tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    result = migrate_last_workspace(str(project), resolver=resolver)

    assert result.outcome == MigrationOutcome.MIGRATED
    assert result.path is not None
    assert Path(result.path).resolve() == project.resolve()
    assert resolver.settings.get(LAST_WORKSPACE_KEY) == result.path


# ----------------------------------------------------------------------
# outcome: already_present (conservative — never overwrite)
# ----------------------------------------------------------------------


def test_already_present_when_preference_exists(resolver, tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    legacy = tmp_path / "legacy"
    legacy.mkdir()

    resolver.remember_workspace(str(existing))
    result = migrate_last_workspace(str(legacy), resolver=resolver)

    assert result.outcome == MigrationOutcome.ALREADY_PRESENT
    # The existing preference is preserved, not replaced by the legacy value.
    assert result.path is not None
    assert Path(result.path).resolve() == existing.resolve()
    assert resolver.settings.get(LAST_WORKSPACE_KEY) == result.path


# ----------------------------------------------------------------------
# outcome — rejected (path is unusable)
# ----------------------------------------------------------------------


def test_rejected_when_path_missing(resolver):
    result = migrate_last_workspace("/definitely/does/not/exist", resolver=resolver)

    assert result.outcome == MigrationOutcome.REJECTED
    assert result.reason is not None
    assert resolver.settings.get(LAST_WORKSPACE_KEY) is None


def test_rejected_when_path_is_a_file(resolver, tmp_path):
    a_file = tmp_path / "not-a-directory.txt"
    a_file.write_text("nope")

    result = migrate_last_workspace(str(a_file), resolver=resolver)

    assert result.outcome == MigrationOutcome.REJECTED
    assert resolver.settings.get(LAST_WORKSPACE_KEY) is None


# ----------------------------------------------------------------------
# robustness: resolver failure must not raise
# ----------------------------------------------------------------------


def test_resolver_failure_is_swallowed(tmp_path, caplog):
    """A resolver whose lookup raises must not abort migration."""
    project = tmp_path / "project"
    project.mkdir()

    class BrokenResolver:
        def __init__(self):
            self.settings = None  # intentional — getattr will fail

        def remember_workspace(self, _path):  # pragma: no cover - never reached
            raise RuntimeError("boom")

    # The broken resolver's settings attribute is None, so .get() will fail
    # inside the try/except that guards the lookup.
    result = migrate_last_workspace(str(project), resolver=BrokenResolver())

    # remember_workspace then raises RuntimeError, which the function catches.
    assert result.outcome == MigrationOutcome.REJECTED
    assert result.reason == "unexpected error"
