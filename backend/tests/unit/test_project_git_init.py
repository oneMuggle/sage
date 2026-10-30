import subprocess
from pathlib import Path

import pytest

from backend.services import project_git_init


def test_init_creates_git_directory(tmp_path: Path) -> None:
    if not project_git_init.git_available():
        pytest.skip("git not available in test environment")
    result = project_git_init.init_project_git(str(tmp_path))
    assert result["initialized"] is True
    assert result["already_repo"] is False
    assert result["error"] is None
    assert (tmp_path / ".git").is_dir()


def test_existing_repo_is_not_reinitialized(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = project_git_init.init_project_git(str(tmp_path))
    assert result["initialized"] is False
    assert result["already_repo"] is True
    assert result["error"] is None


def test_returns_gracefully_when_git_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_git_init.shutil, "which", lambda _name: None)
    result = project_git_init.init_project_git(str(tmp_path))
    assert result["initialized"] is False
    assert result["git_available"] is False
    assert result["error"] == "git_not_available"


def test_reports_git_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_git_init.shutil, "which", lambda _name: "/usr/bin/git")

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["git", "init"], returncode=128, stderr=b"boom")

    monkeypatch.setattr(project_git_init.subprocess, "run", fake_run)
    result = project_git_init.init_project_git(str(tmp_path))
    assert result["initialized"] is False
    assert result["error"] == "boom"
