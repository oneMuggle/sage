"""``ResurrectedProcess`` 单元测试（2026-11-06 Phase 2，POSIX only）。"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys

import pytest

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
