"""Filesystem traversal helpers for Wiki content."""

from __future__ import annotations

import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path
from typing import Iterator, Tuple


def _directory_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)


def _require_posix_safety() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if os.name != "posix" or not nofollow or not hasattr(os, "O_DIRECTORY"):
        raise OSError("Wiki 文件操作在当前平台不具备可靠的 no-follow 原语")

    required_dir_fd = (os.open, os.mkdir, os.stat, os.unlink, os.rmdir, os.rename)
    if any(function not in os.supports_dir_fd for function in required_dir_fd):
        raise OSError("Wiki 文件操作缺少 dir_fd/openat 能力")
    if os.scandir not in os.supports_fd:
        raise OSError("Wiki 文件操作缺少目录 fd 遍历能力")
    return nofollow


def is_reparse_point(path: Path) -> bool:
    """Return whether a path has Windows reparse-point metadata."""
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    return bool(attributes & 0x0400)


def _win_abspath(root: Path, target: Path, *, allow_root: bool = False) -> Path:
    """W5 Windows 分支骨架：逃逸拒绝 + 逐组件 reparse 检查。

    刻意不走 abspath/resolve —— 那会把 ``..`` 词法折叠成越界路径。
    ``_relative_parts`` 先按 POSIX 同款契约拒绝越界/``..``/空段，再拼接
    后做逐组件 reparse 检查（缺失组件放行，缺失错误由后续打开语义表达）。
    """
    from backend.tools.win_reparse_io import verify_no_reparse

    if allow_root and Path(target) == Path(root):
        absolute = Path(root)
    else:
        parts = _relative_parts(root, target)
        absolute = root.joinpath(*parts)
    if not verify_no_reparse(str(absolute)):
        raise OSError(f"拒绝 reparse 组件: {absolute}")
    return absolute


def _win_remove_tree(absolute: Path) -> None:
    """递归删除已验证目录；条目级 reparse/非 regular 一律拒绝。"""
    for entry in os.scandir(absolute):
        try:
            entry_stat = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise OSError("拒绝删除不可核验的 Wiki 条目") from exc
        if entry_stat.st_file_attributes & 0x400:
            raise OSError("拒绝删除符号链接")
        if stat.S_ISDIR(entry_stat.st_mode):
            _win_remove_tree(Path(entry.path))
        elif stat.S_ISREG(entry_stat.st_mode):
            os.unlink(entry.path)
        else:
            raise OSError("拒绝删除非 regular Wiki 文件")
    os.rmdir(absolute)  # noqa: PTH106 — reparse-safe 递归删除要求路径形式与条目校验一致


def _relative_parts(root: Path, path: Path) -> Tuple[str, ...]:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise OSError("Wiki 文件路径不在项目目录内") from exc
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise OSError("Wiki 文件路径无效")
    return parts


def _open_existing_directory(parent_fd: int, name: str, nofollow: int) -> int:
    fd = os.open(name, _directory_flags() | nofollow, dir_fd=parent_fd)
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise NotADirectoryError(name)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_or_create_directory(parent_fd: int, name: str, nofollow: int) -> int:
    try:
        return _open_existing_directory(parent_fd, name, nofollow)
    except FileNotFoundError:
        os.mkdir(name, 0o700, dir_fd=parent_fd)  # noqa: PTH102 — dirfd-relative mkdir is required
        return _open_existing_directory(parent_fd, name, nofollow)


def _open_parent(
    root: Path, parts: Tuple[str, ...], nofollow: int, *, create_missing: bool
) -> Tuple[int, int]:
    root_fd = os.open(str(root), _directory_flags() | nofollow)
    current_fd = root_fd
    try:
        for part in parts[:-1]:
            next_fd = (
                _open_or_create_directory(current_fd, part, nofollow)
                if create_missing
                else _open_existing_directory(current_fd, part, nofollow)
            )
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        return root_fd, current_fd
    except BaseException:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)
        raise


def _close_parent(root_fd: int, parent_fd: int) -> None:
    if parent_fd != root_fd:
        os.close(parent_fd)
    os.close(root_fd)


def _close_owned_fd(fd: int) -> None:
    """Close an owned descriptor without masking the primary exception."""
    with suppress(OSError):
        os.close(fd)


