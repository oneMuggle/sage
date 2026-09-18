"""跨平台 shell 探测。"""

from __future__ import annotations

import ctypes
import functools
import ntpath
import os
import shutil
import subprocess
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional, Tuple

_POSIX_CANDIDATES: Tuple[Tuple[str, str], ...] = (("/bin/bash", "bash"), ("/bin/sh", "sh"))
_GIT_BASH_RELATIVE = ntpath.join("Git", "bin", "bash.exe")
_POWERSHELL_RELATIVE = ntpath.join("System32", "WindowsPowerShell", "v1.0", "powershell.exe")
_SAGE_BUNDLED_BASH_RELATIVE = ntpath.join("tools", "git-bash", "bin", "bash.exe")
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


def _is_directory(path: object) -> bool:
    return isinstance(path, str) and bool(os.path.isdir(path))  # noqa: PTH112


def _canonical_windows_path(path: str) -> str:
    normalized = path[4:] if path.startswith("\\\\?\\") else path
    return ntpath.normcase(ntpath.normpath(normalized)).replace("/", "\\").rstrip("\\")


def _get_sage_install_root() -> Optional[str]:
    """获取 Sage 安装根目录（%ProgramFiles%\\Sage 或 SAGE_INSTALL_DIR 环境变量）。"""
    if os.name != "nt":
        return None
    env = os.getenv("SAGE_INSTALL_DIR")
    if env and _is_local_windows_absolute(env) and _is_directory(env):
        return env
    roots = _get_windows_program_files_roots()
    if roots:
        candidate = ntpath.join(roots[0], "Sage")
        if _is_directory(candidate):
            return candidate
    return None


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
            verified = _canonical_windows_path(buffer.value) == _canonical_windows_path(expected)
        finally:
            close_succeeded = bool(close(handle))
        return verified and close_succeeded
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


def _trusted_sage_bash_path(path: object, sage_root: Optional[str]) -> Optional[str]:
    """验证 path 是否等于 Sage 自带的 git-bash 路径。"""
    if (
        not sage_root
        or not _is_local_windows_absolute(path)
        or not _is_regular_file(path)
        or path.endswith(("\\", "/"))
    ):
        return None
    expected = ntpath.join(sage_root, "tools", "git-bash", "bin", "bash.exe")
    if _canonical_windows_path(path) == _canonical_windows_path(expected) and _verify_windows_file_identity(path, expected):
        return path
    return None


def _find_windows_bash() -> Optional[str]:
    """查找可用的 bash 可执行文件。

    优先级：
    1. PATH 里的 bash（必须是 Git for Windows 安装目录下的可信路径）
    2. Git for Windows 标准安装位置：%ProgramFiles%\\Git\\bin\\bash.exe
    3. Sage 自带的便携 bash：%ProgramFiles%\\Sage\\tools\\git-bash\\bin\\bash.exe
    """
    roots = _get_windows_program_files_roots()
    # 1) PATH 里的 bash
    found = _trusted_git_bash_path(shutil.which("bash"), roots)
    if found:
        return found
    # 2) Git for Windows 标准安装位置
    for root in roots:
        candidate = ntpath.join(root, _GIT_BASH_RELATIVE)
        if _is_regular_file(candidate) and _verify_windows_file_identity(candidate, candidate):
            return candidate
    # 3) Sage 自带的便携 bash
    sage_root = _get_sage_install_root()
    if sage_root:
        candidate = ntpath.join(sage_root, _SAGE_BUNDLED_BASH_RELATIVE)
        if _is_regular_file(candidate) and _verify_windows_file_identity(candidate, candidate):
            return candidate
    return None


def _find_powershell() -> Optional[str]:
    root = _get_windows_system_directory()
    if not root:
        return None
    candidate = ntpath.join(root, _POWERSHELL_RELATIVE)
    return candidate if _is_regular_file(candidate) and _verify_windows_file_identity(candidate, candidate) else None


