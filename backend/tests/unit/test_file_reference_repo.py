"""file_reference_repo 单元测试（P5, 2026-11-05 设计 §9）。"""

from __future__ import annotations

import pytest

from backend.data.file_reference_repo import (
    KIND_DIRECTORY,
    KIND_FILE,
    KIND_SYMLINK,
    FileReferenceConflictError,
    FileReferenceRepository,
    InvalidReferencePathError,
    normalize_rel_path,
    normalize_target_path,
)

pytestmark = pytest.mark.unit


class TestNormalizeRelPath:
    def test_posix_and_backslash_normalized(self):
        assert normalize_rel_path("data\\cases") == "data/cases"
        assert normalize_rel_path("./data//cases/") == "data/cases"

    @pytest.mark.parametrize(
        "bad",
        ["", "   ", "/etc/passwd", "C:\\tmp", "data/../../etc", "a\x00b"],
    )
    def test_rejects_escape_and_absolute(self, bad):
        with pytest.raises(InvalidReferencePathError):
            normalize_rel_path(bad)


class TestNormalizeTargetPath:
    def test_keeps_absolute(self):
        assert normalize_target_path("/mnt/cases/./x") == "/mnt/cases/x"

    @pytest.mark.parametrize("bad", ["", "relative/path", "/tmp/a\x00b"])
    def test_rejects_relative_or_nul(self, bad):
        with pytest.raises(InvalidReferencePathError):
            normalize_target_path(bad)


class TestFileReferenceRepository:
    def test_create_list_get_delete(self, tmp_path):
        repo = FileReferenceRepository()
        target = str(tmp_path / "cases")
        created = repo.create(
            "proj-1", "data/cases", target, kind=KIND_DIRECTORY, alias_name="cases"
        )
        assert created.id
        assert created.kind == KIND_DIRECTORY
        assert created.alias_name == "cases"

        listed = repo.list_by_project("proj-1")
        assert [ref.id for ref in listed] == [created.id]
        assert repo.get(created.id).rel_path == "data/cases"
        assert repo.find_by_rel_path("proj-1", "data/cases").id == created.id
        assert repo.delete(created.id) is True
        assert repo.get(created.id) is None
        assert repo.delete(created.id) is False

    def test_duplicate_rel_path_conflicts(self, tmp_path):
        repo = FileReferenceRepository()
        repo.create("proj-1", "data/cases", str(tmp_path), kind=KIND_DIRECTORY)
        with pytest.raises(FileReferenceConflictError):
            repo.create("proj-1", "data/cases", str(tmp_path / "other"))

    def test_same_rel_path_allowed_across_projects(self, tmp_path):
        repo = FileReferenceRepository()
        first = repo.create("proj-1", "data/cases", str(tmp_path))
        second = repo.create("proj-2", "data/cases", str(tmp_path))
        assert first.id != second.id

    def test_default_alias_from_basename(self, tmp_path):
        ref = FileReferenceRepository().create(
            "proj-1", "docs/notes", str(tmp_path)
        )
        assert ref.alias_name == "notes"

    def test_upsert_symlink_creates_then_updates_target(self, tmp_path):
        repo = FileReferenceRepository()
        first = repo.upsert_symlink("proj-1", "linked", str(tmp_path / "a"))
        assert first.kind == KIND_SYMLINK

        updated = repo.upsert_symlink("proj-1", "linked", str(tmp_path / "b"))
        assert updated.id == first.id
        assert updated.target_path == normalize_target_path(str(tmp_path / "b"))
        assert len(repo.list_by_project("proj-1")) == 1

    def test_upsert_symlink_does_not_override_manual_reference(self, tmp_path):
        repo = FileReferenceRepository()
        manual = repo.create(
            "proj-1", "linked", str(tmp_path / "manual"), kind=KIND_FILE
        )
        result = repo.upsert_symlink("proj-1", "linked", str(tmp_path / "scan"))
        assert result.id == manual.id
        assert result.kind == KIND_FILE
        assert result.target_path == normalize_target_path(str(tmp_path / "manual"))

    def test_invalid_kind_rejected(self, tmp_path):
        with pytest.raises(InvalidReferencePathError):
            FileReferenceRepository().create(
                "proj-1", "x", str(tmp_path), kind="socket"
            )
