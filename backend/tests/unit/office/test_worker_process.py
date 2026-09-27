"""Real-process lifecycle tests plus Windows job API failure contracts."""
from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

from backend.office import excel_eval, worker_job, worker_process


@pytest.fixture()
def launched(monkeypatch):
    processes = []
    original = worker_process.subprocess.Popen

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(worker_process.subprocess, "Popen", capture)
    yield processes
    # Assert actual OS handles have signalled/reaped, not just a returned None.
    for process in processes:
        assert process.poll() is not None
        process.wait(timeout=2)


def _run(tmp_path, body, *, timeout=3, cancel_event=None):
    output = tmp_path / "result.json"
    script = (
        "import sys, time, os; from pathlib import Path; "
        "assert sys.stdin.buffer.readline(4) == b'GO\\n'; "
        f"output=Path({str(output)!r}); " + body
    )
    return worker_process.run_json_worker(
        [sys.executable, "-I", "-c", script], output,
        timeout=timeout, cancel_event=cancel_event,
    )


def test_normal_output_and_no_unbounded_stdio(tmp_path, launched):
    result = _run(tmp_path, "os.write(1, b'x'*1000000); output.write_text('{\"ok\":true}')")
    assert result == {"ok": True}
    assert len(launched) == 1


def test_timeout_kills_and_reaps_real_worker(tmp_path, launched):
    started = time.monotonic()
    assert _run(tmp_path, "time.sleep(60)", timeout=0.3) is None
    assert time.monotonic() - started < 3
    assert len(launched) == 1
    # KILL_ON_JOB_CLOSE may report exit code 0 on Windows; OS completion is decisive.
    assert launched[0].returncode is not None


def test_cancel_kills_started_worker(tmp_path, launched):
    cancel = threading.Event()
    ready = tmp_path / "ready"

    def cancel_when_started():
        deadline = time.monotonic() + 4
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        cancel.set()

    thread = threading.Thread(target=cancel_when_started)
    thread.start()
    try:
        assert _run(tmp_path, f"Path({str(ready)!r}).touch(); time.sleep(60)", timeout=6, cancel_event=cancel) is None
    finally:
        cancel.set()
        thread.join(timeout=5)
    assert ready.exists()
    # KILL_ON_JOB_CLOSE may report exit code 0 on Windows; OS completion is decisive.
    assert launched[0].returncode is not None


def test_pre_cancel_and_busy_do_not_spawn(tmp_path, launched):
    cancel = threading.Event()
    cancel.set()
    assert _run(tmp_path, "raise AssertionError", cancel_event=cancel) is None
    assert worker_process._SLOT.acquire(blocking=False)
    try:
        assert _run(tmp_path, "raise AssertionError") is None
    finally:
        worker_process._SLOT.release()
    assert launched == []


@pytest.mark.parametrize("body", [
    "sys.exit(3)",
    "output.write_text('not json')",
    "output.write_bytes(b'x' * (2*1024*1024+1)); time.sleep(60)",
    "pass",  # successful exit without a result is not success
])
def test_failures_are_bounded_and_reaped(tmp_path, launched, body):
    assert _run(tmp_path, body) is None
    assert len(launched) == 1
    # A completed failure must release capacity for subsequent calls.
    assert worker_process._SLOT.acquire(blocking=False)
    worker_process._SLOT.release()


def test_launch_failure_releases_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_process.subprocess, "Popen", MagicMock(side_effect=OSError("launch")))
    assert _run(tmp_path, "pass") is None
    assert worker_process._SLOT.acquire(blocking=False)
    worker_process._SLOT.release()


@pytest.mark.parametrize("payload", [
    None, [], {"version": 2, "values": {}}, {"version": 1, "values": []},
    {"version": 1, "values": {"Sheet": {"A1": [1]}}},
    {"version": 1, "values": {"Sheet": {"A1": float("nan")}}},
    {"version": 1, "values": {"Sheet": {"A0": 1}}},
])
def test_untrusted_results_are_rejected(payload):
    assert excel_eval._validate_result(payload) is None


def test_formula_result_cap_and_types():
    values = {"Sheet": {f"A{i}": 1 for i in range(1, 502)}}
    assert excel_eval._validate_result({"version": 1, "values": values}) is None
    values = {"Sheet": {"A1": 30, "A2": True, "A3": "#VALUE!", "A4": 0.5}}
    assert excel_eval._validate_result(json.loads(json.dumps({"version": 1, "values": values}))) == values


def test_input_size_limit_prevents_launch(tmp_path, monkeypatch):
    path = tmp_path / "oversize.xlsx"
    path.write_bytes(b"123")
    monkeypatch.setattr(excel_eval, "MAX_INPUT_BYTES", 2)
    runner = MagicMock()
    monkeypatch.setattr(excel_eval, "run_json_worker", runner)
    assert excel_eval.evaluate_workbook(path) is None
    runner.assert_not_called()