def _write_fd(fd: int, content: str) -> None:
    """Write and close an owned descriptor exactly once.

    Callers transfer ownership by setting their local fd to ``-1`` before
    calling this helper.  That keeps an I/O exception from being masked by a
    second close in the caller's cleanup path.
    """
    try:
        stream = os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        with suppress(OSError):
            os.close(fd)
        raise
    try:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    finally:
        stream.close()


def _write_bytes_fd(fd: int, content: bytes) -> None:
    """Write bytes and close an owned descriptor exactly once."""
    try:
        stream = os.fdopen(fd, "wb")
    except BaseException:
        with suppress(OSError):
            os.close(fd)
        raise
    try:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    finally:
        stream.close()


def secure_ensure_directory(root: Path, target: Path) -> None:
    """Create/open a directory path through a no-follow directory-fd chain."""
    if os.name == "nt":
        absolute = _win_abspath(root, target, allow_root=True)
        try:
            absolute.mkdir(parents=True, exist_ok=True)
        except FileExistsError as exc:
            raise NotADirectoryError(str(absolute)) from exc
        if not absolute.is_dir():
            raise NotADirectoryError(root)
        return
    nofollow = _require_posix_safety()
    if target == root:
        root_fd = os.open(str(root), _directory_flags() | nofollow)
        try:
            if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                raise NotADirectoryError(root)
        finally:
            os.close(root_fd)
        return
    parts = _relative_parts(root, target)
    root_fd, parent_fd = _open_parent(root, parts, nofollow, create_missing=True)
    try:
        child_fd = _open_or_create_directory(parent_fd, parts[-1], nofollow)
        os.close(child_fd)
    finally:
        _close_parent(root_fd, parent_fd)


def secure_write_file(root: Path, target: Path, content: str) -> None:
    """Write via a stable POSIX directory-fd chain; unsupported platforms fail closed."""
    if os.name == "nt":
        from backend.tools.win_reparse_io import write_file_reparse_safe

        absolute = _win_abspath(root, target)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        # overwrite=True（CREATE_ALWAYS）+ 句柄复核：reparse/目录/多链接
        # 一律拒绝（原语内 _validate_info），契约与 POSIX 分支对齐。
        write_file_reparse_safe(str(absolute), content.encode("utf-8"), overwrite=True)
        return
    nofollow = _require_posix_safety()
    parts = _relative_parts(root, target)
    root_fd, parent_fd = _open_parent(root, parts, nofollow, create_missing=True)
    try:
        try:
            existing = os.stat(  # noqa: PTH116 — dirfd-relative no-follow stat is required
                parts[-1], dir_fd=parent_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            existing = None
        if existing is not None and existing.st_nlink > 1:
            raise OSError("拒绝写入多链接 Wiki 文件")
        fd = os.open(
            parts[-1],
            os.O_WRONLY | os.O_CREAT | nofollow,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise OSError("拒绝写入非 regular 文件")
            if opened.st_nlink > 1:
                raise OSError("拒绝写入多链接 Wiki 文件")
            os.ftruncate(fd, 0)
            owned_fd = fd
            fd = -1
            _write_fd(owned_fd, content)
        finally:
            if fd != -1:
                os.close(fd)
    finally:
        _close_parent(root_fd, parent_fd)


def secure_write_temp_file(root: Path, directory: Path, suffix: str, content: str) -> Path:
    """Create a random private temporary regular file inside ``directory``."""
    if os.name == "nt":
        from backend.tools.win_reparse_io import write_file_reparse_safe

        directory_absolute = _win_abspath(root, directory)
        directory_absolute.mkdir(parents=True, exist_ok=True)
        for _ in range(10):
            name = f".tmp-{secrets.token_hex(16)}{suffix}"
            try:
                write_file_reparse_safe(
                    str(directory_absolute / name), content.encode("utf-8"), overwrite=False
                )
                return directory / name
            except FileExistsError:
                continue
        raise OSError("无法创建安全临时文件")
    nofollow = _require_posix_safety()
    directory_parts = _relative_parts(root, directory)
    secure_ensure_directory(root, directory)
    root_fd = os.open(str(root), _directory_flags() | nofollow)
    current_fd = root_fd
    fd = -1
    name = ""
    completed = False
    try:
        for part in directory_parts:
            child_fd = _open_existing_directory(current_fd, part, nofollow)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = child_fd
        for _ in range(10):
            name = f".tmp-{secrets.token_hex(16)}{suffix}"
            try:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                    0o600,
                    dir_fd=current_fd,
                )
                break
            except FileExistsError:
                continue
        else:
            raise OSError("无法创建安全临时文件")
        owned_fd = fd
        fd = -1
        _write_fd(owned_fd, content)
        completed = True
        return directory / name
    finally:
        if not completed:
            with suppress(OSError):
                os.unlink(name, dir_fd=current_fd)
        if fd != -1:
            os.close(fd)
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def secure_create_temp_file(root: Path, directory: Path, suffix: str) -> Tuple[Path, int]:
    """Create a private regular temp file and retain its descriptor."""
    if os.name == "nt":
        from backend.tools.win_reparse_io import create_new_write_fd_reparse_safe

        directory_absolute = _win_abspath(root, directory)
        directory_absolute.mkdir(parents=True, exist_ok=True)
        for _ in range(10):
            name = f".tmp-{secrets.token_hex(16)}{suffix}"
            try:
                return directory / name, create_new_write_fd_reparse_safe(
                    str(directory_absolute / name)
                )
            except FileExistsError:
                continue
        raise OSError("无法创建安全临时文件")
    nofollow = _require_posix_safety()
    directory_parts = _relative_parts(root, directory)
    secure_ensure_directory(root, directory)
    root_fd = os.open(str(root), _directory_flags() | nofollow)
    current_fd = root_fd
    try:
        for part in directory_parts:
            child_fd = _open_existing_directory(current_fd, part, nofollow)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = child_fd
        for _ in range(10):
            name = f".tmp-{secrets.token_hex(16)}{suffix}"
            try:
                fd = os.open(
                    name, os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow, 0o600,
                    dir_fd=current_fd,
                )
                return directory / name, fd
            except FileExistsError:
                continue
        raise OSError("无法创建安全临时文件")
    finally:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)

