"""bash_session 后台 shell 注册表单元测试。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from backend.tools.bash_session import (
    MAX_BACKGROUND_SESSIONS,
    BashSessionRegistry,
    SessionLimitExceeded,
    get_registry,
)
from backend.tools.subprocess_util import make_temp_output_file

pytestmark = pytest.mark.unit

READ_CAP = 30 * 1024


def _spawn(registry, code: str):
    """起一个后台 python 子进程并注册，返回 BashSession。"""
    stdout_path = make_temp_output_file(prefix="sage_test_")
    stderr_path = make_temp_output_file(prefix="sage_test_")
    out_handle = open(stdout_path, "wb")  # noqa: SIM115
    err_handle = open(stderr_path, "wb")  # noqa: SIM115
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=subprocess.DEVNULL,
            stdout=out_handle,
            stderr=err_handle,
            start_new_session=True,
        )
    finally:
        out_handle.close()
        err_handle.close()
    return registry.register(process, code, stdout_path, stderr_path)


@pytest.fixture()
def registry():
    reg = BashSessionRegistry()
    yield reg
    reg.clear()


def test_register_assigns_hex_shell_id(registry):
    """注册返回的 shell_id 是纯 hex（不可能构成路径片段）。"""
    session = _spawn(registry, "print('x')")
    assert len(session.shell_id) == 32
    assert all(c in "0123456789abcdef" for c in session.shell_id)


def test_get_unknown_shell_id_returns_none(registry):
    assert registry.get("deadbeef") is None


def test_read_increment_unknown_id_returns_none_without_filesystem_access(registry):
    result = registry.read_increment("../../etc/passwd", cap=READ_CAP)
    assert result is None


def test_read_increment_reports_running_then_exited(registry):
    session = _spawn(registry, "import sys; sys.stdout.write('done'); sys.exit(3)")
    deadline = time.monotonic() + 10
    while session.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    after = registry.read_increment(session.shell_id, cap=READ_CAP)
    assert after is not None
    assert after["status"] == "exited"
    assert after["exit_code"] == 3
    assert "done" in after["stdout"]


def test_read_increment_is_incremental_across_calls(registry):
    code = (
        "import sys, time\n"
        "sys.stdout.write('first'); sys.stdout.flush()\n"
        "time.sleep(1.5)\n"
        "sys.stdout.write('second'); sys.stdout.flush()\n"
    )
    session = _spawn(registry, code)
    time.sleep(0.6)
    first = registry.read_increment(session.shell_id, cap=READ_CAP)
    time.sleep(1.5)
    second = registry.read_increment(session.shell_id, cap=READ_CAP)
    assert first is not None
    assert second is not None
    assert "first" in first["stdout"]
    assert "first" not in second["stdout"]
    assert "second" in second["stdout"]


def test_terminate_kills_running_process_and_removes_session(registry):
    session = _spawn(registry, "import time; time.sleep(30)")
    shell_id = session.shell_id
    stdout_path = session.stdout_path
    result = registry.terminate(shell_id, cap=READ_CAP)
    assert result is not None
    assert result["killed"] is True
    assert registry.get(shell_id) is None
    assert registry.count() == 0
    assert not os.path.exists(stdout_path)


def test_terminate_unknown_id_returns_none(registry):
    assert registry.terminate("nope", cap=READ_CAP) is None


def test_terminate_already_exited_session_is_not_an_error(registry):
    session = _spawn(registry, "import sys; sys.exit(0)")
    deadline = time.monotonic() + 10
    while session.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    result = registry.terminate(session.shell_id, cap=READ_CAP)
    assert result is not None
    assert result["exit_code"] == 0
    assert registry.count() == 0


def test_register_beyond_limit_raises(registry):
    for _ in range(MAX_BACKGROUND_SESSIONS):
        _spawn(registry, "import time; time.sleep(30)")
    with pytest.raises(SessionLimitExceeded):
        _spawn(registry, "import time; time.sleep(30)")


def test_get_registry_returns_process_singleton():
    assert get_registry() is get_registry()


def _wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_running_status_has_no_exit_code(registry):
    session = _spawn(registry, "import time; print('ready', flush=True); time.sleep(5)")
    assert _wait_until(lambda: Path(session.stdout_path).stat().st_size > 0)
    result = registry.read_increment(session.shell_id, READ_CAP)
    assert result["status"] == "running"
    assert result["exit_code"] is None


def test_stderr_increment_and_small_cap_advances_cursor(registry):
    session = _spawn(registry, "import sys; sys.stderr.write('abcdef'); sys.stderr.flush()")
    assert _wait_until(lambda: Path(session.stderr_path).stat().st_size >= 6)
    first = registry.read_increment(session.shell_id, 2)
    second = registry.read_increment(session.shell_id, 20)
    assert "ab" in first["stderr"]
    assert "cd" in second["stderr"]
    assert "ab" not in second["stderr"]


def test_invalid_terminate_cap_keeps_session_manageable_and_cleans(registry):
    session = _spawn(registry, "import time; time.sleep(5)")
    with pytest.raises(ValueError, match="positive integer"):
        registry.terminate(session.shell_id, 0)
    assert registry.get(session.shell_id) is session
    paths = (session.stdout_path, session.stderr_path)
    registry.terminate(session.shell_id, 1)
    for path in paths:
        assert not Path(path).exists()


def test_reentrant_lock_path(registry):
    session = _spawn(registry, "print('x')")
    with registry._lock:
        assert registry.get(session.shell_id) is session
        assert registry.count() == 1


def test_bounded_collectors_stop_and_overflow():
    import io

    from backend.tools.subprocess_util import start_bounded_output_collectors

    out = io.BytesIO(b"x" * 100)
    err = io.BytesIO(b"y" * 100)
    out_path = make_temp_output_file(prefix="collector_")
    err_path = make_temp_output_file(prefix="collector_")
    collectors = start_bounded_output_collectors(out, err, out_path, err_path, max_bytes=10)
    for collector in collectors:
        collector.join(2)
    for collector in collectors:
        assert collector.overflowed
        assert collector.bytes_written == 10
    assert Path(out_path).stat().st_size == Path(err_path).stat().st_size == 10
    os.unlink(out_path)
    os.unlink(err_path)
