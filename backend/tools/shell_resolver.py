"""跨平台 shell 探测。"""

from __future__ import annotations

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


def _is_trusted_git_bash(path: object) -> bool:
    if not _is_local_windows_absolute(path) or not _is_regular_file(path):
        return False
    if path.endswith(("\\", "/")):
        return False
    normalized = ntpath.normcase(ntpath.normpath(path)).replace("/", "\\")
    return normalized.endswith("\\git\\bin\\bash.exe")


def _resolve_posix() -> ShellSpec:
    for path, kind in _POSIX_CANDIDATES:
        if os.path.exists(path):
            return ShellSpec(executable=path, args_prefix=("-c",), kind=kind)
    return ShellSpec(executable="/bin/sh", args_prefix=("-c",), kind="sh")


def _find_windows_bash() -> Optional[str]:
    from_path = shutil.which("bash")
    if _is_trusted_git_bash(from_path):
        return from_path
    for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_key)
        if not _is_local_windows_absolute(base):
            continue
        candidate = ntpath.join(base, _GIT_BASH_RELATIVE)
        if _is_regular_file(candidate):
            return candidate
    return None


def _find_powershell() -> Optional[str]:
    from_path = shutil.which("powershell")
    if _is_local_windows_absolute(from_path) and _is_regular_file(from_path):
        return from_path
    for env_key in ("SystemRoot", "WINDIR"):
        root = os.environ.get(env_key)
        if not _is_local_windows_absolute(root):
            continue
        candidate = ntpath.join(root, _POWERSHELL_RELATIVE)
        if _is_regular_file(candidate):
            return candidate
    return None


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
