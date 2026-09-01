"""安全写入用户技能文件的跨平台文件系统辅助。"""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path
from typing import Union

SkillContent = Union[str, bytes]


def _lstat(path: Path, *, allow_missing: bool) -> bool:
    """拒绝符号链接，并返回路径是否存在。"""
    try:
        mode = os.lstat(str(path)).st_mode
    except FileNotFoundError:
        if allow_missing:
            return False
        raise
    if stat.S_ISLNK(mode):
        raise OSError(f"Refusing skill write through symlink: {path}")
    return True


def _open_posix_skill_file(
    root: Path, name: str, content: SkillContent, *, overwrite: bool
) -> None:
    """通过目录 fd 打开技能文件，避免目录替换造成的 TOCTOU。"""
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(str(root), directory_flags | nofollow)
    try:
        try:
            skill_dir_fd = os.open(name, directory_flags | nofollow, dir_fd=root_fd)
        except FileNotFoundError:
            os.mkdir(name, 0o700, dir_fd=root_fd)  # noqa: PTH102 - dir_fd 安全创建
            skill_dir_fd = os.open(name, directory_flags | nofollow, dir_fd=root_fd)

        try:
            flags = os.O_WRONLY | os.O_CREAT
            if overwrite:
                try:
                    existing = os.stat(  # noqa: PTH116 - dirfd-relative no-follow security primitive
                        "SKILL.md", dir_fd=skill_dir_fd, follow_symlinks=False
                    )
                except FileNotFoundError:
                    existing = None
                if existing is not None and existing.st_nlink != 1:
                    raise OSError("Refusing skill write to non-private regular file")
            flags |= os.O_EXCL if not overwrite else 0
            file_fd = os.open(
                "SKILL.md", flags | nofollow, 0o600, dir_fd=skill_dir_fd
            )
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                os.close(file_fd)
                file_fd = -1
                raise OSError("Refusing skill write to non-private regular file")
            if overwrite:
                os.ftruncate(file_fd, 0)
        finally:
            os.close(skill_dir_fd)
    finally:
        os.close(root_fd)

    try:
        mode = "wb" if isinstance(content, bytes) else "w"
        kwargs = {} if mode == "wb" else {"encoding": "utf-8"}
        stream = os.fdopen(file_fd, mode, **kwargs)
    except BaseException:
        with suppress(OSError):
            os.close(file_fd)
        raise

    with stream:
        stream.write(content)


def prepare_skill_write_path(skills_root: Path, name: str, *, overwrite: bool) -> Path:
    """校验并准备 ``<root>/<name>/SKILL.md``，绝不跟随已有 symlink。"""
    root = skills_root.expanduser()
    _lstat(root, allow_missing=False)
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    root_resolved = root.resolve()
    target_dir = root / name
    target_file = target_dir / "SKILL.md"
    try:
        target_dir.resolve().relative_to(root_resolved)
    except ValueError as exc:
        raise OSError(f"Refusing skill write outside skills root: {target_dir}") from exc

    _lstat(target_dir, allow_missing=True)
    if not target_dir.exists():
        target_dir.mkdir()
    _lstat(root, allow_missing=False)
    _lstat(target_dir, allow_missing=False)
    if not target_dir.is_dir():
        raise NotADirectoryError(str(target_dir))

    target_exists = _lstat(target_file, allow_missing=True)
    if target_exists and not overwrite:
        raise FileExistsError(str(target_file))
    return target_file


def _open_windows_skill_file(
    root: Path, name: str, content: SkillContent, *, overwrite: bool
) -> None:
    """拒绝使用无法证明 reparse point 安全性的 Windows 路径 API。

    ``lstat`` followed by ``os.open(str(path), ...)`` 仍有 TOCTOU 窗口：父目录
    可以在检查后被 junction 替换。Windows Python 也没有可移植、等价于 POSIX
    ``openat(O_NOFOLLOW)`` 的 ``dir_fd`` 语义。除非这里接入并验证原生 handle
    实现，否则任何字符串路径写入都必须 fail-closed。
    """
    del root, name, content, overwrite
    raise OSError(
        "Refusing skill write on Windows: no verified reparse-safe handle API"
    )


def write_skill_file(
    skills_root: Path, name: str, content: SkillContent, *, overwrite: bool
) -> Path:
    """写入技能文件；POSIX 使用目录 fd，Windows 无可靠方案时 fail-closed。"""
    if os.name == "nt":
        # Do this before prepare_skill_write_path: that helper creates directories
        # using ordinary paths and must never be treated as a Windows security
        # primitive. A future native handle implementation can replace this branch.
        _open_windows_skill_file(
            skills_root.expanduser(), name, content, overwrite=overwrite
        )
        raise AssertionError("unreachable")  # pragma: no cover

    target = prepare_skill_write_path(skills_root, name, overwrite=overwrite)
    _open_posix_skill_file(skills_root.expanduser(), name, content, overwrite=overwrite)
    return target
