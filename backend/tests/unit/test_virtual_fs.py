"""virtual_fs 单元测试（P5, 2026-11-05 设计 §9.2/§9.3）。

覆盖: 相对前缀翻译、精确匹配、兄弟前缀隔离、``..`` 拒绝、
绝对路径直连、目标外拒绝、符号链接越界拒绝。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.data.file_reference_repo import FileReferenceRepository
from backend.services.virtual_fs import resolve_virtual

pytestmark = pytest.mark.unit


@pytest.fixture()
def referenced_project(tmp_path):
    target = tmp_path / "target"
    (target / "001").mkdir(parents=True)
    (target / "001" / "a.md").write_text("hello", encoding="utf-8")
    FileReferenceRepository().create(
        "proj-1", "data/cases", str(target), kind="directory"
    )
    return "proj-1", target


def test_relative_path_translates_into_target(referenced_project):
    project_id, target = referenced_project
    resolved, hit = resolve_virtual(project_id, "data/cases/001/a.md")
    assert resolved == Path(os.path.normpath(str(target / "001" / "a.md")))
    assert hit is not None
    assert hit.remainder == "001/a.md"
    assert hit.direct is False


def test_exact_reference_maps_to_target_root(referenced_project):
    project_id, target = referenced_project
    resolved, hit = resolve_virtual(project_id, "data/cases")
    assert resolved == Path(os.path.normpath(str(target)))
    assert hit is not None
    assert hit.remainder == ""


def test_sibling_prefix_is_not_matched(referenced_project):
    project_id, _ = referenced_project
    resolved, hit = resolve_virtual(project_id, "data/cases2/secret.txt")
    assert hit is None
    assert resolved == Path("data/cases2/secret.txt")


def test_parent_traversal_is_rejected(referenced_project):
    project_id, _ = referenced_project
    resolved, hit = resolve_virtual(project_id, "data/cases/../../etc/passwd")
    assert hit is None
    assert resolved == Path("data/cases/../../etc/passwd")


def test_absolute_path_under_target_is_direct_hit(referenced_project):
    project_id, target = referenced_project
    absolute = str(target / "001" / "a.md")
    resolved, hit = resolve_virtual(project_id, absolute)
    assert hit is not None
    assert hit.direct is True
    assert resolved == Path(os.path.normpath(absolute))


def test_absolute_path_outside_target_is_not_matched(referenced_project):
    project_id, _ = referenced_project
    outside = "/var/lib/other/data.txt"
    resolved, hit = resolve_virtual(project_id, outside)
    assert hit is None
    assert resolved == Path(outside)


def test_symlink_escape_inside_target_is_rejected(referenced_project, tmp_path):
    project_id, target = referenced_project
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    os.symlink(str(outside), str(target / "escape"))

    resolved, hit = resolve_virtual(project_id, "data/cases/escape/secret.txt")
    assert hit is None
    assert resolved == Path("data/cases/escape/secret.txt")


def test_no_project_id_returns_original():
    resolved, hit = resolve_virtual(None, "data/cases/001/a.md")
    assert hit is None
    assert resolved == Path("data/cases/001/a.md")


def test_project_without_references_returns_original():
    resolved, hit = resolve_virtual("proj-without-refs", "data/cases/001/a.md")
    assert hit is None
    assert resolved == Path("data/cases/001/a.md")
