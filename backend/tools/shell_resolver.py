"""跨平台 shell 探测。"""

from __future__ import annotations

import ctypes
import functools
import ntpath
import os
import shutil
from ctypes import wintypes
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
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_SHARE_ALL = 0x00000007
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


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
    if not isinstance(path, str):
        return False
    drive, tail = ntpath.splitdrive(path)
    return len(drive) == 2 and drive[1] == ":" and tail.startswith(("\\", "/"))


def _is_regular_file(path: object) -> bool:
    return isinstance(path, str) and bool(os.path.isfile(path))  # noqa: PTH113


def _canonical_windows_path(path: str) -> str:
    normalized = path[4:] if path.startswith("\\\\?\\\\") else path
    return ntpath.normcase(ntpath.normpath(normalized)).replace("/", "\\").rstrip("\\")


def _get_windows_program_files_roots() -> Tuple[str, ...]:
    if os.name != "nt":
        return ()
    try:
        shell32 = ctypes.windll.shell32
        function = shell32.SHGetFolderPathW
        function.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR]
        function.restype = wintypes.HRESULT
        roots = []
        for csidl in _PROGRAM_FILES_CSIDL:
            buffer = ctypes.create_unicode_buffer(32768)
            result = function(None, csidl, None, 0, buffer)
            if result == 0 and buffer.value and _is_local_windows_absolute(buffer.value):
                roots.append(buffer.value)
        return tuple(roots)
    except Exception:
        return ()


def _get_windows_system_directory() -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        function = kernel32.GetWindowsDirectoryW
        function.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        function.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = function(buffer, len(buffer))
        if not isinstance(length, int) or length <= 0 or length >= len(buffer):
            return None
        return buffer.value if _is_local_windows_absolute(buffer.value) else None
    except Exception:
        return None


def _windows_parent_paths(path: str) -> Tuple[str, ...]:
    drive, tail = ntpath.splitdrive(ntpath.normpath(path))
    parts = [part for part in tail.replace("/", "\\").split("\\") if part]
    current = drive + "\\"
    parents = [current]
    for part in parts[:-1]:
        current = ntpath.join(current, part)
        parents.append(current)
    return tuple(parents)


def _configure_kernel32(kernel32):
    attributes = kernel32.GetFileAttributesW
    attributes.argtypes = [wintypes.LPCWSTR]
    attributes.restype = wintypes.DWORD
    create = kernel32.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    final_path = kernel32.GetFinalPathNameByHandleW
    final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    final_path.restype = wintypes.DWORD
    close = kernel32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    return attributes, create, final_path, close


def _verify_windows_file_identity(path: str, expected: str) -> bool:  # noqa: PLR0911
    if os.name != "nt" or not _is_local_windows_absolute(path) or not _is_local_windows_absolute(expected):
        return False
    try:
        attributes, create, final_path, close = _configure_kernel32(ctypes.windll.kernel32)
        for parent in _windows_parent_paths(path):
            value = attributes(parent)
            if value == 0xFFFFFFFF or value & _FILE_ATTRIBUTE_REPARSE_POINT:
                return False
        value = attributes(path)
        if value == 0xFFFFFFFF or value & _FILE_ATTRIBUTE_REPARSE_POINT:
            return False
        handle = create(path, _FILE_READ_ATTRIBUTES, _FILE_SHARE_ALL, None, _OPEN_EXISTING, _FILE_FLAG_OPEN_REPARSE_POINT, None)
        handle_value = getattr(handle, "value", handle)
        if handle_value in (None, _INVALID_HANDLE_VALUE):
            return False
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = final_path(handle, buffer, len(buffer), 0)
            if not isinstance(length, int) or length <= 0 or length >= len(buffer):
                return False
            return _canonical_windows_path(buffer.value) == _canonical_windows_path(expected)
        finally:
            close(handle)
    except Exception:
        return False


def _resolve_posix() -> ShellSpec:
    for path, kind in _POSIX_CANDIDATES:
        if _is_regular_file(path) and os.access(path, os.X_OK):
            return ShellSpec(executable=path, args_prefix=("-c",), kind=kind)
    raise RuntimeError("未找到可用的 POSIX shell（/bin/bash 和 /bin/sh 均不是可执行 regular file）。")


def _trusted_git_bash_path(path: object, roots: Tuple[str, ...]) -> Optional[str]:
    if not _is_local_windows_absolute(path) or not _is_regular_file(path) or path.endswith(("\\", "/")):
        return None
    for root in roots:
        expected = ntpath.join(root, _GIT_BASH_RELATIVE)
        if _canonical_windows_path(path) == _canonical_windows_path(expected) and _verify_windows_file_identity(path, expected):
            return path
    return None


def _find_windows_bash() -> Optional[str]:
    roots = _get_windows_program_files_roots()
    found = _trusted_git_bash_path(shutil.which("bash"), roots)
    if found:
        return found
    for root in roots:
        candidate = ntpath.join(root, _GIT_BASH_RELATIVE)
        if _is_regular_file(candidate) and _verify_windows_file_identity(candidate, candidate):
            return candidate
    return None


def _find_powershell() -> Optional[str]:
    root = _get_windows_system_directory()
    if not root:
        return None
    candidate = ntpath.join(root, _POWERSHELL_RELATIVE)
    return candidate if _is_regular_file(candidate) and _verify_windows_file_identity(candidate, candidate) else None


def _resolve_windows() -> ShellSpec:
    bash_path = _find_windows_bash()
    if bash_path:
        return ShellSpec(bash_path, ("-c",), "bash")
    powershell = _find_powershell()
    if not powershell:
        raise RuntimeError("未找到可信的 PowerShell 可执行文件；拒绝使用不安全的裸文件名。")
    return ShellSpec(powershell, ("-NoProfile", "-Command"), "powershell")


def resolve_shell_uncached() -> ShellSpec:
    if os.name == "nt":
        return _resolve_windows()
    return _resolve_posix()


@functools.lru_cache(maxsize=1)
def resolve_shell() -> ShellSpec:
    return resolve_shell_uncached()


__all__ = ["ShellSpec", "SHELL_FALLBACK_NOTE", "resolve_shell", "resolve_shell_uncached"]
