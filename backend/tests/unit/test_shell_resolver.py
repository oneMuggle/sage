"""shell_resolver 跨平台 shell 探测单元测试。

全部用 monkeypatch 模拟 os.name / 文件存在性 / shutil.which，
不依赖运行测试的机器上实际装了什么。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from backend.tools import shell_resolver
from backend.tools.shell_resolver import resolve_shell_uncached

pytestmark = pytest.mark.unit


def _fake_os(monkeypatch, name, exists, environ=None):
    monkeypatch.setattr(
        shell_resolver,
        "os",
        SimpleNamespace(
            name=name,
            path=SimpleNamespace(exists=exists),
            environ=dict(os.environ if environ is None else environ),
        ),
    )


def test_posix_prefers_bin_bash(monkeypatch):
    """POSIX: /bin/bash 存在 → 用它, args_prefix 为 -c。"""
    # Arrange
    _fake_os(monkeypatch, "posix", lambda p: p == "/bin/bash")

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.executable == "/bin/bash"
    assert spec.args_prefix == ("-c",)
    assert spec.kind == "bash"


def test_posix_falls_back_to_bin_sh(monkeypatch):
    """POSIX: 无 /bin/bash → 退 /bin/sh。"""
    # Arrange
    _fake_os(monkeypatch, "posix", lambda p: p == "/bin/sh")

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.executable == "/bin/sh"
    assert spec.kind == "sh"


def test_windows_uses_bash_from_path(monkeypatch):
    """Windows: PATH 里有 bash → 用它（Git Bash 常见形态）。"""
    # Arrange
    _fake_os(monkeypatch, "nt", lambda p: False)
    monkeypatch.setattr(
        shell_resolver.shutil, "which", lambda name: r"C:\Git\bin\bash.exe" if name == "bash" else None
    )

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.executable == r"C:\Git\bin\bash.exe"
    assert spec.args_prefix == ("-c",)
    assert spec.kind == "bash"


def test_windows_probes_program_files_git(monkeypatch):
    """Windows: PATH 无 bash → 探测 Program Files 下的 Git Bash。"""
    # Arrange
    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    _fake_os(monkeypatch, "nt", lambda p: p == git_bash, {"PROGRAMFILES": r"C:\Program Files", "PROGRAMFILES(X86)": r"C:\Program Files (x86)"})
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: None)

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.executable == git_bash
    assert spec.kind == "bash"


def test_windows_probes_program_files_x86_after_program_files(monkeypatch):
    """Windows: 无 64-bit Git Bash → 按顺序探测 Program Files(X86)。"""
    # Arrange
    git_bash = r"C:\Program Files (x86)\Git\bin\bash.exe"
    probes = []

    def _exists(path):
        probes.append(path)
        return path == git_bash

    _fake_os(
        monkeypatch,
        "nt",
        _exists,
        {"PROGRAMFILES": r"C:\Program Files", "PROGRAMFILES(X86)": r"C:\Program Files (x86)"},
    )
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: None)

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.executable == git_bash
    assert probes == [
        r"C:\Program Files\Git\bin\bash.exe",
        git_bash,
    ]


    """Windows: 找不到任何 bash → 退 PowerShell, kind 标记降级。"""
    # Arrange
    _fake_os(monkeypatch, "nt", lambda p: False, {})
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: None)

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.kind == "powershell"
    assert spec.args_prefix == ("-NoProfile", "-Command")


def test_resolve_shell_caches_result(monkeypatch):
    """resolve_shell 带缓存: 第二次调用不再探测文件系统。"""
    # Arrange
    shell_resolver.resolve_shell.cache_clear()
    calls = []

    def _counting_exists(path):
        calls.append(path)
        return path == "/bin/bash"

    _fake_os(monkeypatch, "posix", _counting_exists)

    # Act
    first = shell_resolver.resolve_shell()
    probe_count = len(calls)
    second = shell_resolver.resolve_shell()

    # Assert
    assert first == second
    assert len(calls) == probe_count, "第二次调用重新探测了文件系统"
    shell_resolver.resolve_shell.cache_clear()
