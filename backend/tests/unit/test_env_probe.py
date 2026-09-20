# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Windows 工具链环境快照（backend/tools/env_probe.py）单元测试。"""

from __future__ import annotations

import pytest

from backend.agents.profiles import build_system_base
from backend.tools import env_probe, shell_resolver
from backend.tools.shell_resolver import ShellSpec

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_cache():
    env_probe.reset_cache()
    yield
    env_probe.reset_cache()


def _fake_windows(monkeypatch):
    monkeypatch.setattr(env_probe.os, "name", "nt")


def _fake_probes(
    monkeypatch,
    shell=None,
    shell_error=None,
    ps_version="2.0",
    bundled_python="C:\\Program Files\\Sage\\resources\\python\\python.exe",
    which=None,
    versions=None,
):
    def resolve_shell():
        if shell_error is not None:
            raise shell_error
        return shell or ShellSpec("C:\\powershell.exe", ("-NoProfile", "-Command"), "powershell")

    monkeypatch.setattr(shell_resolver, "resolve_shell", resolve_shell)
    monkeypatch.setattr(shell_resolver, "detect_powershell_version", lambda: ps_version)
    monkeypatch.setattr(shell_resolver, "get_bundled_python_path", lambda: bundled_python)
    monkeypatch.setattr(env_probe.shutil, "which", lambda name: (which or {}).get(name))
    monkeypatch.setattr(
        env_probe, "_command_version", lambda exe: (versions or {}).get(exe, "")
    )


def test_non_windows_returns_empty(monkeypatch):
    monkeypatch.setattr(env_probe.os, "name", "posix")
    assert env_probe.build_snapshot() == ""


def test_snapshot_ps2_lists_shell_python_node(monkeypatch):
    _fake_windows(monkeypatch)
    _fake_probes(
        monkeypatch,
        ps_version="2.0",
        which={"python": "C:\\Python38\\python.exe", "node": "C:\\nodejs\\node.exe"},
        versions={
            "C:\\Python38\\python.exe": "Python 3.8.10",
            "C:\\nodejs\\node.exe": "v18.20.4",
        },
    )
    block = env_probe.build_snapshot()
    assert block.startswith("<windows-environment>")
    assert "Windows PowerShell 2.0" in block
    # PS 2.0 兼容坑提示
    assert "-Directory" in block
    assert "PSIsContainer" in block
    # 自带 python + 系统 python/node 事实
    assert "Sage 自带 Python: C:\\Program Files\\Sage" in block
    assert "系统 Python: Python 3.8.10 (C:\\Python38\\python.exe)" in block
    assert "Node.js: v18.20.4 (C:\\nodejs\\node.exe)" in block
    # 引导 agent 把试错经验固化进记忆
    assert "memory_save" in block


def test_snapshot_ps5_omits_ps2_hint(monkeypatch):
    _fake_windows(monkeypatch)
    _fake_probes(monkeypatch, ps_version="5.1", which={}, versions={})
    block = env_probe.build_snapshot()
    assert "Windows PowerShell 5.1" in block
    assert "PSIsContainer" not in block
    assert "系统 Python: 未检测到" in block
    assert "Node.js: 未检测到" in block


def test_snapshot_with_bash_available(monkeypatch):
    _fake_windows(monkeypatch)
    _fake_probes(
        monkeypatch,
        shell=ShellSpec("C:\\Git\\bin\\bash.exe", ("-c",), "bash"),
        which={},
        versions={},
    )
    block = env_probe.build_snapshot()
    assert "bash (C:\\Git\\bin\\bash.exe)" in block
    assert "Windows PowerShell" not in block
    assert "PSIsContainer" not in block


def test_snapshot_shell_probe_failure_is_failsafe(monkeypatch):
    _fake_windows(monkeypatch)
    _fake_probes(monkeypatch, shell_error=RuntimeError("no trusted powershell"))
    block = env_probe.build_snapshot()
    assert "探测失败" in block


def test_snapshot_ttl_cache(monkeypatch):
    _fake_windows(monkeypatch)
    calls = {"n": 0}

    def count_shell():
        calls["n"] += 1
        return ShellSpec("C:\\powershell.exe", ("-NoProfile", "-Command"), "powershell")

    monkeypatch.setattr(shell_resolver, "resolve_shell", count_shell)
    monkeypatch.setattr(shell_resolver, "detect_powershell_version", lambda: "5.1")
    monkeypatch.setattr(shell_resolver, "get_bundled_python_path", lambda: None)
    monkeypatch.setattr(env_probe.shutil, "which", lambda name: None)
    monkeypatch.setattr(env_probe, "_command_version", lambda exe: "")

    env_probe.build_snapshot()
    env_probe.build_snapshot()
    assert calls["n"] == 1
    env_probe.build_snapshot(force_refresh=True)
    assert calls["n"] == 2


def test_build_system_base_injects_snapshot_on_windows(monkeypatch):
    _fake_windows(monkeypatch)
    monkeypatch.setattr(
        env_probe, "build_snapshot", lambda force_refresh=False: "<windows-environment>FAKE</windows-environment>"
    )
    prompt = build_system_base()
    assert "<windows-environment>FAKE</windows-environment>" in prompt


def test_build_system_base_no_snapshot_on_posix(monkeypatch):
    monkeypatch.setattr(env_probe.os, "name", "posix")
    prompt = build_system_base()
    assert "<windows-environment>" not in prompt


def test_build_system_base_survives_snapshot_crash(monkeypatch):
    _fake_windows(monkeypatch)

    def boom(force_refresh=False):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(env_probe, "build_snapshot", boom)
    prompt = build_system_base()
    assert prompt.startswith("你是 Sage")