def secure_write_temp_bytes(root: Path, directory: Path, suffix: str, content: bytes) -> Path:
    """Create a random private temporary file containing ``content`` bytes."""
    if os.name == "nt":
        from backend.tools.win_reparse_io import write_file_reparse_safe

        directory_absolute = _win_abspath(root, directory)
        directory_absolute.mkdir(parents=True, exist_ok=True)
        for _ in range(10):
            name = f".tmp-{secrets.token_hex(16)}{suffix}"
            try:
                write_file_reparse_safe(str(directory_absolute / name), content, overwrite=False)
                return directory / name
            except FileExistsError:
                continue
        raise OSError("无法创建安全临时文件")
    nofollow = _require_posix_safety()
    directory_parts = _relative_parts(root, directory)
    secure_ensure_directory(root, directory)
    root_fd = os.open(str(root), _directory_flags() | nofollow)
    current_fd = root_fd
    fd = -1
    name = ""
    completed = False
    try:
        for part in directory_parts:
            child_fd = _open_existing_directory(current_fd, part, nofollow)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = child_fd
        for _ in range(10):
            name = f".tmp-{secrets.token_hex(16)}{suffix}"
            try:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                    0o600,
                    dir_fd=current_fd,
                )
                break
            except FileExistsError:
                continue
        else:
            raise OSError("无法创建安全临时文件")
        owned_fd = fd
        fd = -1
        _write_bytes_fd(owned_fd, content)
        completed = True
        return directory / name
    finally:
        if not completed:
            with suppress(OSError):
                os.unlink(name, dir_fd=current_fd)
        if fd != -1:
            os.close(fd)
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def secure_publish_held_temp(
    root: Path, temp: Path, target: Path, fd: int
) -> None:
    """Publish a held temp inode after verifying its dirfd pathname binding."""
    if os.name == "nt":
        temp_absolute = _win_abspath(root, temp)
        target_absolute = _win_abspath(root, target)
        if temp_absolute.parent != target_absolute.parent:
            raise OSError("临时文件和目标必须位于同一目录")
        held = os.fstat(fd)
        if not stat.S_ISREG(held.st_mode):
            raise OSError("拒绝发布非 regular 临时文件")
        current = temp_absolute.lstat()
        if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
            raise OSError("临时文件在发布前发生变化")
        try:
            existing = target_absolute.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            (existing.st_file_attributes & 0x400) or not stat.S_ISREG(existing.st_mode)
        ):
            raise OSError("拒绝覆盖非 regular 文件")
        os.replace(temp_absolute, target_absolute)  # noqa: PTH105 — MoveFileExW 原子替换语义
        return
    nofollow = _require_posix_safety()
    temp_parts = _relative_parts(root, temp)
    target_parts = _relative_parts(root, target)
    if temp_parts[:-1] != target_parts[:-1]:
        raise OSError("临时文件和目标必须位于同一目录")
    root_fd, parent_fd = _open_parent(root, temp_parts, nofollow, create_missing=False)
    try:
        held = os.fstat(fd)
        if not stat.S_ISREG(held.st_mode):
            raise OSError("拒绝发布非 regular 临时文件")
        current = os.stat(  # noqa: PTH116 — dirfd-relative no-follow stat is required for TOCTOU protection
            temp_parts[-1], dir_fd=parent_fd, follow_symlinks=False
        )
        if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
            raise OSError("临时文件在发布前发生变化")
        try:
            existing = os.stat(  # noqa: PTH116 — dirfd-relative no-follow stat is required for safe target validation
                target_parts[-1], dir_fd=parent_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            existing = None
        if existing is not None and (stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode)):
            raise OSError("拒绝覆盖非 regular 文件")
        os.rename(  # noqa: PTH104 — dirfd-relative atomic rename is required for safe publication
            temp_parts[-1], target_parts[-1],
            src_dir_fd=parent_fd, dst_dir_fd=parent_fd,
        )
    finally:
        _close_parent(root_fd, parent_fd)


