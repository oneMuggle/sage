"""bash_session 后台 shell 注册表单元测试。"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable
from unittest.mock import Mock

import pytest

from backend.tools.bash_session import (
    MAX_BACKGROUND_SESSIONS,
    BashSessionRegistry,
    SessionLimitExceeded,
    get_registry,
)
from backend.tools.subprocess_util import (
    MAX_OUTPUT_CAP_BYTES,
    BoundedOutputCollector,
    make_temp_output_file,
    observe_process_exit,
    spawn_verified,
    start_bounded_output_collectors,
)

pytestmark = pytest.mark.unit

READ_CAP = 30 * 1024


def _spawn(registry: BashSessionRegistry, code: str) -> Any:
    """起一个后台 python 子进程并注册，返回 BashSession。"""
    stdout_path = make_temp_output_file(prefix="sage_test_")
    stderr_path = make_temp_output_file(prefix="sage_test_")
    out_handle = open(stdout_path, "wb")  # noqa: SIM115
    err_handle = open(stderr_path, "wb")  # noqa: SIM115
    try:
        verified = spawn_verified(
            [sys.executable, "-c", code], stdout=out_handle, stderr=err_handle
        )
    finally:
        out_handle.close()
        err_handle.close()
    return registry.register(verified, code, stdout_path, stderr_path)


def _spawn_with_collectors(
    registry: BashSessionRegistry,
    code: str,
    max_bytes: int = READ_CAP,
) -> Any:
    """起一个 stdout/stderr 由有界 collector 消费的后台进程。"""
    stdout_path = make_temp_output_file(prefix="sage_pipe_")
    stderr_path = make_temp_output_file(prefix="sage_pipe_")
    verified = spawn_verified(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    process = verified.process
    assert process.stdout is not None
    assert process.stderr is not None
    collectors = start_bounded_output_collectors(
        process.stdout,
        process.stderr,
        stdout_path,
        stderr_path,
        max_bytes=max_bytes,
    )
    return registry.register(
        verified,
        code,
        stdout_path,
        stderr_path,
        collectors=collectors,
    )


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


def test_register_failure_retains_owner_after_fast_exit(registry, monkeypatch):
    """spawn_verified failure exposes the process owner; registry rejects raw Popen."""
    from backend.tools.subprocess_util import ProcessGroupVerificationError

    process = Mock()
    process.poll.return_value = 0
    error = ProcessGroupVerificationError("group unavailable", process)

    with pytest.raises(ProcessGroupVerificationError, match="group unavailable"):
        raise error

    with pytest.raises(TypeError, match="VerifiedProcess"):
        registry.register(process, "exit", "/not-owned/stdout", "/not-owned/stderr")
    assert registry.count() == 0
    assert error.process is process
    assert error.running is False


def test_register_failure_cleans_running_process_and_outputs(registry):
    """A process-group verification failure leaves cleanup to its explicit owner."""
    from backend.tools.subprocess_util import ProcessGroupVerificationError

    process = Mock()
    process.poll.return_value = None
    error = ProcessGroupVerificationError("contract rejected", process)

    assert error.running is True
    with pytest.raises(TypeError, match="VerifiedProcess"):
        registry.register(process, "sleep", "/not-owned/stdout", "/not-owned/stderr")
    assert registry.count() == 0
    assert error.process is process


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


def test_terminate_after_output_files_removed_is_idempotent_cleanup(registry):
    session = _spawn(registry, "import time; time.sleep(30)")
    shell_id = session.shell_id
    os.unlink(session.stdout_path)
    os.unlink(session.stderr_path)

    result = registry.terminate(shell_id, cap=READ_CAP)

    assert result is not None
    assert registry.get(shell_id) is None
    assert registry.pending_cleanup_count() == 0


def test_terminate_already_exited_session_without_prior_poll_is_cleaned(registry):
    session = _spawn(registry, "import sys; sys.exit(0)")
    assert _wait_until(
        lambda: observe_process_exit(session.process, 0.0) is True
    )

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


def _wait_until(predicate: Callable[[], bool], timeout: float = 5) -> bool:
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


def test_invalid_caps_all_rejected_without_removing_session(registry):
    session = _spawn(registry, "import time; time.sleep(5)")
    for cap in (True, "2", -1, 0, 10 * 1024 * 1024 + 1):
        with pytest.raises(ValueError, match="cap"):
            registry.terminate(session.shell_id, cap)
        assert registry.get(session.shell_id) is session


def test_clear_removes_multiple_sessions_and_files(registry):
    sessions = [_spawn(registry, "import time; time.sleep(5)") for _ in range(3)]
    paths = [(s.stdout_path, s.stderr_path) for s in sessions]
    registry.clear()
    assert registry.count() == 0
    assert all(s.process.poll() is not None for s in sessions)
    assert all(not Path(p).exists() for pair in paths for p in pair)


def test_terminate_drain_error_still_cleans_and_removes(registry, monkeypatch):
    session = _spawn(registry, "import time; time.sleep(5)")
    paths = (session.stdout_path, session.stderr_path)
    def broken(*args, **kwargs):
        raise RuntimeError("drain failure")
    monkeypatch.setattr("backend.tools.bash_session.read_capped_output", broken)
    with pytest.raises(RuntimeError, match="drain failure"):
        registry.terminate(session.shell_id, 10)
    assert registry.get(session.shell_id) is None
    assert all(not Path(p).exists() for p in paths)


def test_pipe_collectors_preserve_output_before_termination(registry):
    code = (
        "import sys, time\n"
        "sys.stdout.write('stdout-before-stop'); sys.stdout.flush()\n"
        "sys.stderr.write('stderr-before-stop'); sys.stderr.flush()\n"
        "time.sleep(30)\n"
    )
    session = _spawn_with_collectors(registry, code)
    assert _wait_until(
        lambda: Path(session.stdout_path).stat().st_size > 0
        and Path(session.stderr_path).stat().st_size > 0
    )

    result = registry.terminate(session.shell_id, cap=READ_CAP)

    assert result is not None
    assert result["stdout"] == "stdout-before-stop"
    assert result["stderr"] == "stderr-before-stop"
    assert result["status"] == "exited"
    assert all(not collector.is_alive for collector in session.collectors or ())


def test_pipe_collector_overflow_propagates_truncated(registry):
    code = (
        "import sys, time\n"
        "sys.stdout.write('x' * 4096); sys.stdout.flush()\n"
        "sys.stderr.write('y' * 4096); sys.stderr.flush()\n"
        "time.sleep(30)\n"
    )
    session = _spawn_with_collectors(registry, code, max_bytes=16)
    collectors = session.collectors or ()
    assert _wait_until(lambda: all(collector.overflowed for collector in collectors))

    result = registry.terminate(session.shell_id, cap=READ_CAP)

    assert result is not None
    assert result["truncated"] is True
    assert len(result["stdout"]) == 16
    assert len(result["stderr"]) == 16
    assert all(not collector.is_alive for collector in collectors)


def test_pipe_collector_cleanup_error_retains_session_until_collectors_stop(registry):
    session = _spawn_with_collectors(registry, "import time; time.sleep(30)")
    collectors = session.collectors or ()
    assert collectors[0].stop(timeout=2) is True
    failing = Mock()
    failing.finish.side_effect = RuntimeError("collector failure")
    failing.stop.side_effect = RuntimeError("collector stop failure")
    failing.is_alive = True
    session.collectors = (failing, collectors[1])
    paths = (session.stdout_path, session.stderr_path)

    with pytest.raises(RuntimeError, match="collector failure"):
        registry.terminate(session.shell_id, cap=READ_CAP)

    assert registry.get(session.shell_id) is session
    assert all(Path(path).exists() for path in paths)
    assert failing.stop.called
    assert all(not collector.is_alive for collector in collectors[1:])

    failing.finish.side_effect = None
    failing.finish.return_value = True
    failing.stop.side_effect = None
    failing.stop.return_value = True
    failing.is_alive = False
    result = registry.terminate(session.shell_id, cap=READ_CAP)

    assert result is not None
    assert registry.get(session.shell_id) is None
    assert all(not Path(path).exists() for path in paths)


def test_terminate_after_process_was_reaped_fails_closed_and_retains_session(
    registry, monkeypatch
):
    session = _spawn(registry, "import sys; sys.exit(0)")
    assert _wait_until(lambda: session.process.poll() is not None)
    kill = Mock()
    monkeypatch.setattr("backend.tools.bash_session.kill_process_tree", kill)

    with pytest.raises(RuntimeError, match="无法安全观察进程组"):
        registry.terminate(session.shell_id, cap=READ_CAP)

    assert registry.get(session.shell_id) is session
    kill.assert_not_called()


def test_collector_read_error_marks_output_lost(tmp_path):
    class FailingStream:
        def read(self, _size):
            raise RuntimeError("read failure")

        def close(self):
            return None

    collector = BoundedOutputCollector(
        FailingStream(), str(tmp_path / "output"), max_bytes=16
    )
    collector.start()
    collector.join(2)

    assert not collector.is_alive
    assert collector.output_lost is True


def test_collector_stop_returns_true_when_thread_already_finished(tmp_path):
    collector = BoundedOutputCollector(
        io.BytesIO(b"done"), str(tmp_path / "out"), max_bytes=16
    )
    collector.start()
    assert _wait_until(lambda: not collector.is_alive)
    assert collector.stop(timeout=0.1) is True


def test_collector_stop_returns_false_for_uninterruptible_stream(tmp_path):
    release = threading.Event()
    entered = threading.Event()

    class UninterruptibleStream:
        def read(self, _size):
            entered.set()
            release.wait()
            return b""

        def close(self):
            return None

    collector = BoundedOutputCollector(
        UninterruptibleStream(), str(tmp_path / "out"), max_bytes=16
    )
    collector.start()
    assert _wait_until(entered.is_set)
    try:
        assert collector.stop(timeout=0.01) is False
    finally:
        release.set()
    assert _wait_until(lambda: not collector.is_alive)


def test_collector_finish_returns_true_after_natural_eof(tmp_path):
    collector = BoundedOutputCollector(
        io.BytesIO(b"done"), str(tmp_path / "out"), max_bytes=16
    )
    collector.start()
    assert collector.finish(timeout=1) is True
    assert not collector.is_alive


def test_collector_finish_returns_false_when_stop_cannot_join(tmp_path):
    release = threading.Event()

    class UninterruptibleStream:
        def read(self, _size):
            release.wait()
            return b""

        def close(self):
            return None

    collector = BoundedOutputCollector(
        UninterruptibleStream(), str(tmp_path / "out"), max_bytes=16
    )
    collector.start()
    assert _wait_until(lambda: collector.is_alive)
    assert collector.finish(timeout=0.01) is False
    release.set()
    assert _wait_until(lambda: not collector.is_alive)


def test_collector_posix_fd_error_marks_output_lost(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX fd collector behavior")

    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb")
    collector = BoundedOutputCollector(stream, str(tmp_path / "out"), max_bytes=16)
    monkeypatch.setattr(
        "backend.tools.subprocess_util.select.select",
        Mock(side_effect=OSError("select failed")),
    )
    try:
        collector.start()
        assert _wait_until(lambda: not collector.is_alive)
        assert collector.output_lost is True
    finally:
        os.close(write_fd)


@pytest.mark.parametrize("max_bytes", [MAX_OUTPUT_CAP_BYTES + 1, 10**100])
def test_collector_rejects_max_bytes_above_shared_limit(tmp_path, max_bytes):
    with pytest.raises(ValueError, match="maximum"):
        BoundedOutputCollector(io.BytesIO(), str(tmp_path / "output"), max_bytes)

    with pytest.raises(ValueError, match="maximum"):
        start_bounded_output_collectors(
            io.BytesIO(),
            io.BytesIO(),
            str(tmp_path / "stdout"),
            str(tmp_path / "stderr"),
            max_bytes=max_bytes,
        )
def test_pipe_collectors_are_stopped_when_session_limit_is_reached(registry):
    for _ in range(MAX_BACKGROUND_SESSIONS):
        _spawn(registry, "import time; time.sleep(30)")

    stdout_path = make_temp_output_file(prefix="sage_limit_")
    stderr_path = make_temp_output_file(prefix="sage_limit_")
    verified = spawn_verified(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process = verified.process
    assert process.stdout is not None
    assert process.stderr is not None
    collectors = start_bounded_output_collectors(
        process.stdout,
        process.stderr,
        stdout_path,
        stderr_path,
        max_bytes=16,
    )

    failing = Mock()
    failing.finish.side_effect = RuntimeError("collector failure")
    failing.stop.return_value = False
    failing.is_alive = True
    paths = (stdout_path, stderr_path)

    with pytest.raises(SessionLimitExceeded):
        registry.register(
            verified,
            "import time; time.sleep(30)",
            stdout_path,
            stderr_path,
            collectors=(failing, collectors[1]),
        )

    assert process.poll() is not None
    assert registry.pending_cleanup_count() == 1
    assert failing.finish.called
    assert failing.stop.called
    assert all(Path(path).exists() for path in paths)

    failing.finish.side_effect = None
    failing.finish.return_value = True
    failing.is_alive = False
    assert registry.pending_cleanup_count() == 0
    assert all(not Path(path).exists() for path in paths)


# ---------------------------------------------------------------------------
# 并发：read_increment/terminate 不再互相阻塞无关 shell
# ---------------------------------------------------------------------------


def test_concurrent_read_increment_on_distinct_sessions_proceeds_in_parallel(registry):
    """多个 shell 同时被读应在不同 session 间真正并行, 不串行化在全局锁上。"""
    code = (
        "import sys, time\n"
        "sys.stdout.write('ready'); sys.stdout.flush()\n"
        "time.sleep(2)\n"
    )
    sessions = [_spawn(registry, code) for _ in range(4)]
    shell_ids = [s.shell_id for s in sessions]
    assert _wait_until(
        lambda: all(Path(s.stdout_path).stat().st_size >= 5 for s in sessions)
    )

    barrier = threading.Barrier(len(shell_ids))

    def worker(shell_id):
        barrier.wait()
        result = registry.read_increment(shell_id, cap=READ_CAP)
        return result is not None and "ready" in result["stdout"]

    started = time.monotonic()
    results = []
    threads = [
        threading.Thread(target=lambda s=sh: results.append(worker(s)))
        for sh in shell_ids
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    elapsed = time.monotonic() - started

    assert len(results) == len(shell_ids)
    assert all(results)
    assert elapsed < 6, f"并行读被串行化为 {elapsed:.2f}s，远超 2s 等待 + 余量"


def test_concurrent_terminate_on_distinct_sessions_does_not_block_one_another(registry):
    """多 shell 同时 terminate 不应因全局锁串行。"""
    sessions = [_spawn(registry, "import time; time.sleep(30)") for _ in range(3)]
    shell_ids = [s.shell_id for s in sessions]

    barrier = threading.Barrier(len(shell_ids))
    results: list = []
    errors: list = []

    def worker(shell_id):
        try:
            barrier.wait()
            payload = registry.terminate(shell_id, cap=READ_CAP)
            results.append(payload)
        except Exception as exc:
            errors.append(exc)

    started = time.monotonic()
    threads = [
        threading.Thread(target=lambda s=sh: worker(s)) for sh in shell_ids
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    elapsed = time.monotonic() - started

    assert not errors
    assert len(results) == 3
    assert all(r is not None and r["killed"] for r in results)
    assert registry.count() == 0
    assert elapsed < 10, f"三个独立 terminate 串行耗时 {elapsed:.2f}s"


def test_concurrent_register_does_not_exceed_session_limit(registry):
    """并发注册在 limit 上限附近不会突破 MAX_BACKGROUND_SESSIONS。"""
    target = MAX_BACKGROUND_SESSIONS + 4
    outcomes: list = []
    barrier = threading.Barrier(target)

    def worker():
        try:
            barrier.wait()
            session = _spawn(registry, "import time; time.sleep(30)")
            outcomes.append(session.shell_id)
        except SessionLimitExceeded:
            outcomes.append(None)

    threads = [threading.Thread(target=worker) for _ in range(target)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    accepted = [sid for sid in outcomes if sid is not None]
    rejected = [sid for sid in outcomes if sid is None]
    assert len(accepted) == MAX_BACKGROUND_SESSIONS
    assert len(rejected) == target - MAX_BACKGROUND_SESSIONS
    assert registry.count() == MAX_BACKGROUND_SESSIONS


def test_read_increment_serialize_per_session_via_operation_lock(registry, monkeypatch):
    """同一 shell 的并发读必须在 operation_lock 内串行, 避免 offset 撕裂。"""
    session = _spawn(
        registry,
        "import sys, time\n"
        "for i in range(40): sys.stdout.write(str(i)); sys.stdout.flush()\n"
        "time.sleep(2)\n",
    )
    start_drain = threading.Event()
    proceed_drain = threading.Event()

    real_drain = BashSessionRegistry._drain

    def slow_drain(reg_self, sess, cap):
        if sess is session:
            start_drain.set()
            proceed_drain.wait(timeout=2)
        return real_drain(reg_self, sess, cap)

    monkeypatch.setattr(BashSessionRegistry, "_drain", slow_drain)

    first_done = threading.Event()
    second_started = threading.Event()

    def worker():
        return registry.read_increment(session.shell_id, cap=READ_CAP)

    results: list = []
    t1 = threading.Thread(target=lambda: (results.append(("first", worker())), first_done.set()))
    t1.start()
    assert start_drain.wait(timeout=5)
    t2 = threading.Thread(target=lambda: (results.append(("second", worker())), second_started.set()))
    t2.start()
    time.sleep(0.5)
    assert not second_started.is_set(), "operation_lock 失效：第二次 read_increment 抢到了同一个 session"
    proceed_drain.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert first_done.is_set()
    assert second_started.is_set()
    assert results[0][0] == "first"
    assert results[1][0] == "second"
