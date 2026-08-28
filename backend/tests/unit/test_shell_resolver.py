"""shell_resolver 跨平台 shell 探测单元测试。"""

from __future__ import annotations

import ctypes
import os
from types import SimpleNamespace

import pytest

from backend.tools import shell_resolver
from backend.tools.shell_resolver import resolve_shell_uncached

pytestmark = pytest.mark.unit


@pytest.fixture()
def _clean_shell_cache():
    shell_resolver.resolve_shell.cache_clear()
    yield
    shell_resolver.resolve_shell.cache_clear()


def _fake_os(monkeypatch, name, isfile=None, access=None, environ=None):
    monkeypatch.setattr(
        shell_resolver,
        "os",
        SimpleNamespace(
            name=name,
            path=SimpleNamespace(
                isfile=isfile or (lambda _path: False),
                access=access or (lambda _path, _mode: False),
                dirname=shell_resolver.ntpath.dirname,
            ),
            environ=dict(os.environ if environ is None else environ),
            access=access or (lambda _path, _mode: False),
            X_OK=os.X_OK,
        ),
    )


def _windows(monkeypatch, *, isfile, known_roots=(), system_root=None, identity=True):
    _fake_os(monkeypatch, "nt", isfile=isfile)
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda _name: None)
    monkeypatch.setattr(shell_resolver, "_get_windows_program_files_roots", lambda: tuple(known_roots))
    monkeypatch.setattr(shell_resolver, "_get_windows_system_directory", lambda: system_root)
    monkeypatch.setattr(shell_resolver, "_verify_windows_file_identity", lambda _path, _expected: identity)


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


def test_fake_kernel32_verifies_final_path_and_closes_handle(monkeypatch):
    root = r"C:\Windows"
    expected = root + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    closed = []

    class Function:
        def __init__(self, callback):
            self.callback = callback
        def __call__(self, *args):
            return self.callback(*args)

    kernel = SimpleNamespace(
        GetFileAttributesW=Function(lambda _p: 0),
        CreateFileW=Function(lambda *_args: 42),
        GetFinalPathNameByHandleW=Function(lambda _h, buf, _size, _flags: _set_buffer(buf, expected)),
        CloseHandle=Function(lambda handle: closed.append(handle) or 1),
    )
    monkeypatch.setattr(shell_resolver, "os", SimpleNamespace(name="nt", path=SimpleNamespace(isfile=lambda _p: True)))
    monkeypatch.setattr(shell_resolver.ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    assert shell_resolver._verify_windows_file_identity(expected, expected)
    assert closed == [42]


def _set_buffer(buffer, value):
    buffer.value = value
    return len(value)


def test_fake_kernel32_reparse_and_invalid_results_fail_closed(monkeypatch):
    root = r"C:\Windows"
    expected = root + r"\System32\WindowsPowerShell\v1.0\powershell.exe"

    class Function:
        def __init__(self, callback):
            self.callback = callback
        def __call__(self, *args):
            return self.callback(*args)

    kernel = SimpleNamespace(
        GetFileAttributesW=Function(lambda _p: 0x400),
        CreateFileW=Function(lambda *_args: ctypes.c_void_p(-1).value),
        GetFinalPathNameByHandleW=Function(lambda *_args: 32768),
        CloseHandle=Function(lambda _h: 1),
    )
    monkeypatch.setattr(shell_resolver, "os", SimpleNamespace(name="nt", path=SimpleNamespace(isfile=lambda _p: True)))
    monkeypatch.setattr(shell_resolver.ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
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
