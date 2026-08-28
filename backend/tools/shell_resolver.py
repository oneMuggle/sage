"""跨平台 shell 探测。"""

from __future__ import annotations

import ctypes
import functools
import ntpath
import os
import shutil
from dataclasses import dataclass
from typing import Optional, Tuple

SHELL_FALLBACK_NOTE = (
    "未找到 bash（已尝试 PATH 与 Git for Windows 安装目录），"
    "改用 PowerShell 执行。bash 专有语法（&&、||、$()、管道到 sh）可能不生效，"
    "请改用 PowerShell 等价写法。"
)

_POSIX_CANDIDATES: Tuple[Tuple[str, str], ...] = (("/bin/bash", "bash"), ("/bin/sh", "sh"))
_GIT_BASH_RELATIVE = ntpath.join("Git", "bin", "bash.exe")
_POWERSHELL_RELATIVE = ntpath.join("System32", "WindowsPowerShell", "v1.0", "powershell.exe")
_PROGRAM_FILES_CSIDL = (0x0026, 0x002A)


@dataclass(frozen=True)
class ShellSpec:
    """一次 shell 调用需要的全部信息。"""

    executable: str
    args_prefix: Tuple[str, ...]
    kind: str

    @property
    def is_fallback(self) -> bool:
        """是否为 PowerShell 降级。"""
        return self.kind == "powershell"


def _is_local_windows_absolute(path: object) -> bool:
    """只接受带盘符且盘符后以分隔符开头的本地 Windows 路径。"""
    if not isinstance(path, str):
        return False
    drive, tail = ntpath.splitdrive(path)
    return len(drive) == 2 and drive[1] == ":" and tail.startswith(("\\", "/"))


def _is_regular_file(path: object) -> bool:
    return isinstance(path, str) and bool(os.path.isfile(path))  # noqa: PTH113


def _canonical_windows_path(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path)).replace("/", "\\").rstrip("\\")


def _get_windows_program_files_roots() -> Tuple[str, ...]:
    """通过 Win32 known folders 获取受信任的 Program Files 根目录。"""
    if os.name != "nt":
        return ()
    try:
        shell32 = ctypes.windll.shell32
        roots = []
        for csidl in _PROGRAM_FILES_CSIDL:
            buffer = ctypes.create_unicode_buffer(32768)
            result = shell32.SHGetFolderPathW(None, csidl, None, 0, buffer)
            value = buffer.value
            if result == 0 and value and _is_local_windows_absolute(value):
                roots.append(value)
        return tuple(roots)
    except (AttributeError, OSError, TypeError):
        return ()


def _get_windows_system_directory() -> Optional[str]:
    """通过 Win32 API 获取系统目录的根路径，不信任环境变量。"""
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetWindowsDirectoryW(buffer, len(buffer))
        value = buffer.value if length else ""
        return value if value and _is_local_windows_absolute(value) else None
    except (AttributeError, OSError, TypeError):
        return None


def _resolve_posix() -> ShellSpec:
    for path, kind in _POSIX_CANDIDATES:
        if _is_regular_file(path):
            return ShellSpec(executable=path, args_prefix=("-c",), kind=kind)
    return ShellSpec(executable="/bin/sh", args_prefix=("-c",), kind="sh")


def _trusted_git_bash_path(path: object, roots: Tuple[str, ...]) -> Optional[str]:
    if not _is_local_windows_absolute(path) or not _is_regular_file(path):
        return None
    if path.endswith(("\\", "/")):
        return None
    candidate = _canonical_windows_path(path)
    for root in roots:
        if not _is_local_windows_absolute(root):
            continue
        expected = _canonical_windows_path(ntpath.join(root, _GIT_BASH_RELATIVE))
        if candidate == expected:
            return path
    return None


def _find_windows_bash() -> Optional[str]:
    roots = _get_windows_program_files_roots()
    from_path = _trusted_git_bash_path(shutil.which("bash"), roots)
    if from_path:
        return from_path
    for root in roots:
        if not _is_local_windows_absolute(root):
            continue
        candidate = ntpath.join(root, _GIT_BASH_RELATIVE)
        if _is_regular_file(candidate):
            return candidate
    return None


def _find_powershell() -> Optional[str]:
    root = _get_windows_system_directory()
    if not root or not _is_local_windows_absolute(root):
        return None
    candidate = ntpath.join(root, _POWERSHELL_RELATIVE)
    return candidate if _is_regular_file(candidate) else None


def _resolve_windows() -> ShellSpec:
    bash_path = _find_windows_bash()
    if bash_path:
        return ShellSpec(executable=bash_path, args_prefix=("-c",), kind="bash")
    powershell = _find_powershell()
    if not powershell:
        raise RuntimeError("未找到可信的 PowerShell 可执行文件；拒绝使用不安全的裸文件名。")
    return ShellSpec(executable=powershell, args_prefix=("-NoProfile", "-Command"), kind="powershell")


def resolve_shell_uncached() -> ShellSpec:
    """探测可用 shell（不走缓存）。"""
    if os.name == "nt":
        return _resolve_windows()
    return _resolve_posix()


@functools.lru_cache(maxsize=1)
def resolve_shell() -> ShellSpec:
    """探测可用 shell（进程内缓存一次）。"""
    return resolve_shell_uncached()


__all__ = ["ShellSpec", "SHELL_FALLBACK_NOTE", "resolve_shell", "resolve_shell_uncached"]
