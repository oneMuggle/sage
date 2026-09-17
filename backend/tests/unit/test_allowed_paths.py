"""allowed_paths 路径匹配引擎单元测试。

覆盖场景：

- 目录包含检查（规则指向已存在目录）
- 通配符匹配（*, **, ?）
- ~ 展开为 home 目录
- 路径遍历防护（.. 和符号链接）
- 空 allowed_paths 返回 False
- 无效路径处理
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.office.allowed_paths import is_allowed


class TestIsAllowed:
    """is_allowed() 函数测试。"""

    def test_empty_allowed_paths_returns_false(self):
        """空 allowed_paths 列表返回 False。"""
        assert is_allowed("/home/user/file.txt", []) is False

    def test_directory_containment(self, tmp_path: Path):
        """规则指向已存在目录时，检查候选路径是否在该目录下。"""
        # tmp_path 是已存在的目录
        rule = str(tmp_path / "**")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        candidate = subdir / "file.txt"
        candidate.write_text("test")

        assert is_allowed(str(candidate), [rule]) is True

    def test_directory_containment_outside(self, tmp_path: Path):
        """候选路径不在规则目录下，返回 False。"""
        rule = str(tmp_path / "**")
        candidate = tmp_path.parent / "other" / "file.txt"

        assert is_allowed(str(candidate), [rule]) is False

    def test_glob_star_matches_single_level(self, tmp_path: Path):
        """* 匹配单层目录或文件名。"""
        rule = str(tmp_path / "*.txt")
        candidate = tmp_path / "file.txt"

        # 创建文件使 tmp_path 存在
        candidate.write_text("test")

        assert is_allowed(str(candidate), [rule]) is True

    def test_glob_doublestar_matches_nested(self, tmp_path: Path):
        """** 匹配任意层级目录。"""
        rule = str(tmp_path / "**")
        candidate = tmp_path / "a" / "b" / "c" / "file.txt"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("test")

        assert is_allowed(str(candidate), [rule]) is True

    def test_tilde_expansion(self):
        """~ 展开为 home 目录。"""
        with patch("pathlib.Path.home") as mock_home:
            mock_home.return_value = Path("/fake/home/user")

            # 规则 ~/docs/** 应该匹配 /fake/home/user/docs/file.txt
            candidate = "/fake/home/user/docs/file.txt"
            assert is_allowed(candidate, ["~/docs/**"]) is True

    def test_path_traversal_blocked(self, tmp_path: Path):
        """路径遍历（..）被 resolve() 阻断。"""
        rule = str(tmp_path / "**")
        # /tmp/allowed_path_test/../etc/passwd 解析后不在 tmp_path 下
        candidate = str(tmp_path / ".." / "etc" / "passwd")

        # resolve() 后应该是 tmp_path.parent / "etc" / "passwd"
        # 不在 tmp_path 下，应该返回 False
        assert is_allowed(candidate, [rule]) is False

    def test_absolute_path_rule(self, tmp_path: Path):
        """绝对路径规则精确匹配。"""
        rule = str(tmp_path / "exact_file.txt")
        candidate = tmp_path / "exact_file.txt"
        candidate.write_text("test")

        assert is_allowed(str(candidate), [rule]) is True

    def test_multiple_rules_any_match(self, tmp_path: Path):
        """多条规则，任一匹配即返回 True。"""
        rule1 = str(tmp_path / "docs" / "**")
        rule2 = str(tmp_path / "images" / "**")

        # 创建 docs 和 images 目录
        (tmp_path / "docs").mkdir()
        (tmp_path / "images").mkdir()

        candidate = tmp_path / "images" / "photo.jpg"
        candidate.write_text("test")

        assert is_allowed(str(candidate), [rule1, rule2]) is True

    def test_invalid_candidate_path(self):
        """无效候选路径返回 False（不抛异常）。"""
        # 包含 NUL 字节的路径在大多数系统上无效
        invalid_path = "/tmp/\x00file.txt"
        assert is_allowed(invalid_path, ["/tmp/**"]) is False

    def test_relative_rule_without_project_root(self):
        """相对路径规则无 project_root 时返回 False。"""
        # 相对路径 "docs/**" 无 project_root 时无法展开
        assert is_allowed("/home/user/docs/file.txt", ["docs/**"]) is False

    def test_relative_rule_with_project_root(self, tmp_path: Path):
        """相对路径规则有 project_root 时正确展开。"""
        # 创建 project_root 和 docs 子目录
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "docs").mkdir()
        candidate = project_root / "docs" / "file.txt"
        candidate.write_text("test")

        # 相对路径规则 "docs/**" 相对于 project_root
        assert is_allowed(
            str(candidate), ["docs/**"], project_root=str(project_root)
        ) is True


class TestPathSafety:
    """路径安全性测试。"""

    def test_symlink_escape_blocked(self, tmp_path: Path):
        """符号链接逃逸被 resolve() 阻断。"""
        # 创建 allowed 目录和 target 文件
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()

        target_file = tmp_path / "target.txt"
        target_file.write_text("secret")

        # 在 allowed_dir 中创建指向 target_file 的符号链接
        symlink = allowed_dir / "escape_link"
        symlink.symlink_to(target_file)

        # 规则只允许 allowed_dir 下的内容
        rule = str(allowed_dir / "**")

        # 候选路径是符号链接本身（不 resolve）
        # 但 is_allowed 内部会 resolve，所以会看到真实路径 target_file
        # target_file 不在 allowed_dir 下，应该返回 False
        assert is_allowed(str(symlink), [rule]) is False

    def test_resolve_normalizes_path(self, tmp_path: Path):
        """resolve() 归一化路径（消除多余 / 和 .）。"""
        rule = str(tmp_path / "**")
        # 候选路径包含多余的 / 和 .
        candidate = str(tmp_path) + "//./subdir/./file.txt"
        Path(tmp_path / "subdir").mkdir(exist_ok=True)
        (tmp_path / "subdir" / "file.txt").write_text("test")

        assert is_allowed(candidate, [rule]) is True
