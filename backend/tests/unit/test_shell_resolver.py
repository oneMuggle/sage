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


def _fake_os(monkeypatch, name, exists, isfile=None, environ=None):
    monkeypatch.setattr(
        shell_resolver,
        "os",
        SimpleNamespace(
            name=name,
            path=SimpleNamespace(exists=exists, isfile=isfile or exists),
            environ=dict(os.environ if environ is None else environ),
        ),
    )


def _windows(monkeypatch, *, isfile, environ=None):
    _fake_os(monkeypatch, "nt", lambda _path: False, isfile=isfile, environ=environ or {})
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda _name: None)


def test_posix_prefers_bin_bash(monkeypatch):
    _fake_os(monkeypatch, "posix", lambda p: p == "/bin/bash")
    spec = resolve_shell_uncached()
    assert spec.executable == "/bin/bash"
    assert spec.args_prefix == ("-c",)
    assert spec.kind == "bash"


def test_posix_falls_back_to_bin_sh(monkeypatch):
    _fake_os(monkeypatch, "posix", lambda p: p == "/bin/sh")
    spec = resolve_shell_uncached()
    assert spec.executable == "/bin/sh"
    assert spec.kind == "sh"


def test_windows_uses_trusted_bash_from_path(monkeypatch):
    path_bash = r"C:\Git\bin\bash.exe"
    _windows(monkeypatch, isfile=lambda p: p == path_bash)
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: path_bash if name == "bash" else None)
    spec = resolve_shell_uncached()
    assert spec.executable == path_bash
    assert spec.args_prefix == ("-c",)
    assert spec.kind == "bash"


@pytest.mark.parametrize(
    "path",
    [r"C:\Other\bash.exe", "bash.exe", "C:\\Git\\bin\\bash.exe\\", r"C:\Git\bash.exe"],
)
def test_windows_rejects_untrusted_bash_from_path(monkeypatch, path):
    _windows(monkeypatch, isfile=lambda _path: True, environ={})
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: path if name == "bash" else None)
    with pytest.raises(RuntimeError, match="PowerShell"):
        resolve_shell_uncached()


def test_windows_rejects_bash_directory_from_path(monkeypatch):
    path_bash = r"C:\Git\bin\bash.exe"
    _windows(monkeypatch, isfile=lambda _path: False, environ={"SystemRoot": r"C:\Windows"})
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: path_bash if name == "bash" else None)
    with pytest.raises(RuntimeError, match="PowerShell"):
        resolve_shell_uncached()


def test_windows_probes_program_files_git(monkeypatch):
    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    _windows(
        monkeypatch,
        isfile=lambda p: p == git_bash,
        environ={"PROGRAMFILES": r"C:\Program Files", "PROGRAMFILES(X86)": r"C:\Program Files (x86)"},
    )
    spec = resolve_shell_uncached()
    assert spec.executable == git_bash
    assert spec.kind == "bash"


def test_windows_probes_program_files_x86_after_program_files(monkeypatch):
    git_bash = r"C:\Program Files (x86)\Git\bin\bash.exe"
    probes = []

    def isfile(path):
        probes.append(path)
        return path == git_bash

    _windows(
        monkeypatch,
        isfile=isfile,
        environ={"PROGRAMFILES": r"C:\Program Files", "PROGRAMFILES(X86)": r"C:\Program Files (x86)"},
    )
    spec = resolve_shell_uncached()
    assert spec.executable == git_bash
    assert probes == [r"C:\Program Files\Git\bin\bash.exe", git_bash]


@pytest.mark.parametrize("base", [r"\foo", "/foo", r"C:foo", r"\\server\share", r"\\?\C:\Windows", "relative"])
def test_windows_rejects_untrusted_program_files_roots(monkeypatch, base):
    _windows(monkeypatch, isfile=lambda _path: True, environ={"PROGRAMFILES": base})
    with pytest.raises(RuntimeError, match="PowerShell"):
        resolve_shell_uncached()


def test_windows_rejects_program_files_directory(monkeypatch):
    _windows(monkeypatch, isfile=lambda _path: False, environ={"PROGRAMFILES": r"C:\Program Files"})
    with pytest.raises(RuntimeError, match="PowerShell"):
        resolve_shell_uncached()


def test_windows_accepts_trusted_powershell_from_path(monkeypatch):
    powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    _windows(monkeypatch, isfile=lambda p: p == powershell)
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: powershell if name == "powershell" else None)
    spec = resolve_shell_uncached()
    assert spec.executable == powershell
    assert spec.kind == "powershell"
    assert spec.args_prefix == ("-NoProfile", "-Command")
    assert spec.is_fallback
    assert shell_resolver.SHELL_FALLBACK_NOTE


def test_windows_uses_trusted_system_powershell_fallback(monkeypatch):
    powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    _windows(monkeypatch, isfile=lambda p: p == powershell, environ={"SystemRoot": r"C:\Windows"})
    spec = resolve_shell_uncached()
    assert spec.executable == powershell
    assert spec.kind == "powershell"
    assert spec.is_fallback


def test_windows_uses_windir_when_systemroot_missing(monkeypatch):
    powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    _windows(monkeypatch, isfile=lambda p: p == powershell, environ={"WINDIR": r"C:\Windows"})
    assert resolve_shell_uncached().executable == powershell


def test_windows_fails_without_trusted_powershell(monkeypatch):
    _windows(monkeypatch, isfile=lambda _path: False, environ={})
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: "powershell.exe" if name == "powershell" else None)
    with pytest.raises(RuntimeError, match="可信.*PowerShell"):
        resolve_shell_uncached()


def test_shell_spec_is_frozen():
    spec = shell_resolver.ShellSpec("bash", ("-c",), "bash")
    with pytest.raises(AttributeError):
        spec.kind = "sh"


@pytest.mark.usefixtures("_clean_shell_cache")
def test_resolve_shell_caches_result(monkeypatch):
    calls = []

    def exists(path):
        calls.append(path)
        return path == "/bin/bash"

    _fake_os(monkeypatch, "posix", exists)
    first = shell_resolver.resolve_shell()
    probe_count = len(calls)
    second = shell_resolver.resolve_shell()
    assert first == second
    assert len(calls) == probe_count