def secure_write_file_if_missing(root: Path, target: Path, content: str) -> bool:
    """Create a regular file once, without following a leaf link."""
    if os.name == "nt":
        from backend.tools.win_reparse_io import write_file_reparse_safe

        absolute = _win_abspath(root, target)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        try:
            write_file_reparse_safe(str(absolute), content.encode("utf-8"), overwrite=False)
            return True
        except FileExistsError:
            existing = absolute.lstat()
            if (existing.st_file_attributes & 0x400) or not stat.S_ISREG(existing.st_mode):
                raise OSError("拒绝使用非 regular Wiki 文件")
            if existing.st_nlink > 1:
                raise OSError("拒绝使用多链接 Wiki 文件")
            return False
    nofollow = _require_posix_safety()
    parts = _relative_parts(root, target)
    root_fd, parent_fd = _open_parent(root, parts, nofollow, create_missing=True)
    try:
        try:
            fd = os.open(
                parts[-1],
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            existing = os.stat(  # noqa: PTH116 — dirfd-relative no-follow stat is required
                parts[-1], dir_fd=parent_fd, follow_symlinks=False
            )
            if not stat.S_ISREG(existing.st_mode):
                raise OSError("拒绝使用非 regular Wiki 文件")
            if existing.st_nlink > 1:
                raise OSError("拒绝使用多链接 Wiki 文件")
            return False
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise OSError("拒绝写入非 regular 文件")
            if opened.st_nlink > 1:
                raise OSError("拒绝写入多链接 Wiki 文件")
            owned_fd = fd
            fd = -1
            _write_fd(owned_fd, content)
        finally:
            if fd != -1:
                os.close(fd)
        return True
    finally:
        _close_parent(root_fd, parent_fd)


def secure_atomic_write_file(root: Path, target: Path, content: str) -> None:
    """Atomically replace a regular file using a random, private dirfd temp.

    The temporary pathname is private (0600) and is verified immediately
    before rename.  POSIX platforms without the directory-fd/no-follow
    primitives are rejected rather than falling back to pathname writes.

    R32 Windows 分支：reparse-safe 原语 + MoveFileExW 原子替换（替换的是
    链接本身而非链接目标，无内容泄漏）。其余 secure_* 仍 POSIX-only。
    """
    if os.name == "nt":
        from backend.tools.win_reparse_io import (
            replace_file,
            write_file_reparse_safe,
        )

        abs_target = (root / target).absolute()
        abs_target.parent.mkdir(parents=True, exist_ok=True)
        tmp = abs_target.parent / f".{abs_target.name}.{secrets.token_hex(16)}.tmp"
        write_file_reparse_safe(str(tmp), content.encode("utf-8"), overwrite=False)
        replace_file(str(tmp), str(abs_target))
        return
    nofollow = _require_posix_safety()
    parts = _relative_parts(root, target)
    root_fd, parent_fd = _open_parent(root, parts, nofollow, create_missing=True)
    temp_name = f".{parts[-1]}.{secrets.token_hex(16)}.tmp"
    fd = -1
    try:
        fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=parent_fd,
        )
        owned_fd = fd
        fd = -1
        _write_fd(owned_fd, content)

        # Re-open only through the already-open parent fd and bind the
        # pathname to the inode we are about to rename.  A replacement is
        # rejected; importantly, the cleanup below is also dirfd-relative.
        verify_fd = os.open(temp_name, os.O_RDONLY | nofollow, dir_fd=parent_fd)
        try:
            temp_stat = os.fstat(verify_fd)
            if not stat.S_ISREG(temp_stat.st_mode) or temp_stat.st_mode & 0o777 != 0o600:
                raise OSError("拒绝使用被替换的临时文件")
            path_stat = os.stat(temp_name, dir_fd=parent_fd, follow_symlinks=False)  # noqa: PTH116
            if (path_stat.st_dev, path_stat.st_ino) != (temp_stat.st_dev, temp_stat.st_ino):
                raise OSError("临时文件在替换前发生变化")
        finally:
            os.close(verify_fd)

        try:
            target_stat = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)  # noqa: PTH116
        except FileNotFoundError:
            target_stat = None
        if target_stat is not None and (
            stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISREG(target_stat.st_mode)
        ):
            raise OSError("拒绝覆盖非 regular 文件")
        os.rename(  # noqa: PTH104 — dirfd-relative atomic rename is required
            temp_name, parts[-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd
        )
    finally:
        if fd != -1:
            os.close(fd)
        with suppress(OSError):
            os.unlink(temp_name, dir_fd=parent_fd)
        _close_parent(root_fd, parent_fd)


def _remove_tree_at(parent_fd: int, name: str, nofollow: int) -> None:
    child_fd = _open_existing_directory(parent_fd, name, nofollow)
    try:
        for entry in os.scandir(child_fd):
            if entry.is_symlink():
                os.unlink(entry.name, dir_fd=child_fd)
            elif entry.is_dir(follow_symlinks=False):
                _remove_tree_at(child_fd, entry.name, nofollow)
            elif entry.is_file(follow_symlinks=False):
                os.unlink(entry.name, dir_fd=child_fd)
            else:
                raise OSError("拒绝删除非 regular Wiki 文件")
    finally:
        os.close(child_fd)
    os.rmdir(name, dir_fd=parent_fd)  # noqa: PTH106 — dirfd-relative removal is required


def secure_delete_path(root: Path, target: Path) -> None:
    """Delete a path through directory fds without following links."""
    if os.name == "nt":
        absolute = _win_abspath(root, target)
        mode = absolute.lstat()
        if stat.S_ISLNK(mode.st_mode) or (mode.st_file_attributes & 0x400):
            raise OSError("拒绝删除符号链接")
        if stat.S_ISREG(mode.st_mode):
            absolute.unlink()
        elif stat.S_ISDIR(mode.st_mode):
            _win_remove_tree(absolute)
        else:
            raise OSError("拒绝删除非 regular Wiki 路径")
        return
    nofollow = _require_posix_safety()
    parts = _relative_parts(root, target)
    root_fd, parent_fd = _open_parent(root, parts, nofollow, create_missing=False)
    try:
        mode = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False).st_mode  # noqa: PTH116 — no-follow dirfd stat is required
        if stat.S_ISLNK(mode):
            raise OSError("拒绝删除符号链接")
        if stat.S_ISREG(mode):
            os.unlink(parts[-1], dir_fd=parent_fd)
        elif stat.S_ISDIR(mode):
            _remove_tree_at(parent_fd, parts[-1], nofollow)
        else:
            raise OSError("拒绝删除非 regular Wiki 路径")
    finally:
        _close_parent(root_fd, parent_fd)


