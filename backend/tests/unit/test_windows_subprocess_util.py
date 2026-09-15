"""Windows subprocess_util 行为测试（在 POSIX CI 上通过 patch 模拟 Windows）。"""

from __future__ import annotations

import os as _real_os
import subprocess
from unittest import mock

from backend.tools import subprocess_util


class _OsProxy:
    """把 subprocess_util 看到的 os 伪装成 Windows，但保留其他进程级属性。

    仅修改 ``subprocess_util.os`` 的模块级绑定，不动全局 ``os.name``，
    避免污染 pytest 内部的 Path 实例化逻辑（后者会据 ``os.name``
    选择 ``PosixPath``/``WindowsPath``）。
    """

    def __init__(self, name: str = "nt") -> None:
        object.__setattr__(self, "_name", name)

    def __getattr__(self, attribute: str):
        # Windows 上 os 没有 killpg / getpgid / waitid / setpgid —— 让
        # hasattr() 检查返回 False，模拟原生 Windows Python 环境。
        if attribute in {"killpg", "getpgid", "waitid", "setpgid"}:
            raise AttributeError(attribute)
        return getattr(_real_os, attribute)

    @property
    def name(self) -> str:  # noqa: A003 — 镜像 os.name
        return object.__getattribute__(self, "_name")


def test_spawn_verified_starts_process_on_windows_with_new_process_group(monkeypatch):
    """Windows 不应因缺少 waitid 拒绝启动 shell。"""
    process = mock.Mock(pid=1234)
    popen = mock.Mock(return_value=process)
    monkeypatch.setattr(subprocess_util, "os", _OsProxy("nt"))
    monkeypatch.setattr(subprocess_util.subprocess, "Popen", popen)

    result = subprocess_util.spawn_verified(["powershell.exe", "-Command", "Write-Output ok"])

    assert result.process is process
    assert result.process_group_id == process.pid
    popen.assert_called_once()
    # Windows 下应用 CREATE_NEW_PROCESS_GROUP 以建立独立进程组
    assert popen.call_args.kwargs["creationflags"] == subprocess_util._WINDOWS_CREATE_NEW_PROCESS_GROUP


def test_kill_process_tree_uses_taskkill_tree_on_windows(monkeypatch):
    """Windows 终止后台 shell 时应递归终止进程树。"""
    process = mock.Mock(pid=1234)
    process.poll.return_value = None
    taskkill = mock.Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(subprocess_util, "os", _OsProxy("nt"))
    monkeypatch.setattr(subprocess_util, "observe_process_exit", lambda *_: False)
    monkeypatch.setattr(subprocess_util.subprocess, "run", taskkill)
    monkeypatch.setattr(subprocess_util, "reap_process", mock.Mock(return_value=True))

    result = subprocess_util.kill_process_tree(
        process, reap=True, process_group_id=process.pid
    )

    assert result is True
    taskkill.assert_called_once_with(
        ["taskkill.exe", "/PID", "1234", "/T", "/F"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=subprocess_util._REAP_TIMEOUT_SECONDS,
    )
    process.kill.assert_not_called()


def test_kill_process_tree_falls_back_to_leader_when_taskkill_fails(monkeypatch):
    """taskkill 不可用时至少终止并回收 leader，避免后台会话泄漏。"""
    process = mock.Mock(pid=1234)
    process.poll.return_value = None
    taskkill = mock.Mock(side_effect=OSError("taskkill unavailable"))
    monkeypatch.setattr(subprocess_util, "os", _OsProxy("nt"))
    monkeypatch.setattr(subprocess_util, "observe_process_exit", lambda *_: False)
    monkeypatch.setattr(subprocess_util.subprocess, "run", taskkill)
    monkeypatch.setattr(subprocess_util, "reap_process", mock.Mock(return_value=True))

    result = subprocess_util.kill_process_tree(
        process, reap=True, process_group_id=process.pid
    )

    assert result is True
    process.kill.assert_called_once_with()


def test_kill_process_tree_falls_back_to_leader_when_taskkill_returns_failure(
    monkeypatch,
):
    """taskkill 返回非零退出码时仍要退化为 leader kill。"""
    process = mock.Mock(pid=1234)
    process.poll.return_value = None
    taskkill = mock.Mock(return_value=subprocess.CompletedProcess([], 1))
    monkeypatch.setattr(subprocess_util, "os", _OsProxy("nt"))
    monkeypatch.setattr(subprocess_util, "observe_process_exit", lambda *_: False)
    monkeypatch.setattr(subprocess_util.subprocess, "run", taskkill)
    monkeypatch.setattr(subprocess_util, "reap_process", mock.Mock(return_value=True))

    result = subprocess_util.kill_process_tree(
        process, reap=True, process_group_id=process.pid
    )

    assert result is True
    process.kill.assert_called_once_with()
