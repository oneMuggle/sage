"""Regression tests for final derived-file path hardening."""

import json
from pathlib import Path

import pytest

from backend.api.wiki_routes import _create_wiki_structure
from backend.storage.recent_projects import RecentProject, save_recent
from backend.wiki.files import secure_atomic_write_file, secure_write_temp_file
from backend.wiki.ingest import _save_cache
from backend.wiki.vision import _save_cache as save_vision_cache


def test_create_wiki_structure_rejects_symlinked_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / "wiki").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match=r"Not a directory|拒绝|no-follow|regular"):
        _create_wiki_structure(project)

    assert list(outside.iterdir()) == []


def test_ingest_cache_rejects_symlinked_cache_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / ".llm-wiki").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match=r"Not a directory|拒绝|no-follow|regular"):
        _save_cache(project, {})

    assert list(outside.iterdir()) == []


def test_atomic_write_does_not_use_fixed_symlink_temp(tmp_path: Path) -> None:
    target = tmp_path / "recent-projects.json"
    outside = tmp_path / "outside.json"
    outside.write_text("keep", encoding="utf-8")
    (tmp_path / "recent-projects.json.tmp").symlink_to(outside)

    secure_atomic_write_file(tmp_path, target, "updated")

    assert target.read_text(encoding="utf-8") == "updated"
    assert outside.read_text(encoding="utf-8") == "keep"


def test_recent_projects_keeps_payload_and_ignores_fixed_temp_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
    outside = tmp_path / "outside.json"
    outside.write_text("keep", encoding="utf-8")
    (tmp_path / "recent-projects.json.tmp").symlink_to(outside)

    save_recent([RecentProject(path="/p", name="p", opened_at=1.0, intent="open")])

    assert json.loads((tmp_path / "recent-projects.json").read_text())[0]["path"] == "/p"
    assert outside.read_text(encoding="utf-8") == "keep"


def test_vision_cache_rejects_symlinked_cache_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / ".llm-wiki").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match=r"Not a directory|拒绝|no-follow|regular"):
        save_vision_cache(project, {"hash": "caption"})

    assert list(outside.iterdir()) == []


def test_research_temp_file_is_random_and_private(tmp_path: Path) -> None:
    directory = tmp_path / ".llm-wiki"
    result = secure_write_temp_file(tmp_path, directory, ".md", "report")

    assert result.parent == directory
    assert result.name != "research_fixed.md"
    assert result.stat().st_mode & 0o777 == 0o600
