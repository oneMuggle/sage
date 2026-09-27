"""Bounded, owned subprocess supervision, not a security/egress sandbox.

Only stdlib is loaded in the parent. Formula workers never inherit a shell,
stdout/stderr pipes, or an unbounded queue. A permit is retained if the OS
cannot reap a killed child within the cleanup grace period (fail closed).
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

from .worker_job import WorkerJob

logger = logging.getLogger(__name__)
MAX_INPUT_BYTES = 50 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MEMORY_BYTES = 512 * 1024 * 1024
_CLEANUP_SECONDS = 2.0
_SLOT = threading.BoundedSemaphore(1)


def apply_posix_limits(cpu_seconds: int) -> None:
    """Called by the worker, before document/engine imports (no preexec_fn)."""
    if os.name == "nt":
        return
    import resource

    for kind, limit in [
        (resource.RLIMIT_AS, MEMORY_BYTES),
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_FSIZE, MAX_OUTPUT_BYTES),
    ]:
        _, hard = resource.getrlimit(kind)
        ceiling = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
        resource.setrlimit(kind, (ceiling, ceiling))


def _attach_job(process: Any) -> Optional[WorkerJob]:
    if os.name == "nt":
        job = WorkerJob(int(process._handle), MEMORY_BYTES)
        try:
            job.resume(process.pid)
        except BaseException:
            job.close()
            raise
        return job
    return None


def _stop(process: Any, job: Optional[WorkerJob]) -> bool:
    if job is not None:
        job.close()  # kill-on-close covers the job even after normal completion
    if os.name != "nt":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    elif process.poll() is None:
        process.kill()  # also covers job creation/assignment failures
    try:
        process.wait(timeout=_CLEANUP_SECONDS)
        return True
    except subprocess.TimeoutExpired:
        logger.error("Office worker could not be reaped; evaluation disabled in this process")
        return False


def run_json_worker(  # noqa: PLR0911 — fail-closed lifecycle guards
    command: List[str],
    output: Path,
    *,
    timeout: float,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[Any]:
    """Run a handshake-aware worker, terminate/reap it, read a bounded JSON file.

    ``command`` is constructed by application code, never by document content.
    stdout/stderr are discarded; diagnostics must not exhaust parent memory.
    """
    if timeout <= 0 or (cancel_event is not None and cancel_event.is_set()):
        return None
    if not _SLOT.acquire(blocking=False):
        logger.info("Office formula worker busy; using cached values")
        return None
    process = None
    job = None
    reaped = True
    deadline = time.monotonic() + timeout
    try:
        env = os.environ.copy()
        for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            env[name] = "1"
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            close_fds=True,
            start_new_session=os.name != "nt",
            creationflags=(subprocess.CREATE_NO_WINDOW | 0x4) if os.name == "nt" else 0,  # CREATE_SUSPENDED
        )
        job = _attach_job(process)
        # Document loading/importing cannot begin until containment is attached.
        process.stdin.write(b"GO\n")
        process.stdin.close()
        while True:
            if (cancel_event is not None and cancel_event.is_set()) or time.monotonic() >= deadline:
                logger.warning("Office formula worker cancelled or timed out")
                return None
            if output.exists() and output.stat().st_size > MAX_OUTPUT_BYTES:
                logger.warning("Office formula worker output exceeds limit")
                return None
            code = process.poll()
            if code is not None:
                if code != 0:
                    logger.warning("Office formula worker failed (exit %s)", code)
                    return None
                break
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        # Never trust only stat(): enforce a read cap even if the file grows.
        with output.open("rb") as stream:
            payload = stream.read(MAX_OUTPUT_BYTES + 1)
        if len(payload) > MAX_OUTPUT_BYTES:
            return None
        return json.loads(payload)
    except Exception:  # noqa: BLE001 — optional calculation must degrade safely
        logger.warning("Office formula worker unavailable", exc_info=True)
        return None
    finally:
        try:
            if process is not None:
                reaped = False
                with contextlib.suppress(OSError):
                    if process.stdin is not None and not process.stdin.closed:
                        process.stdin.close()
                try:
                    reaped = _stop(process, job)
                except OSError:
                    logger.exception("Office worker cleanup failed; evaluation disabled")
        finally:
            if reaped:
                _SLOT.release()
