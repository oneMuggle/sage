"""``ResurrectedProcess`` 单元测试（2026-11-06 Phase 2，POSIX only）。"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from backend.tools import subprocess_util
from backend.tools.subprocess_util import UNKNOWN_EXIT_CODE, ResurrectedProcess

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(os.name == "nt", reason="pgid 校验仅 POSIX"),
]


def _spawn_sleep(seconds: int = 60) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        start_new_session=True,
    )


def _kill_group(process: subprocess.Popen) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)


class TestResurrectedProcess:
    def test_live_process_polls_running(self) -> None:
        process = _spawn_sleep()
        try:
            pgid = os.getpgid(process.pid)
            proc = ResurrectedProcess(pid=process.pid, pgid=pgid)
            assert proc.poll() is None
        finally:
            _kill_group(process)

    def test_dead_process_polls_unknown_exit(self) -> None:
        process = _spawn_sleep(0)
        pgid = os.getpgid(process.pid)
        process.wait(timeout=5)
        proc = ResurrectedProcess(pid=process.pid, pgid=pgid)
        assert proc.poll() == UNKNOWN_EXIT_CODE
        # 幂等
        assert proc.poll() == UNKNOWN_EXIT_CODE

    def test_pgid_mismatch_means_pid_recycled(self) -> None:
        process = _spawn_sleep()
        try:
            proc = ResurrectedProcess(pid=process.pid, pgid=os.getpgid(process.pid) + 1)
            assert proc.poll() == UNKNOWN_EXIT_CODE
        finally:
            _kill_group(process)

    def test_wait_timeout_raises(self) -> None:
        process = _spawn_sleep()
        try:
            proc = ResurrectedProcess(pid=process.pid, pgid=os.getpgid(process.pid))
            with pytest.raises(subprocess.TimeoutExpired):
                proc.wait(timeout=0.1)
        finally:
            _kill_group(process)

    def test_wait_returns_unknown_code_after_exit(self) -> None:
        process = _spawn_sleep(0)
        pgid = os.getpgid(process.pid)
        process.wait(timeout=5)
        proc = ResurrectedProcess(pid=process.pid, pgid=pgid)
        assert proc.wait(timeout=1) == UNKNOWN_EXIT_CODE


class TestProcessStartToken:
    def test_current_process_token_is_stable(self) -> None:
        token = subprocess_util.process_start_token(os.getpid())
        assert token
        assert subprocess_util.process_start_token(os.getpid()) == token

    def test_dead_pid_returns_none(self) -> None:
        process = _spawn_sleep(0)
        process.wait(timeout=5)
        assert subprocess_util.process_start_token(process.pid) is None

    def test_matching_token_keeps_process_alive(self) -> None:
        process = _spawn_sleep()
        try:
            token = subprocess_util.process_start_token(process.pid)
            assert token is not None
            proc = ResurrectedProcess(
                pid=process.pid, pgid=os.getpgid(process.pid), start_token=token
            )
            assert proc.poll() is None
        finally:
            _kill_group(process)

    def test_mismatched_token_marks_dead(self) -> None:
        process = _spawn_sleep()
        try:
            proc = ResurrectedProcess(
                pid=process.pid,
                pgid=os.getpgid(process.pid),
                start_token="bogus:token",
            )
            assert proc.poll() == UNKNOWN_EXIT_CODE
        finally:
            _kill_group(process)

    def test_token_read_failure_fails_closed(self, monkeypatch) -> None:
        process = _spawn_sleep()
        try:
            monkeypatch.setattr(subprocess_util, "process_start_token", lambda pid: None)
            proc = ResurrectedProcess(
                pid=process.pid,
                pgid=os.getpgid(process.pid),
                start_token="expected",
            )
            assert proc.poll() == UNKNOWN_EXIT_CODE
        finally:
            _kill_group(process)


class TestWindowsProbe:
    """Windows 存活探测（tasklist）——在 Linux 上通过 monkeypatch 覆盖。"""

    def _patch(self, monkeypatch, run_impl):
        monkeypatch.setattr(subprocess_util, "_IS_WINDOWS", True)
        monkeypatch.setattr(subprocess_util, "_windows_alive_cache", {})
        monkeypatch.setattr(subprocess_util.subprocess, "run", run_impl)

    def test_alive_when_tasklist_contains_pid(self, monkeypatch) -> None:
        completed = SimpleNamespace(stdout='"python.exe","1234","Console","1","1 K"\n')
        self._patch(monkeypatch, lambda *a, **k: completed)
        assert subprocess_util._windows_process_alive(1234) is True

    def test_dead_when_tasklist_empty(self, monkeypatch) -> None:
        completed = SimpleNamespace(stdout="INFO: No tasks are running...\n")
        self._patch(monkeypatch, lambda *a, **k: completed)
        assert subprocess_util._windows_process_alive(1234) is False

    def test_tasklist_failure_fails_closed(self, monkeypatch) -> None:
        def boom(*a, **k):
            raise OSError("tasklist missing")

        self._patch(monkeypatch, boom)
        assert subprocess_util._windows_process_alive(1234) is False

    def test_probe_cache_avoids_repeat_spawn(self, monkeypatch) -> None:
        calls = []
        completed = SimpleNamespace(stdout='"python.exe","42","Console","1","1 K"')

        def fake_run(*a, **k):
            calls.append(1)
            return completed

        self._patch(monkeypatch, fake_run)
        assert subprocess_util._windows_process_alive(42) is True
        assert subprocess_util._windows_process_alive(42) is True
        assert len(calls) == 1

    def test_poll_uses_windows_probe(self, monkeypatch) -> None:
        monkeypatch.setattr(subprocess_util, "_IS_WINDOWS", True)
        monkeypatch.setattr(
            subprocess_util, "_windows_process_alive", lambda pid: True
        )
        alive = subprocess_util.ResurrectedProcess(pid=1, pgid=1)
        assert alive.poll() is None

        monkeypatch.setattr(
            subprocess_util, "_windows_process_alive", lambda pid: False
        )
        dead = subprocess_util.ResurrectedProcess(pid=2, pgid=2)
        assert dead.poll() == subprocess_util.UNKNOWN_EXIT_CODE
