# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""U19 workspace_revert 纯函数单测：hunk 切分 / 补丁重建 / 路径守卫。"""

from __future__ import annotations

import os

import pytest

from backend.office.workspace_revert import (
    build_hunk_patch,
    guard_rel_path,
    split_hunks,
)

MULTI_HUNK_DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,4 +1,5 @@
 line1
+line1-added
 line2
 line3
 line4
@@ -10,4 +11,5 @@
 line10
 line11
+line11-added
 line12
 line13
"""


class TestSplitHunks:
    def test_splits_two_hunks_with_header(self) -> None:
        hunks = split_hunks(MULTI_HUNK_DIFF)
        assert len(hunks) == 2
        for hunk in hunks:
            assert hunk.startswith("diff --git a/app.py")
            assert "@@ -1,4 +1,5 @@" in hunks[0]
            assert "@@ -10,4 +11,5 @@" in hunks[1]

    def test_empty_diff_returns_empty(self) -> None:
        assert split_hunks("") == []
        assert split_hunks("diff --git a/f b/f\nindex 111..222 100644\n") == []

    def test_single_hunk_roundtrip(self) -> None:
        single = MULTI_HUNK_DIFF.split("@@ -10")[0]
        hunks = split_hunks(single)
        assert len(hunks) == 1
        assert hunks[0] == single


class TestBuildHunkPatch:
    def test_selects_subset(self) -> None:
        patch, error = build_hunk_patch(MULTI_HUNK_DIFF, [1])
        assert error is None
        assert "@@ -10,4 +11,5 @@" in patch
        assert "@@ -1,4 +1,5 @@" not in patch
        assert patch.startswith("diff --git")

    def test_out_of_range_index_rejected(self) -> None:
        _, error = build_hunk_patch(MULTI_HUNK_DIFF, [2])
        assert error is not None
        assert "越界" in error

    def test_bool_index_rejected(self) -> None:
        _, error = build_hunk_patch(MULTI_HUNK_DIFF, [True])
        assert error is not None


class TestGuardRelPath:
    def test_relative_path_ok(self, tmp_path: os.PathLike) -> None:
        assert guard_rel_path(str(tmp_path), "src/app.py") is None

    def test_absolute_path_rejected(self, tmp_path: os.PathLike) -> None:
        assert guard_rel_path(str(tmp_path), os.path.abspath("x")) is not None

    def test_escape_rejected(self, tmp_path: os.PathLike) -> None:
        assert guard_rel_path(str(tmp_path), "../outside.py") is not None

    def test_empty_rejected(self, tmp_path: os.PathLike) -> None:
        assert guard_rel_path(str(tmp_path), "") is not None

    @pytest.mark.skipif(os.name != "nt", reason="Windows 盘符语义")
    def test_other_drive_rejected(self) -> None:
        assert guard_rel_path("C:\\repo", "D:\\evil.py") is not None
