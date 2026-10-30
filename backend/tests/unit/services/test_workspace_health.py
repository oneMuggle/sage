"""Unit tests for :mod:`backend.services.workspace_health`.

The checker is a pure filesystem probe, so the tests use real temp
directories and real permission bits — no mocking of ``os.access``, which
would only test the mock.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.workspace_health import (
    WorkspaceHealth,
    WorkspaceHealthChecker,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def checker() -> WorkspaceHealthChecker:
    return WorkspaceHealthChecker()


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    return path


# ----------------------------------------------------------------------
# healthy
# ----------------------------------------------------------------------


def test_healthy_directory(checker, workspace):
    status = checker.check(str(workspace))

    assert status.health == WorkspaceHealth.HEALTHY
    assert status.writable is True
    assert status.is_usable is True
    assert status.detail is None


def test_accepts_path_object(checker, workspace):
    status = checker.check(workspace)

    assert status.health == WorkspaceHealth.HEALTHY
    assert status.path == str(workspace)


# ----------------------------------------------------------------------
# missing
# ----------------------------------------------------------------------


def test_missing_directory(checker, tmp_path):
    status = checker.check(str(tmp_path / "gone"))

    assert status.health == WorkspaceHealth.MISSING
    assert status.is_usable is False
    assert status.writable is False
    assert status.detail is not None


# ----------------------------------------------------------------------
# not a directory
# ----------------------------------------------------------------------


def test_path_is_a_file(checker, tmp_path):
    a_file = tmp_path / "notes.txt"
    a_file.write_text("hello")

    status = checker.check(str(a_file))

    assert status.health == WorkspaceHealth.NOT_A_DIRECTORY
    assert status.is_usable is False


# ----------------------------------------------------------------------
# read-only
# ----------------------------------------------------------------------


def test_read_only_directory_is_still_usable(checker, workspace):
    workspace.chmod(0o500)
    try:
        status = checker.check(str(workspace))
    finally:
        workspace.chmod(0o700)

    assert status.health == WorkspaceHealth.READ_ONLY
    # Read-only still counts as usable — the session can read, only saving fails.
    assert status.is_usable is True
    assert status.writable is False
    assert status.detail is not None


# ----------------------------------------------------------------------
# inaccessible
# ----------------------------------------------------------------------


def test_inaccessible_directory(checker, workspace):
    workspace.chmod(0o000)
    try:
        status = checker.check(str(workspace))
    finally:
        workspace.chmod(0o700)

    assert status.health == WorkspaceHealth.INACCESSIBLE
    assert status.is_usable is False
    assert status.writable is False


# ----------------------------------------------------------------------
# never raises
# ----------------------------------------------------------------------


def test_invalid_path_type_does_not_raise(checker):
    status = checker.check(None)  # type: ignore[arg-type]

    assert status.health == WorkspaceHealth.INACCESSIBLE
    assert status.is_usable is False
