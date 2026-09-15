"""R32: Windows reparse-safe 文件原语单元测试。

本机为 Windows 时执行真实 Win32 行为；非 Windows 平台整模块跳过。
symlink 相关用例做能力探测（无特权环境自动 skip，CI windows runner 可跑）。
"""

from __future__ import annotations

import os

import pytest

from backend.tools import win_reparse_io

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(os.name != "nt", reason="Win32 原语，仅 Windows 可测"),
]


def _make_file(tmp_path, name="f.txt", data=b"hello"):
    p = tmp_path / name
    win_reparse_io.write_file_reparse_safe(str(p), data, overwrite=False)
    return p


def _symlink_or_skip(link, target):
    try:
        os.symlink(str(target), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("当前环境无 symlink 特权（非管理员/未开开发者模式）")


class TestReadFileReparseSafe:
    def test_read_roundtrip(self, tmp_path):
        p = _make_file(tmp_path, data=b"hello world")
        assert win_reparse_io.read_file_reparse_safe(str(p)) == b"hello world"

    def test_read_missing_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            win_reparse_io.read_file_reparse_safe(str(tmp_path / "nope.txt"))

    def test_read_directory_raises_not_a_directory(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            win_reparse_io.read_file_reparse_safe(str(tmp_path))


class TestWriteFileReparseSafe:
    def test_create_new_writes_bytes(self, tmp_path):
        p = tmp_path / "new.txt"
        win_reparse_io.write_file_reparse_safe(str(p), b"data", overwrite=False)
        assert p.read_bytes() == b"data"

    def test_create_new_conflict_raises_file_exists(self, tmp_path):
        p = _make_file(tmp_path)
        with pytest.raises(FileExistsError):
            win_reparse_io.write_file_reparse_safe(str(p), b"x", overwrite=False)

    def test_overwrite_truncates_and_writes(self, tmp_path):
        p = _make_file(tmp_path, data=b"longer-original")
        win_reparse_io.write_file_reparse_safe(str(p), b"short", overwrite=True)
        assert p.read_bytes() == b"short"  # 截断生效，无残留尾巴

    def test_overwrite_missing_creates_file(self, tmp_path):
        """overwrite=True 语义 = 缺失即创建、存在即截断（CREATE_ALWAYS）。"""
        p = tmp_path / "created.txt"
        win_reparse_io.write_file_reparse_safe(str(p), b"x", overwrite=True)
        assert p.read_bytes() == b"x"

    def test_hardlink_refused_on_overwrite(self, tmp_path):
        """多链接文件拒绝覆盖（对齐 POSIX st_nlink==1 私有性契约）。"""
        p = _make_file(tmp_path, data=b"original")
        link = tmp_path / "hard.link"
        try:
            os.link(str(p), str(link))
        except (OSError, NotImplementedError):
            pytest.skip("当前环境不支持 hardlink")
        with pytest.raises(OSError, match="non-private"):
            win_reparse_io.write_file_reparse_safe(str(p), b"x", overwrite=True)


class TestReparseComponentRefusal:
    def test_symlinked_leaf_refused_on_read(self, tmp_path):
        real = _make_file(tmp_path, name="real.txt", data=b"secret")
        link = tmp_path / "link.txt"
        _symlink_or_skip(link, real)

        with pytest.raises(OSError, match="refusing"):
            win_reparse_io.read_file_reparse_safe(str(link))

    def test_symlinked_component_refused_on_write(self, tmp_path):
        real_dir = tmp_path / "real-dir"
        real_dir.mkdir()
        link_dir = tmp_path / "link-dir"
        _symlink_or_skip(link_dir, real_dir)

        target = link_dir / "SKILL.md"
        with pytest.raises(OSError, match="refusing"):
            win_reparse_io.write_file_reparse_safe(str(target), b"x", overwrite=False)


class TestVerifyRegularFileReparseSafe:
    def test_regular_file_passes(self, tmp_path):
        p = _make_file(tmp_path, name="ok.txt", data=b"data")
        win_reparse_io.verify_regular_file_reparse_safe(str(p))  # 不抛即通过

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            win_reparse_io.verify_regular_file_reparse_safe(str(tmp_path / "nope.txt"))

    def test_directory_raises_not_a_directory(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            win_reparse_io.verify_regular_file_reparse_safe(str(tmp_path))

    def test_hardlinked_file_refused(self, tmp_path):
        """多链接文件拒绝（对齐单链接私有性契约）。"""
        p = _make_file(tmp_path, name="linked.txt", data=b"data")
        link = tmp_path / "hard.link"
        try:
            os.link(str(p), str(link))
        except (OSError, NotImplementedError):
            pytest.skip("当前环境不支持 hardlink")
        with pytest.raises(OSError, match="non-private|refusing"):
            win_reparse_io.verify_regular_file_reparse_safe(str(link))

    def test_symlinked_leaf_refused(self, tmp_path):
        real = _make_file(tmp_path, name="real.txt", data=b"secret")
        link = tmp_path / "link.txt"
        _symlink_or_skip(link, real)
        with pytest.raises(OSError, match="refusing|no-follow"):
            win_reparse_io.verify_regular_file_reparse_safe(str(link))