def secure_rename_path(root: Path, old: Path, new: Path) -> None:
    """Rename regular files with directory fds; unsupported platforms fail closed."""
    if os.name == "nt":
        old_absolute = _win_abspath(root, old)
        new_absolute = _win_abspath(root, new)
        old_mode = old_absolute.lstat()
        if (
            stat.S_ISLNK(old_mode.st_mode)
            or (old_mode.st_file_attributes & 0x400)
            or not stat.S_ISREG(old_mode.st_mode)
        ):
            raise OSError("拒绝重命名非 regular Wiki 文件")
        try:
            new_mode = new_absolute.lstat()
        except FileNotFoundError:
            new_mode = None
        if new_mode is not None and (
            stat.S_ISLNK(new_mode.st_mode)
            or (new_mode.st_file_attributes & 0x400)
            or not stat.S_ISREG(new_mode.st_mode)
        ):
            raise OSError("拒绝覆盖非 regular Wiki 文件")
        os.replace(old_absolute, new_absolute)  # noqa: PTH105 — MoveFileExW 原子替换语义
        return
    nofollow = _require_posix_safety()
    old_parts = _relative_parts(root, old)
    new_parts = _relative_parts(root, new)
    old_root_fd, old_parent_fd = _open_parent(
        root, old_parts, nofollow, create_missing=False
    )
    try:
        old_mode = os.stat(old_parts[-1], dir_fd=old_parent_fd, follow_symlinks=False).st_mode  # noqa: PTH116 — no-follow dirfd stat is required
        if not stat.S_ISREG(old_mode):
            raise OSError("拒绝重命名非 regular Wiki 文件")
        new_root_fd, new_parent_fd = _open_parent(
            root, new_parts, nofollow, create_missing=True
        )
        try:
            try:
                new_mode = os.stat(new_parts[-1], dir_fd=new_parent_fd, follow_symlinks=False).st_mode  # noqa: PTH116 — no-follow dirfd stat is required
            except FileNotFoundError:
                new_mode = None
            if new_mode is not None and (stat.S_ISLNK(new_mode) or not stat.S_ISREG(new_mode)):
                raise OSError("拒绝覆盖非 regular Wiki 文件")
            os.rename(  # noqa: PTH104 — dirfd-relative rename is required
                old_parts[-1], new_parts[-1], src_dir_fd=old_parent_fd, dst_dir_fd=new_parent_fd
            )
        finally:
            _close_parent(new_root_fd, new_parent_fd)
    finally:
        _close_parent(old_root_fd, old_parent_fd)


