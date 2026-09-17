"""shell_resolver 跨平台 shell 探测单元测试。"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from types import SimpleNamespace

import pytest

from backend.tools import shell_resolver
from backend.tools.shell_resolver import resolve_shell_uncached

pytestmark = pytest.mark.unit


@pytest.fixture()
def _clean_shell_cache():
    shell_resolver._resolve_shell_cached.cache_clear()
    shell_resolver._detect_powershell_version.cache_clear()
    yield
    shell_resolver._resolve_shell_cached.cache_clear()
    shell_resolver._detect_powershell_version.cache_clear()


def _fake_os(monkeypatch, name, isfile=None, access=None, environ=None, getenv=None):
    """Mock os module for shell_resolver tests.

    getenv: optional function to mock os.getenv. Defaults to reading from environ dict.
    """
    environ_dict = dict(os.environ if environ is None else environ)

    def default_getenv(key, default=None):
        return environ_dict.get(key, default)

    monkeypatch.setattr(
        shell_resolver,
        "os",
        SimpleNamespace(
            name=name,
            path=SimpleNamespace(
                isfile=isfile or (lambda _path: False),
                isdir=(lambda _path: False),
                access=access or (lambda _path, _mode: False),
                dirname=shell_resolver.ntpath.dirname,
            ),
            environ=environ_dict,
            access=access or (lambda _path, _mode: False),
            X_OK=os.X_OK,
            getenv=getenv or default_getenv,
        ),
    )


def _windows(monkeypatch, *, isfile, known_roots=(), system_root=None, identity=True, sage_root=None):
    """Mock Windows environment for shell_resolver tests.

    sage_root: return value for _get_sage_install_root. Defaults to None.
    """
    _fake_os(monkeypatch, "nt", isfile=isfile)
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda _name: None)
    monkeypatch.setattr(shell_resolver, "_get_windows_program_files_roots", lambda: tuple(known_roots))
    monkeypatch.setattr(shell_resolver, "_get_windows_system_directory", lambda: system_root)
    monkeypatch.setattr(shell_resolver, "_verify_windows_file_identity", lambda _path, _expected: identity)
    # Mock _get_sage_install_root to avoid needing real Sage installation
    monkeypatch.setattr(shell_resolver, "_get_sage_install_root", lambda: sage_root)


def test_posix_prefers_bin_bash(monkeypatch):
    _fake_os(monkeypatch, "posix", isfile=lambda p: p == "/bin/bash", access=lambda p, _m: p == "/bin/bash")
    assert resolve_shell_uncached().executable == "/bin/bash"


def test_posix_falls_back_to_bin_sh(monkeypatch):
    _fake_os(monkeypatch, "posix", isfile=lambda p: p == "/bin/sh", access=lambda p, _m: p == "/bin/sh")
    assert resolve_shell_uncached().executable == "/bin/sh"


def test_posix_rejects_nonexecutable_file(monkeypatch):
    _fake_os(monkeypatch, "posix", isfile=lambda _p: True, access=lambda _p, _m: False)
    with pytest.raises(RuntimeError, match="POSIX shell"):
        resolve_shell_uncached()


def test_posix_no_shell_fails_closed(monkeypatch):
    _fake_os(monkeypatch, "posix")
    with pytest.raises(RuntimeError, match="POSIX shell"):
        resolve_shell_uncached()


def test_windows_accepts_path_bash_only_under_known_program_files_root(monkeypatch):
    root = r"C:\Program Files"
    path_bash = root + r"\Git\bin\bash.exe"
    _windows(monkeypatch, isfile=lambda p: p == path_bash, known_roots=(root,))
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: path_bash if name == "bash" else None)
    assert resolve_shell_uncached().executable == path_bash


@pytest.mark.parametrize("path", [r"C:\attacker\Git\bin\bash.exe", "bash.exe", r"\\server\share\Git\bin\bash.exe", r"\\?\C:\Program Files\Git\bin\bash.exe", r"C:\Other\bash.exe"])
def test_windows_rejects_untrusted_path_bash(monkeypatch, path):
    powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    _windows(monkeypatch, isfile=lambda p: p == powershell, known_roots=(r"C:\Program Files",), system_root=r"C:\Windows")
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: path if name == "bash" else None)
    assert resolve_shell_uncached().kind == "powershell"


def test_windows_probes_known_program_files_roots_in_order(monkeypatch):
    roots = (r"C:\Program Files", r"C:\Program Files (x86)")
    expected = roots[1] + r"\Git\bin\bash.exe"
    probes = []

    def isfile(path):
        probes.append(path)
        return path == expected

    _windows(monkeypatch, isfile=isfile, known_roots=roots)
    assert resolve_shell_uncached().executable == expected
    assert probes == [root + r"\Git\bin\bash.exe" for root in roots]


def test_windows_ignores_attacker_program_files_environment(monkeypatch):
    _fake_os(monkeypatch, "nt", isfile=lambda _p: True, environ={"PROGRAMFILES": r"C:\attacker"})
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda _name: None)
    monkeypatch.setattr(shell_resolver, "_get_windows_program_files_roots", lambda: ())
    monkeypatch.setattr(shell_resolver, "_get_windows_system_directory", lambda: None)
    with pytest.raises(RuntimeError, match="可信.*PowerShell"):
        resolve_shell_uncached()


@pytest.mark.parametrize("base", [r"\foo", "/foo", r"C:foo", r"\\server\share", r"\\?\C:\Windows", "relative"])
def test_local_windows_absolute_rejects_unsafe_paths(base):
    assert not shell_resolver._is_local_windows_absolute(base)


def test_windows_accepts_known_system_powershell(monkeypatch):
    root = r"C:\Windows"
    powershell = root + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    _windows(monkeypatch, isfile=lambda p: p == powershell, system_root=root)
    assert resolve_shell_uncached().executable == powershell


def test_windows_never_accepts_path_powershell(monkeypatch):
    _windows(monkeypatch, isfile=lambda _p: True, system_root=None)
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: r"C:\attacker\powershell.exe" if name == "powershell" else None)
    with pytest.raises(RuntimeError, match="可信.*PowerShell"):
        resolve_shell_uncached()


def test_windows_rejects_reparse_resolved_executable(monkeypatch):
    root = r"C:\Program Files"
    path_bash = root + r"\Git\bin\bash.exe"
    _windows(monkeypatch, isfile=lambda p: p == path_bash, known_roots=(root,), identity=False)
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: path_bash if name == "bash" else None)
    with pytest.raises(RuntimeError, match="PowerShell"):
        resolve_shell_uncached()


class _Win32Function:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


def _fake_kernel(monkeypatch, kernel):
    monkeypatch.setattr(
        shell_resolver,
        "os",
        SimpleNamespace(name="nt", path=SimpleNamespace(isfile=lambda _p: True)),
    )
    monkeypatch.setattr(shell_resolver.ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)


def _set_buffer(buffer, value):
    buffer.value = value
    return len(value)


def test_canonical_windows_path_strips_extended_prefix():
    assert shell_resolver._canonical_windows_path(r"\\?\C:\Program Files\Git\bin\bash.exe") == shell_resolver._canonical_windows_path(
        r"C:\Program Files\Git\bin\bash.exe"
    )


@pytest.mark.parametrize("path", [r"\\server\share\tool.exe", r"\\.\PhysicalDrive0", r"\\?\UNC\server\share\tool.exe"])
def test_canonical_windows_path_keeps_non_local_prefixes(path):
    assert shell_resolver._canonical_windows_path(path) != shell_resolver._canonical_windows_path(
        r"C:\tool.exe"
    )


def _identity_kernel(final_callback, *, attributes=None, create=None, close=None):
    return SimpleNamespace(
        GetFileAttributesW=_Win32Function(attributes or (lambda _p: 0)),
        CreateFileW=_Win32Function(create or (lambda *_args: 42)),
        GetFinalPathNameByHandleW=_Win32Function(final_callback),
        CloseHandle=_Win32Function(close or (lambda _handle: 1)),
    )


def test_fake_kernel32_verifies_extended_final_path_and_configures_abi(monkeypatch):
    expected = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    closed = []
    kernel = _identity_kernel(
        lambda _handle, buffer, _size, _flags: _set_buffer(buffer, "\\\\?\\" + expected),
        close=lambda handle: closed.append(handle) or 1,
    )
    _fake_kernel(monkeypatch, kernel)

    assert shell_resolver._verify_windows_file_identity(expected, expected)
    assert closed == [42]
    attributes, create, final_path, close = (
        kernel.GetFileAttributesW,
        kernel.CreateFileW,
        kernel.GetFinalPathNameByHandleW,
        kernel.CloseHandle,
    )
    assert attributes.argtypes == [wintypes.LPCWSTR]
    assert attributes.restype == wintypes.DWORD
    assert create.argtypes == [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    assert create.restype == wintypes.HANDLE
    assert final_path.argtypes == [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    assert final_path.restype == wintypes.DWORD
    assert close.argtypes == [wintypes.HANDLE]
    assert close.restype == wintypes.BOOL


@pytest.mark.parametrize(
    "callback",
    [
        lambda *_args: 0,
        lambda *_args: 32768,
        lambda *_args: 32769,
        lambda *_args: (_ for _ in ()).throw(RuntimeError("final path")),
    ],
)
def test_final_path_invalid_results_fail_closed(monkeypatch, callback):
    expected = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    closed = []
    kernel = _identity_kernel(callback, close=lambda handle: closed.append(handle) or 1)
    _fake_kernel(monkeypatch, kernel)

    assert not shell_resolver._verify_windows_file_identity(expected, expected)
    assert closed == [42]


@pytest.mark.parametrize(
    "setup",
    [
        lambda: {"attributes": lambda _p: 0x400},
        lambda: {"attributes": lambda _p: (_ for _ in ()).throw(RuntimeError("attributes"))},
        lambda: {"create": lambda *_args: (_ for _ in ()).throw(RuntimeError("create"))},
        lambda: {"create": lambda *_args: ctypes.c_void_p(-1).value},
    ],
)
def test_kernel_errors_and_invalid_handle_fail_closed(monkeypatch, setup):
    expected = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    closed = []
    kernel = _identity_kernel(
        lambda _handle, buffer, _size, _flags: _set_buffer(buffer, expected),
        close=lambda handle: closed.append(handle) or 1,
        **setup(),
    )
    _fake_kernel(monkeypatch, kernel)

    assert not shell_resolver._verify_windows_file_identity(expected, expected)
    assert closed == []


def test_close_handle_failure_fails_closed(monkeypatch):
    expected = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    kernel = _identity_kernel(
        lambda _handle, buffer, _size, _flags: _set_buffer(buffer, expected),
        close=lambda _handle: 0,
    )
    _fake_kernel(monkeypatch, kernel)

    assert not shell_resolver._verify_windows_file_identity(expected, expected)


def test_close_handle_exception_fails_closed(monkeypatch):
    expected = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    kernel = _identity_kernel(
        lambda _handle, buffer, _size, _flags: _set_buffer(buffer, expected),
        close=lambda _handle: (_ for _ in ()).throw(RuntimeError("close")),
    )
    _fake_kernel(monkeypatch, kernel)

    assert not shell_resolver._verify_windows_file_identity(expected, expected)


def test_shell_spec_is_frozen():
    spec = shell_resolver.ShellSpec("bash", ("-c",), "bash")
    with pytest.raises(AttributeError):
        spec.kind = "sh"


@pytest.mark.usefixtures("_clean_shell_cache")
def test_resolve_shell_caches_result(monkeypatch):
    calls = []
    _fake_os(monkeypatch, "posix", isfile=lambda p: calls.append(p) or p == "/bin/bash", access=lambda p, _m: p == "/bin/bash")
    first = shell_resolver.resolve_shell()
    second = shell_resolver.resolve_shell()
    assert first == second
    assert len(calls) == 1


# === 新增测试：Win7 PowerShell 2.0 兼容性修复 (2026-09-16) ===


def test_detect_powershell_version_returns_none_on_non_windows(monkeypatch):
    """非 Windows 平台返回 None。"""
    _fake_os(monkeypatch, "posix")
    shell_resolver._detect_powershell_version.cache_clear()
    assert shell_resolver._detect_powershell_version() is None
    shell_resolver._detect_powershell_version.cache_clear()


def test_detect_powershell_version_returns_version_on_windows(monkeypatch):
    """Windows 平台返回 PS 版本号。"""
    powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    _windows(monkeypatch, isfile=lambda p: p == powershell, system_root=r"C:\Windows")

    # Mock subprocess.run to return a version string
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="5.1.12345\n", stderr="")

    monkeypatch.setattr(shell_resolver.subprocess, "run", fake_run)
    shell_resolver._detect_powershell_version.cache_clear()
    result = shell_resolver._detect_powershell_version()
    assert result == "5.1.12345"
    shell_resolver._detect_powershell_version.cache_clear()


def test_build_shell_fallback_note_ps2_includes_warning(monkeypatch):
    """PS 2.0 时消息包含 -Directory 不可用警告。"""
    monkeypatch.setattr(shell_resolver, "_detect_powershell_version", lambda: "2.0")
    monkeypatch.setattr(shell_resolver, "_get_bundled_python_path", lambda: None)
    note = shell_resolver.build_shell_fallback_note()
    assert "PowerShell 2.0" in note
    assert "-Directory" in note
    assert "Where-Object" in note


def test_build_shell_fallback_note_ps5_no_warning(monkeypatch):
    """PS 5.1 时消息不包含 -Directory 不可用警告。"""
    monkeypatch.setattr(shell_resolver, "_detect_powershell_version", lambda: "5.1.12345")
    monkeypatch.setattr(shell_resolver, "_get_bundled_python_path", lambda: None)
    note = shell_resolver.build_shell_fallback_note()
    assert "PowerShell 5.1.12345" in note
    # PS 5.1 should not mention -Directory being unavailable
    assert "-Directory" not in note or "不支持" not in note


def test_build_shell_fallback_note_includes_bundled_python(monkeypatch):
    """消息包含 Sage 自带 Python 路径。"""
    monkeypatch.setattr(shell_resolver, "_detect_powershell_version", lambda: "5.1")
    monkeypatch.setattr(shell_resolver, "_get_bundled_python_path", lambda: r"C:\Program Files\Sage\resources\python\python.exe")
    note = shell_resolver.build_shell_fallback_note()
    assert r"C:\Program Files\Sage\resources\python\python.exe" in note
    assert "无需扫描系统" in note


def test_get_bundled_python_path_from_env(monkeypatch):
    """优先从 SAGE_BUNDLED_PYTHON 环境变量读取。"""
    monkeypatch.setenv("SAGE_BUNDLED_PYTHON", r"C:\custom\python.exe")
    _fake_os(monkeypatch, "nt", isfile=lambda p: p == r"C:\custom\python.exe")
    result = shell_resolver._get_bundled_python_path()
    assert result == r"C:\custom\python.exe"


def test_get_bundled_python_path_from_sage_install(monkeypatch):
    """Sage 安装路径下的默认位置。"""
    monkeypatch.delenv("SAGE_BUNDLED_PYTHON", raising=False)
    _fake_os(monkeypatch, "nt", isfile=lambda p: p == r"C:\Program Files\Sage\resources\python\python.exe")
    monkeypatch.setattr(shell_resolver, "_get_sage_install_root", lambda: r"C:\Program Files\Sage")
    result = shell_resolver._get_bundled_python_path()
    assert result == r"C:\Program Files\Sage\resources\python\python.exe"


def test_get_bundled_python_path_returns_none_on_non_windows(monkeypatch):
    """非 Windows 平台返回 None。"""
    _fake_os(monkeypatch, "posix")
    assert shell_resolver._get_bundled_python_path() is None


def test_find_windows_bash_prefers_sage_bundled_bash(monkeypatch):
    """Sage 自带 bash 路径作为第三优先级候选。"""
    roots = (r"C:\Program Files",)
    sage_bash = r"C:\Program Files\Sage\tools\git-bash\bin\bash.exe"
    sage_root = r"C:\Program Files\Sage"

    # Mock: Git bash not found, Sage bundled bash found
    def isfile(p):
        return p == sage_bash

    _windows(monkeypatch, isfile=isfile, known_roots=roots, system_root=r"C:\Windows", sage_root=sage_root)

    result = shell_resolver._find_windows_bash()
    assert result == sage_bash


def test_find_windows_bash_prefers_git_bash_over_sage_bundled(monkeypatch):
    """Git for Windows bash 优先级高于 Sage 自带 bash。"""
    roots = (r"C:\Program Files",)
    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    sage_bash = r"C:\Program Files\Sage\tools\git-bash\bin\bash.exe"
    sage_root = r"C:\Program Files\Sage"

    # Mock: both exist, Git bash should be preferred
    def isfile(p):
        return p in (git_bash, sage_bash)

    _windows(monkeypatch, isfile=isfile, known_roots=roots, system_root=r"C:\Windows", sage_root=sage_root)

    result = shell_resolver._find_windows_bash()
    assert result == git_bash


@pytest.mark.usefixtures("_clean_shell_cache")
def test_resolve_shell_no_cache_on_fallback(monkeypatch):
    """fallback 时不缓存，下次调用重新探测。"""
    powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    call_count = []

    def isfile(p):
        call_count.append(p)
        return p == powershell

    _windows(monkeypatch, isfile=isfile, system_root=r"C:\Windows")

    # First call: should probe and return powershell (fallback)
    first = shell_resolver.resolve_shell()
    assert first.kind == "powershell"

    # Second call: should probe again (no cache)
    second = shell_resolver.resolve_shell()
    assert second.kind == "powershell"

    # Should have probed twice (no caching on fallback)
    assert len(call_count) >= 2


@pytest.mark.usefixtures("_clean_shell_cache")
def test_resolve_shell_caches_bash(monkeypatch):
    """找到 bash 时缓存，下次调用不重新探测。"""
    root = r"C:\Program Files"
    bash_path = root + r"\Git\bin\bash.exe"
    call_count = []

    def isfile(p):
        call_count.append(p)
        return p == bash_path

    _windows(monkeypatch, isfile=isfile, known_roots=(root,))
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: bash_path if name == "bash" else None)

    # First call: should probe and return bash
    first = shell_resolver.resolve_shell()
    assert first.kind == "bash"
    first_count = len(call_count)

    # Second call: should use cache (no new probes)
    second = shell_resolver.resolve_shell()
    assert second.kind == "bash"
    assert len(call_count) == first_count  # no new probes


def test_build_shell_fallback_note_with_explicit_version():
    """ps_version 参数用于测试时注入。"""
    note = shell_resolver.build_shell_fallback_note(ps_version="7.2.0")
    assert "PowerShell 7.2.0" in note
    assert "-Directory" not in note or "不支持" not in note
