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


# ===== P6 桥接: projects 注册表命中视为已登记（recents ∪ registry）=====


def test_projects_registry_hit_grants_access(tmp_path: Path, monkeypatch):
    """recents 为空但 projects 注册表命中 → 授权通过（P6 桥接）。"""
    project = tmp_path / "project"
    (project / "wiki").mkdir(parents=True)
    monkeypatch.setattr("backend.wiki.project_authorization.load_recent", lambda: [])
    monkeypatch.setattr(
        "backend.wiki.project_authorization._projects_registry_paths",
        lambda: [project],
    )
    assert authorize_registered_project(str(project)) == project.resolve()


def test_projects_registry_failure_fails_closed(tmp_path: Path, monkeypatch):
    """注册表读取异常 → 不放宽（fail-closed，仍 403）。"""
    project = tmp_path / "project"
    (project / "wiki").mkdir(parents=True)
    monkeypatch.setattr("backend.wiki.project_authorization.load_recent", lambda: [])

    def _boom():
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(
        "backend.wiki.project_authorization._projects_registry_paths", _boom
    )
    with pytest.raises(HTTPException) as exc:
        authorize_registered_project(str(project))
    assert exc.value.status_code == 403


def test_projects_registry_hit_but_deleted_returns_404(tmp_path: Path, monkeypatch):
    """注册表命中但目录已删 → 404 语义不变。"""
    project = tmp_path / "project"
    (project / "wiki").mkdir(parents=True)
    monkeypatch.setattr("backend.wiki.project_authorization.load_recent", lambda: [])
    monkeypatch.setattr(
        "backend.wiki.project_authorization._projects_registry_paths",
        lambda: [project],
    )
    import shutil

    shutil.rmtree(project)
    with pytest.raises(HTTPException) as exc:
        authorize_registered_project(str(project))
    assert exc.value.status_code == 404