def secure_read_file(root: Path, target: Path) -> bytes:
    """Read a regular file through a POSIX no-follow directory-fd chain.

    The returned bytes are read from the opened descriptor, not from a later
    pathname lookup.  Platforms without the required primitive fail closed.
    """
    if os.name == "nt":
        from backend.tools.win_reparse_io import read_file_reparse_safe

        return read_file_reparse_safe(str(_win_abspath(root, target)))
    fd = secure_open_file(root, target)
    try:
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def secure_read_file_bounded(root: Path, target: Path, max_bytes: int) -> bytes:
    """Read at most ``max_bytes + 1`` bytes from a no-follow regular file.

    The descriptor is opened before the size check and remains the source of
    truth.  The extra byte lets callers reject files that grow after ``fstat``
    without ever materializing an oversized payload.
    """
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if os.name == "nt":
        from backend.tools.win_reparse_io import read_file_reparse_safe

        absolute = _win_abspath(root, target)
        # 尺寸预检 + 读后长度复核（Windows 无 held-fd 流式读，读整文件后
        # 复核上界；wiki 文件体量小，内存上界可接受）。
        if absolute.lstat().st_size > max_bytes:
            raise ValueError("file exceeds configured read limit")
        payload = read_file_reparse_safe(str(absolute))
        if len(payload) > max_bytes:
            raise ValueError("file exceeds configured read limit")
        return payload
    fd = secure_open_file(root, target)
    try:
        size = os.fstat(fd).st_size
        if size > max_bytes:
            raise ValueError("file exceeds configured read limit")
        chunks = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise ValueError("file exceeds configured read limit")
        return payload
    finally:
        os.close(fd)


def secure_open_file(root: Path, target: Path) -> int:
    """Open a regular file and return an owned descriptor.

    The caller owns the returned descriptor and must close it exactly once.
    All path components are resolved relative to no-follow directory fds.
    """
    if os.name == "nt":
        from backend.tools.win_reparse_io import open_read_fd_reparse_safe

        return open_read_fd_reparse_safe(str(_win_abspath(root, target)))
    nofollow = _require_posix_safety()
    parts = _relative_parts(root, target)
    root_fd, parent_fd = _open_parent(root, parts, nofollow, create_missing=False)
    try:
        fd = os.open(parts[-1], os.O_RDONLY | nofollow, dir_fd=parent_fd)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise OSError("拒绝读取非 regular Wiki 文件")
            if opened.st_nlink > 1:
                raise OSError("拒绝读取多链接 Wiki 文件")
            owned_fd = fd
            fd = -1
            return owned_fd
        finally:
            if fd != -1:
                os.close(fd)
    finally:
        _close_parent(root_fd, parent_fd)