@pytest.mark.parametrize("failed_api", ["CreateJobObjectW", "SetInformationJobObject", "AssignProcessToJobObject"])
def test_windows_job_failure_closes_handle(monkeypatch, failed_api):
    api = MagicMock()
    api.CreateJobObjectW.return_value = 123
    getattr(api, failed_api).return_value = 0
    monkeypatch.setattr(worker_job, "_kernel32", lambda: api)
    with pytest.raises(OSError, match=failed_api):
        worker_job.WorkerJob(456, worker_process.MEMORY_BYTES)
    if failed_api == "CreateJobObjectW":
        api.CloseHandle.assert_not_called()
    else:
        api.CloseHandle.assert_called_once_with(123)


def test_windows_job_total_memory_bounded_processes_and_kill_on_close(monkeypatch):
    api = MagicMock()
    api.CreateJobObjectW.return_value = 123
    captured = []

    def set_limits(handle, info_class, pointer, size):
        value = ctypes.cast(pointer, ctypes.POINTER(worker_job._ExtendedLimits)).contents
        captured.append((handle, info_class, size, value.basic.flags, value.basic.active_processes, value.process_memory, value.job_memory))
        return 1

    api.SetInformationJobObject.side_effect = set_limits
    monkeypatch.setattr(worker_job, "_kernel32", lambda: api)
    job = worker_job.WorkerJob(456, worker_process.MEMORY_BYTES)
    assert captured == [(123, 9, ctypes.sizeof(worker_job._ExtendedLimits), 0x2308, 2, 512 * 1024 * 1024, 512 * 1024 * 1024)]
    api.AssignProcessToJobObject.assert_called_once_with(123, 456)
    job.close()
    job.close()
    api.CloseHandle.assert_called_once_with(123)


def test_job_denial_never_sends_start_and_reaps(tmp_path, monkeypatch, launched):
    ready = tmp_path / "must-not-run"
    monkeypatch.setattr(worker_process, "_attach_job", MagicMock(side_effect=OSError("job denied")))
    assert _run(tmp_path, f"Path({str(ready)!r}).touch(); time.sleep(60)") is None
    assert not ready.exists()
    assert len(launched) == 1
    # KILL_ON_JOB_CLOSE may report exit code 0 on Windows; OS completion is decisive.
    assert launched[0].returncode is not None


def test_concurrent_requests_launch_only_one_worker(tmp_path, launched):
    first = tmp_path / "first"
    first.mkdir()
    ready, release = tmp_path / "ready", tmp_path / "release"
    results = []
    body = (
        f"Path({str(ready)!r}).touch()\n"
        f"while not Path({str(release)!r}).exists(): time.sleep(0.02)\n"
        "output.write_text('{\"ok\":true}')"
    )
    thread = threading.Thread(target=lambda: results.append(_run(first, body, timeout=8)))
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        assert _run(tmp_path, "raise AssertionError") is None
        assert len(launched) == 1
    finally:
        release.touch()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert results == [{"ok": True}]


def test_real_worker_memory_limit(tmp_path, launched):
    from pathlib import Path

    root = str(Path(__file__).resolve().parents[4])
    body = (
        f"sys.path.insert(0, {root!r}); "
        "from backend.office.worker_process import apply_posix_limits; "
        "apply_posix_limits(2)\n"
        "try: bytearray(1024*1024*1024)\n"
        "except MemoryError: output.write_text('{\"limited\":true}')\n"
        "else: output.write_text('{\"limited\":false}')\n"
    )
    assert _run(tmp_path, body) == {"limited": True}


@pytest.mark.parametrize("resume_count", [1, 0xFFFFFFFF, 2])
def test_resume_owned_suspended_thread_closes_handles(monkeypatch, resume_count):
    api = MagicMock()
    api.CreateJobObjectW.return_value = 123
    api.CreateToolhelp32Snapshot.return_value = 7
    api.OpenThread.return_value = 8
    api.ResumeThread.return_value = resume_count

    def first(snapshot, pointer):
        entry = ctypes.cast(pointer, ctypes.POINTER(worker_job._ThreadEntry)).contents
        entry.owner_pid = 456
        entry.thread_id = 789
        return 1

    api.Thread32First.side_effect = first
    monkeypatch.setattr(worker_job, "_kernel32", lambda: api)
    job = worker_job.WorkerJob(100, worker_process.MEMORY_BYTES)
    try:
        if resume_count == 1:
            job.resume(456)
        else:
            with pytest.raises(OSError, match="ResumeThread"):
                job.resume(456)
        api.OpenThread.assert_called_once_with(0x2, False, 789)
        assert [c.args[0] for c in api.CloseHandle.call_args_list] == [8, 7]
    finally:
        job.close()


def test_resume_missing_thread_is_fail_closed(monkeypatch):
    api = MagicMock()
    api.CreateJobObjectW.return_value = 123
    api.CreateToolhelp32Snapshot.return_value = 7
    api.Thread32First.return_value = 0
    monkeypatch.setattr(worker_job, "_kernel32", lambda: api)
    job = worker_job.WorkerJob(100, worker_process.MEMORY_BYTES)
    try:
        with pytest.raises(OSError, match="not found"):
            job.resume(456)
        api.CloseHandle.assert_called_once_with(7)
    finally:
        job.close()