def _get_bundled_python_path() -> Optional[str]:
    """获取 Sage 自带的 Python 可执行文件路径（Win7: 3.8, main: 3.10/3.11）。

    优先从 SAGE_BUNDLED_PYTHON 环境变量读取，否则用默认安装路径。
    """
    if os.name != "nt":
        return None
    env_path = os.getenv("SAGE_BUNDLED_PYTHON")
    if env_path and _is_regular_file(env_path):
        return env_path
    sage_root = _get_sage_install_root()
    if sage_root:
        candidate = ntpath.join(sage_root, "resources", "python", "python.exe")
        if _is_regular_file(candidate):
            return candidate
    return None


@functools.lru_cache(maxsize=1)
def _detect_powershell_version() -> Optional[str]:
    """探测系统 PowerShell 主版本号（2.0 / 5.1 / 7.x 等），失败返回 None。

    通过执行 PowerShell 内置变量 $PSVersionTable.PSVersion 获取。
    用 lru_cache 缓存，整个进程生命周期只探测一次。
    """
    if os.name != "nt":
        return None
    try:
        ps_exe = _find_powershell()
        if not ps_exe:
            return None
        result = subprocess.run(
            [ps_exe, "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
             "$PSVersionTable.PSVersion.ToString()"],
            capture_output=True, text=True, timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.strip() or None
    except Exception:
        pass
    return None


def build_shell_fallback_note(ps_version: Optional[str] = None) -> str:
    """动态构建 fallback 消息，包含 PS 版本 + Sage 自带 Python 路径。

    ps_version 参数用于测试时注入，生产调用时为 None，会自动探测。
    """
    version = ps_version or _detect_powershell_version() or "未知"
    bundled_python = _get_bundled_python_path()
    base = (
        "未找到 bash（已尝试 PATH、Git for Windows 安装目录、Sage 自带 bash），"
        f"改用 Windows PowerShell {version} 执行。"
    )
    if version.startswith("2.") or version == "未知":
        base += (
            " PowerShell 2.0 不支持 -Directory/-File/-LiteralPath 等 PS 5.0+ 参数；"
            "请用 `Get-ChildItem | Where-Object { $_.PSIsContainer }` 替代 `-Directory`，"
            "或改用 `Test-Path -PathType Container` 判断目录。"
        )
    else:
        base += " bash 专有语法（&&、||、$()、管道到 sh）可能不生效，请改用 PowerShell 等价写法。"
    if bundled_python:
        base += f" Sage 自带 Python 路径: {bundled_python}（无需扫描系统）。"
    return base


# 保留为静态字符串，向后兼容未升级调用方
SHELL_FALLBACK_NOTE = (
    "未找到 bash（已尝试 PATH 与 Git for Windows 安装目录），"
    "改用 PowerShell 执行。bash 专有语法（&&、||、$()、管道到 sh）可能不生效，"
    "请改用 PowerShell 等价写法。"
)


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
def _resolve_shell_cached() -> ShellSpec:
    """内部缓存包装层。fallback 时由外层 resolve_shell() 主动 cache_clear()。"""
    return resolve_shell_uncached()


def resolve_shell() -> ShellSpec:
    """获取当前平台的 shell 配置。

    关键特性：如果降级到 PowerShell（fallback），则立即清缓存，
    让下次调用重新探测。这样如果用户后来安装了 Git for Windows
    或 PowerShell 5.1，会自动生效，无需重启后端。

    找到真正的 bash 时缓存（bash 安装后不会卸载，所以缓存安全）。

    实现细节：lru_cache 装饰器在函数返回后才会写入缓存，
    所以 ``cache_clear()`` 必须在**外层**调用才能真正清除。
    """
    spec = _resolve_shell_cached()
    if spec.is_fallback:
        _resolve_shell_cached.cache_clear()
    return spec


__all__ = [
    "ShellSpec",
    "SHELL_FALLBACK_NOTE",
    "build_shell_fallback_note",
    "resolve_shell",
    "resolve_shell_uncached",
]