def secure_list_directory(root: Path, target: Path) -> Tuple[Tuple[str, bool], ...]:
    """List one directory through an opened no-follow directory descriptor.

    Returned values are immutable ``(name, is_directory)`` identifiers; no
    caller is given a pathname that it must reopen.  Symlinks, reparse-like
    entries, and non-regular/non-directory entries are omitted.
    """
    if os.name == "nt":
        absolute = _win_abspath(root, target, allow_root=True)
        entries = []
        for entry in os.scandir(absolute):
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if entry_stat.st_file_attributes & 0x400:
                continue  # symlink/junction/reparse 一律跳过
            if stat.S_ISDIR(entry_stat.st_mode):
                entries.append((entry.name, True))
            elif stat.S_ISREG(entry_stat.st_mode):
                entries.append((entry.name, False))
        return tuple(entries)
    nofollow = _require_posix_safety()
    parts = _relative_parts(root, target) if target != root else ()
    root_fd = os.open(str(root), _directory_flags() | nofollow)
    current_fd = root_fd
    try:
        for part in parts:
            child_fd = _open_existing_directory(current_fd, part, nofollow)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = child_fd
        entries = []
        for entry in os.scandir(current_fd):
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                entries.append((entry.name, True))
            elif entry.is_file(follow_symlinks=False):
                entries.append((entry.name, False))
        return tuple(entries)
    finally:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def secure_read_text(root: Path, target: Path, encoding: str = "utf-8") -> str:
    """Decode content obtained from :func:`secure_read_file`.

    R32 Windows 分支：reparse-safe 原语读取（其余 secure_* 仍 POSIX-only）。
    W5：补 ``_win_abspath`` 逃逸拒绝（R32 版本未拒绝 ``..``，本批对齐契约）。
    """
    if os.name == "nt":
        from backend.tools.win_reparse_io import read_file_reparse_safe

        return read_file_reparse_safe(str(_win_abspath(root, target))).decode(encoding)
    return secure_read_file(root, target).decode(encoding)


def _scan_wiki_dir(fd: int, path: Path) -> Iterator[Path]:
    """Recursively scan an already-open directory without following links."""
    try:
        entries = list(os.scandir(fd))
    except OSError:
        return
    for entry in entries:
        if entry.is_symlink():
            continue
        entry_path = path / entry.name
        try:
            if entry.is_dir(follow_symlinks=False):
                child_fd = _open_existing_directory(fd, entry.name, _require_posix_safety())
                try:
                    yield from _scan_wiki_dir(child_fd, entry_path)
                finally:
                    os.close(child_fd)
            elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".md"):
                yield entry_path
        except OSError:
            # A disappearing or replaced entry is not trusted.
            continue


def iter_wiki_markdown(project_root: Path) -> Iterator[Path]:
    """Yield Markdown paths from a no-follow directory-fd traversal.

    Paths are only identifiers.  Callers must use ``secure_read_file`` or
    ``secure_read_text`` when opening a yielded path.
    """
    if os.name == "nt":
        from backend.tools.win_reparse_io import verify_no_reparse

        root = Path(project_root)
        wiki_root = root / "wiki"
        if not verify_no_reparse(str(wiki_root)):
            return
        if not wiki_root.is_dir():
            return
        stack = [wiki_root]
        while stack:
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue  # 消失/被替换的条目不可信
                if entry_stat.st_file_attributes & 0x400:
                    continue  # symlink/junction/reparse 一律跳过
                entry_path = Path(entry.path)
                if stat.S_ISDIR(entry_stat.st_mode):
                    stack.append(entry_path)
                elif stat.S_ISREG(entry_stat.st_mode) and entry.name.endswith(".md"):
                    yield entry_path
        return
    _require_posix_safety()
    root = Path(project_root)
    root_fd = os.open(str(root), _directory_flags() | os.O_NOFOLLOW)
    try:
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            return
        wiki_fd = _open_existing_directory(root_fd, "wiki", os.O_NOFOLLOW)
        try:
            yield from _scan_wiki_dir(wiki_fd, root / "wiki")
        finally:
            os.close(wiki_fd)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return
    finally:
        os.close(root_fd)
