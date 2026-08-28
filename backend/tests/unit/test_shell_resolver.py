"""shell_resolver 跨平台 shell 探测单元测试。"""

from __future__ import annotations

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


def _fake_os(monkeypatch, name, exists=None, isfile=None, environ=None):
    monkeypatch.setattr(
        shell_resolver,
        "os",
        SimpleNamespace(
            name=name,
            path=SimpleNamespace(exists=exists or (lambda _path: False), isfile=isfile or (lambda _path: False)),
            environ=dict(os.environ if environ is None else environ),
        ),
    )


def _windows(monkeypatch, *, isfile, known_roots=(), system_root=None):
    _fake_os(monkeypatch, "nt", isfile=isfile, environ={})
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda _name: None)
    monkeypatch.setattr(shell_resolver, "_get_windows_program_files_roots", lambda: tuple(known_roots))
    monkeypatch.setattr(shell_resolver, "_get_windows_system_directory", lambda: system_root)


def test_posix_prefers_bin_bash(monkeypatch):
    _fake_os(monkeypatch, "posix", isfile=lambda p: p == "/bin/bash")
    spec = resolve_shell_uncached()
    assert spec.executable == "/bin/bash"
    assert spec.args_prefix == ("-c",)
    assert spec.kind == "bash"


def test_posix_falls_back_to_bin_sh(monkeypatch):
    _fake_os(monkeypatch, "posix", isfile=lambda p: p == "/bin/sh")
    spec = resolve_shell_uncached()
    assert spec.executable == "/bin/sh"
    assert spec.kind == "sh"


def test_posix_ignores_existing_directory(monkeypatch):
    _fake_os(monkeypatch, "posix", exists=lambda _p: True, isfile=lambda _p: False)
    assert resolve_shell_uncached().executable == "/bin/sh"


def test_windows_accepts_path_bash_only_under_known_program_files_root(monkeypatch):
    root = r"C:\Program Files"
    path_bash = root + r"\Git\bin\bash.exe"
    _windows(monkeypatch, isfile=lambda p: p == path_bash, known_roots=(root,))
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: path_bash if name == "bash" else None)
    assert resolve_shell_uncached().executable == path_bash


@pytest.mark.parametrize("path", [r"C:\attacker\Git\bin\bash.exe", "bash.exe", r"\\server\share\Git\bin\bash.exe", r"\\?\C:\Program Files\Git\bin\bash.exe", r"C:\Other\bash.exe"])
def test_windows_rejects_untrusted_path_bash(monkeypatch, path):
    _windows(
        monkeypatch,
        isfile=lambda p: p == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        known_roots=(r"C:\Program Files",),
        system_root=r"C:\Windows",
    )
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: path if name == "bash" else None)
    spec = resolve_shell_uncached()
    assert spec.kind == "powershell"


def test_windows_rejects_path_bash_directory(monkeypatch):
    root = r"C:\Program Files"
    path_bash = root + r"\Git\bin\bash.exe"
    _windows(monkeypatch, isfile=lambda _p: False, known_roots=(root,), system_root=r"C:\Windows")
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: path_bash if name == "bash" else None)
    with pytest.raises(RuntimeError, match="PowerShell"):
        resolve_shell_uncached()


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
    attacker = r"C:\attacker"
    _fake_os(monkeypatch, "nt", isfile=lambda _p: True, environ={"PROGRAMFILES": attacker, "PROGRAMFILES(X86)": attacker})
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda _name: None)
    monkeypatch.setattr(shell_resolver, "_get_windows_program_files_roots", lambda: ())
    monkeypatch.setattr(shell_resolver, "_get_windows_system_directory", lambda: None)
    with pytest.raises(RuntimeError, match="PowerShell"):
        resolve_shell_uncached()


@pytest.mark.parametrize("base", [r"\foo", "/foo", r"C:foo", r"\\server\share", r"\\?\C:\Windows", "relative"])
def test_local_windows_absolute_rejects_unsafe_paths(base):
    assert not shell_resolver._is_local_windows_absolute(base)


def test_windows_accepts_known_system_powershell(monkeypatch):
    system_root = r"C:\Windows"
    powershell = system_root + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    _windows(monkeypatch, isfile=lambda p: p == powershell, system_root=system_root)
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: powershell if name == "powershell" else None)
    spec = resolve_shell_uncached()
    assert spec.executable == powershell
    assert spec.kind == "powershell"


@pytest.mark.parametrize("path", [r"C:\attacker\powershell.exe", r"C:\Windows\powershell.exe"])
def test_windows_never_accepts_path_powershell(monkeypatch, path):
    _windows(monkeypatch, isfile=lambda _p: True, system_root=None)
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: path if name == "powershell" else None)
    with pytest.raises(RuntimeError, match="可信.*PowerShell"):
        resolve_shell_uncached()


def test_windows_fails_without_known_system_powershell(monkeypatch):
    _windows(monkeypatch, isfile=lambda _p: False, system_root=None)
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: r"C:\Windows\powershell.exe" if name == "powershell" else None)
    with pytest.raises(RuntimeError, match="可信.*PowerShell"):
        resolve_shell_uncached()


def test_shell_spec_is_frozen():
    spec = shell_resolver.ShellSpec("bash", ("-c",), "bash")
    with pytest.raises(AttributeError):
        spec.kind = "sh"


@pytest.mark.usefixtures("_clean_shell_cache")
def test_resolve_shell_caches_result(monkeypatch):
    calls = []

    def isfile(path):
        calls.append(path)
        return path == "/bin/bash"

    _fake_os(monkeypatch, "posix", isfile=isfile)
    first = shell_resolver.resolve_shell()
    second = shell_resolver.resolve_shell()
    assert first == second
    assert len(calls) == 1
