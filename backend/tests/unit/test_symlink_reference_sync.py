"""扫描器符号链接 → file_references 持久化测试（P5, 2026-11-05 设计 §9.5）。"""

from __future__ import annotations

import os

import pytest

from backend.data.file_reference_repo import (
    KIND_SYMLINK,
    FileReferenceRepository,
)
from backend.data.project_repo import ProjectRepository
from backend.services.workspace_scanner import (
    WorkspaceScanner,
    sync_file_references_from_tree,
    sync_projects_from_tree,
)

pytestmark = pytest.mark.unit


def _make_symlink(link: str, target: str) -> None:
    os.symlink(target, link)


def test_symlink_registered_under_root_project(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    _make_symlink(str(root / "sub" / "link"), str(outside))

    project = ProjectRepository().register(str(root.resolve()))
    tree = WorkspaceScanner().scan(root)
    touched = sync_file_references_from_tree(project.id, tree)

    refs = FileReferenceRepository().list_by_project(project.id)
    assert len(refs) == 1
    assert refs[0].rel_path == "sub/link"
    assert refs[0].kind == KIND_SYMLINK
    assert refs[0].alias_name == "link"
    assert refs[0].target_path == os.path.realpath(str(outside))
    assert touched == [refs[0].id]


def test_symlink_attributed_to_nearest_child_project(tmp_path):
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "CLAUDE.md").write_text("ctx", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    _make_symlink(str(child / "link"), str(outside))

    root_project = ProjectRepository().register(str(root.resolve()))
    tree = WorkspaceScanner().scan(root)
    sync_projects_from_tree(root_project.id, tree)
    sync_file_references_from_tree(root_project.id, tree)

    child_project = ProjectRepository().get_project_for_workspace(
        str(child.resolve())
    )
    assert child_project is not None
    child_refs = FileReferenceRepository().list_by_project(child_project.id)
    assert [ref.rel_path for ref in child_refs] == ["link"]
    assert FileReferenceRepository().list_by_project(root_project.id) == []


def test_rescan_is_idempotent(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _make_symlink(str(root / "link"), str(outside))

    project = ProjectRepository().register(str(root.resolve()))
    sync_file_references_from_tree(project.id, WorkspaceScanner().scan(root))
    sync_file_references_from_tree(project.id, WorkspaceScanner().scan(root))

    refs = FileReferenceRepository().list_by_project(project.id)
    assert len(refs) == 1
    assert refs[0].kind == KIND_SYMLINK
