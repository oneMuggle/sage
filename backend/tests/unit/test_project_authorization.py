from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.wiki.project_authorization import (
    authorize_registered_project,
    authorize_registration,
    canonical_project_path,
)


def test_canonical_rejects_invalid_paths(tmp_path: Path):
    assert canonical_project_path("") is None
    assert canonical_project_path("relative") is None
    assert canonical_project_path("/tmp/bad\x00path") is None


def test_unregistered_project_is_forbidden(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    (project / "wiki").mkdir(parents=True)
    monkeypatch.setattr("backend.wiki.project_authorization.load_recent", lambda: [])
    with pytest.raises(HTTPException) as exc:
        authorize_registered_project(str(project))
    assert exc.value.status_code == 403


def test_registered_project_is_allowed(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    (project / "wiki").mkdir(parents=True)
    monkeypatch.setattr(
        "backend.wiki.project_authorization.load_recent",
        lambda: [type("Entry", (), {"path": str(project), "name": "p"})()],
    )
    assert authorize_registered_project(str(project)) == project.resolve()


def test_registered_deleted_project_returns_404(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    (project / "wiki").mkdir(parents=True)
    monkeypatch.setattr(
        "backend.wiki.project_authorization.load_recent",
        lambda: [type("Entry", (), {"path": str(project), "name": "p"})()],
    )
    import shutil

    shutil.rmtree(project)
    with pytest.raises(HTTPException) as exc:
        authorize_registered_project(str(project))
    assert exc.value.status_code == 404


def test_registration_requires_real_wiki_directory(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(HTTPException) as exc:
        authorize_registration(str(project), "open")
    assert exc.value.status_code == 404
