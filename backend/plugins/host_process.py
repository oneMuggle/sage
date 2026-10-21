"""Process supervision primitives for the plugin host (R83).

This module owns one worker process: bounded stdio JSON-RPC, reader threads,
platform process cleanup, and runtime snapshots.  The public manager in
``backend.plugins.host`` composes these sessions with lifecycle records and
the capability registry.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.domain.plugin import FiberState
from backend.plugins.manifest import PluginCapability

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
_ENV_WHITELIST = (
    "APPDATA",
    "COMSPEC",
    "HOME",
    "LANG",
    "LC_ALL",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "SystemRoot",
    "TEMP",
    "TERM",
    "TMP",
    "USERPROFILE",
    "WINDIR",
)


class PluginHostError(RuntimeError):
    """Structured plugin-host failure with an HTTP-friendly status code."""

    def __init__(self, code: str, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PluginHostLimits:
    """Bounded-supervision limits for one plugin worker."""

    startup_timeout_seconds: float = 10.0
    request_timeout_seconds: float = 30.0
    shutdown_timeout_seconds: float = 3.0
    max_message_bytes: int = 1024 * 1024
    memory_bytes: int = 512 * 1024 * 1024
    cpu_seconds: int = 300
    max_stderr_chars: int = 8000

    def __post_init__(self) -> None:
        if self.startup_timeout_seconds <= 0:
            raise ValueError("startup_timeout_seconds must be positive")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.shutdown_timeout_seconds <= 0:
            raise ValueError("shutdown_timeout_seconds must be positive")
        if self.max_message_bytes < 1024:
            raise ValueError("max_message_bytes must be at least 1024")
        if self.memory_bytes <= 0:
            raise ValueError("memory_bytes must be positive")
        if self.cpu_seconds <= 0:
            raise ValueError("cpu_seconds must be positive")
        if self.max_stderr_chars <= 0:
            raise ValueError("max_stderr_chars must be positive")

    def to_wire(self) -> Dict[str, int]:
        return {
            "max_message_bytes": self.max_message_bytes,
            "memory_bytes": self.memory_bytes,
            "cpu_seconds": self.cpu_seconds,
        }


@dataclass
class PluginRuntimeStatus:
    """In-memory runtime status; intentionally not persisted across restarts."""

    plugin_name: str
    state: FiberState = FiberState.PENDING
    pid: Optional[int] = None
    started_at: Optional[float] = None
    stopped_at: Optional[float] = None
    exit_code: Optional[int] = None
    restart_count: int = 0
    capabilities: List[str] = field(default_factory=list)
    last_error: Optional[str] = None
    stderr_tail: str = ""
    limits: PluginHostLimits = field(default_factory=PluginHostLimits)
    memory_limit_enforced: bool = False
    cpu_limit_enforced: bool = False

    @property
    def running(self) -> bool:
        return self.state == FiberState.ACTIVE and self.pid is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_name": self.plugin_name,
            "state": self.state.value,
            "running": self.running,
            "pid": self.pid,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "exit_code": self.exit_code,
            "restart_count": self.restart_count,
            "capabilities": list(self.capabilities),
            "last_error": self.last_error,
            "stderr_tail": self.stderr_tail,
            "limits": {
                "startup_timeout_seconds": self.limits.startup_timeout_seconds,
                "request_timeout_seconds": self.limits.request_timeout_seconds,
                "shutdown_timeout_seconds": self.limits.shutdown_timeout_seconds,
                "max_message_bytes": self.limits.max_message_bytes,
                "memory_bytes": self.limits.memory_bytes,
                "cpu_seconds": self.limits.cpu_seconds,
                "memory_limit_enforced": self.memory_limit_enforced,
                "cpu_limit_enforced": self.cpu_limit_enforced,
            },
        }


def _truncate(value: Any, limit: int = 1000) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "...[truncated]"




def _build_worker_env(plugin_name: str, plugin_root: Path) -> Dict[str, str]:
    by_upper: Dict[str, Tuple[str, str]] = {}
    for key, value in os.environ.items():
        by_upper.setdefault(key.upper(), (key, value))

    env: Dict[str, str] = {}
    for key in _ENV_WHITELIST:
        found = by_upper.get(key.upper())
        if found is not None:
            env[found[0]] = found[1]

    env.update(
        {
            "PYTHONPATH": str(plugin_root),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SAGE_PLUGIN_NAME": plugin_name,
            "SAGE_PLUGIN_ROOT": str(plugin_root),
        }
    )
    return env


class _PluginProcess:
    """One supervised worker process and its single-flight JSON-RPC client."""

    def __init__(
        self,
        *,
        plugin_name: str,
        plugin_root: Path,
        capabilities: Sequence[PluginCapability],
        config: Dict[str, Any],
        limits: PluginHostLimits,
        restart_count: int,
        python_executable: str,
        worker_script: Path,
    ) -> None:
        self.plugin_name = plugin_name
        self.plugin_root = plugin_root
        self.capabilities = list(capabilities)
        self.capability_names = [capability.name for capability in capabilities]
        self.config = dict(config)
        self.limits = limits
        self.restart_count = restart_count
        self.python_executable = python_executable
        self.worker_script = worker_script

        self.state = FiberState.PENDING
        self.pid: Optional[int] = None
        self.started_at: Optional[float] = None
        self.stopped_at: Optional[float] = None
        self.exit_code: Optional[int] = None
        self.last_error: Optional[str] = None
        self.memory_limit_enforced = False
        self.cpu_limit_enforced = False

        self._process: Optional[subprocess.Popen] = None
        self._job: Optional[Any] = None
        self._io_lock = threading.Lock()
        self._responses = queue.Queue()  # items: Tuple[str, Optional[bytes]]
        self._stderr_lock = threading.Lock()
        self._stderr_parts: List[str] = []
        self._next_id = 1
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return (
            self.state == FiberState.ACTIVE
            and self._process is not None
            and self._process.poll() is None
        )

    def start(self) -> PluginRuntimeStatus:
        if self.running:
            return self.snapshot()
        self.state = FiberState.LOADING
        self.started_at = time.time()
        self.stopped_at = None
        self.exit_code = None
        self.last_error = None
        try:
            self._spawn()
            self._start_readers()
            result = self.request(
                "initialize",
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "plugin_name": self.plugin_name,
                    "plugin_root": str(self.plugin_root),
                    "config": self.config,
                    "capabilities": [
                        {"name": cap.name, "entry_point": cap.entry_point or ""}
                        for cap in self.capabilities
                    ],
                    "limits": self.limits.to_wire(),
                },
                timeout=self.limits.startup_timeout_seconds,
            )
            if not isinstance(result, dict):
                raise PluginHostError(
                    "PLUGIN_PROTOCOL_ERROR",
                    "plugin worker initialize returned a non-object result",
                    status_code=502,
                )
            loaded = result.get("capabilities")
            if not isinstance(loaded, list) or sorted(str(name) for name in loaded) != sorted(
                self.capability_names
            ):
                raise PluginHostError(
                    "PLUGIN_PROTOCOL_ERROR",
                    "plugin worker loaded an unexpected capability set",
                    status_code=502,
                )
            limits_applied = result.get("limits_applied") or {}
            if isinstance(limits_applied, dict):
                self.memory_limit_enforced = self.memory_limit_enforced or bool(
                    limits_applied.get("memory")
                )
                self.cpu_limit_enforced = bool(limits_applied.get("cpu"))
        except PluginHostError as exc:
            self._mark_failed(exc, terminate=True)
            raise
        except Exception as exc:  # noqa: BLE001 - startup boundary
            error = PluginHostError(
                "PLUGIN_WORKER_START_FAILED",
                f"could not start plugin worker: {type(exc).__name__}: {_truncate(exc)}",
                status_code=502,
            )
            self._mark_failed(error, terminate=True)
            raise error from exc

        self.state = FiberState.ACTIVE
        self.last_error = None
        return self.snapshot()

    def invoke(self, capability_name: str, arguments: Dict[str, Any]) -> Any:
        self.reconcile()
        if capability_name not in self.capability_names:
            raise PluginHostError(
                "CAPABILITY_NOT_FOUND",
                f"plugin capability is not loaded: {capability_name}",
                status_code=422,
            )
        if not self.running:
            raise PluginHostError(
                "PLUGIN_NOT_RUNNING",
                f"plugin runtime is not running: {self.plugin_name}",
                status_code=409,
            )
        result = self.request(
            "tools/call",
            {"name": capability_name, "arguments": dict(arguments)},
            timeout=self.limits.request_timeout_seconds,
        )
        self.last_error = None
        return result

    def request(self, method: str, params: Dict[str, Any], *, timeout: float) -> Any:
        with self._io_lock:
            return self._request_locked(method, params, timeout=timeout)

    def stop(self) -> PluginRuntimeStatus:
        if self._process is None:
            self.state = FiberState.DISPOSED
            self.pid = None
            return self.snapshot()

        self._stopping = True
        self.state = FiberState.UNLOADING
        acquired = self._io_lock.acquire(timeout=0.2)
        if acquired:
            try:
                if self._process.poll() is None:
                    with contextlib.suppress(PluginHostError):
                        self._request_locked(
                            "shutdown",
                            {},
                            timeout=min(1.0, self.limits.shutdown_timeout_seconds),
                        )
            finally:
                self._io_lock.release()

        self._terminate_process(self.limits.shutdown_timeout_seconds)
        self._join_readers()
        self.state = FiberState.DISPOSED
        self.stopped_at = time.time()
        self.pid = None
        self._stopping = False
        return self.snapshot()

    def reconcile(self) -> bool:
        """Return True only when this call transitions a dead worker to failed."""

        process = self._process
        if process is None or self._stopping:
            return False
        exit_code = process.poll()
        if exit_code is None or self.state not in (FiberState.LOADING, FiberState.ACTIVE):
            return False
        self.exit_code = exit_code
        self.state = FiberState.FAILED
        self.stopped_at = time.time()
        self.last_error = f"plugin worker exited with code {exit_code}"
        self._close_job()
        return True

    def snapshot(self) -> PluginRuntimeStatus:
        self.reconcile()
        return PluginRuntimeStatus(
            plugin_name=self.plugin_name,
            state=self.state,
            pid=self.pid if self._process is not None else None,
            started_at=self.started_at,
            stopped_at=self.stopped_at,
            exit_code=self.exit_code,
            restart_count=self.restart_count,
            capabilities=list(self.capability_names),
            last_error=self.last_error,
            stderr_tail=self._stderr_tail(),
            limits=self.limits,
            memory_limit_enforced=self.memory_limit_enforced,
            cpu_limit_enforced=self.cpu_limit_enforced,
        )

    def _request_locked(self, method: str, params: Dict[str, Any], *, timeout: float) -> Any:
        process = self._process
        if process is None or process.poll() is not None:
            if process is not None:
                self.exit_code = process.poll()
            error = PluginHostError(
                "PLUGIN_WORKER_EXITED",
                f"plugin worker is not running (exit_code={self.exit_code})",
                status_code=502,
            )
            self._mark_failed(error, terminate=False)
            raise error
        if process.stdin is None:
            error = PluginHostError(
                "PLUGIN_PROTOCOL_ERROR",
                "plugin worker stdin is unavailable",
                status_code=502,
            )
            self._mark_failed(error, terminate=True)
            raise error

        request_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        try:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise PluginHostError(
                "INVALID_ARGUMENTS",
                f"plugin request is not JSON serializable: {_truncate(exc)}",
                status_code=422,
            ) from exc
        if len(raw) > self.limits.max_message_bytes:
            raise PluginHostError(
                "PLUGIN_REQUEST_TOO_LARGE",
                f"plugin request exceeds {self.limits.max_message_bytes} bytes",
                status_code=422,
            )

        try:
            process.stdin.write(raw + b"\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            error = PluginHostError(
                "PLUGIN_WORKER_EXITED",
                f"could not write to plugin worker: {_truncate(exc)}",
                status_code=502,
            )
            self._mark_failed(error, terminate=True)
            raise error from exc

        try:
            kind, line = self._responses.get(timeout=max(0.0, timeout))
        except queue.Empty:
            error = PluginHostError(
                "PLUGIN_REQUEST_TIMEOUT",
                f"plugin request timed out after {timeout:.3g}s: {method}",
                status_code=504,
            )
            self._mark_failed(error, terminate=True)
            raise error from None

        if kind == "oversized":
            error = PluginHostError(
                "PLUGIN_PROTOCOL_ERROR",
                "plugin worker sent an oversized protocol line",
                status_code=502,
            )
            self._mark_failed(error, terminate=True)
            raise error
        if kind == "eof" or line is None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=0.2)
            self.exit_code = process.poll()
            error = PluginHostError(
                "PLUGIN_WORKER_EXITED",
                f"plugin worker exited while handling {method} (exit_code={self.exit_code})",
                status_code=502,
            )
            self._mark_failed(error, terminate=False)
            raise error

        try:
            response = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            error = PluginHostError(
                "PLUGIN_PROTOCOL_ERROR",
                "plugin worker sent invalid JSON",
                status_code=502,
            )
            self._mark_failed(error, terminate=True)
            raise error from exc

        if not isinstance(response, dict) or response.get("id") != request_id:
            error = PluginHostError(
                "PLUGIN_PROTOCOL_ERROR",
                "plugin worker response id does not match the request",
                status_code=502,
            )
            self._mark_failed(error, terminate=True)
            raise error

        if "error" in response:
            rpc_error = response.get("error") if isinstance(response.get("error"), dict) else {}
            data = rpc_error.get("data") if isinstance(rpc_error.get("data"), dict) else {}
            code = str(data.get("code") or "PLUGIN_WORKER_ERROR")
            message = _truncate(rpc_error.get("message") or code)
            status_code = 422 if code in {
                "CAPABILITY_NOT_FOUND",
                "INVALID_ENTRY_POINT",
                "INVALID_PARAMS",
                "NO_CAPABILITIES",
                "PLUGIN_LOAD_FAILED",
                "PLUGIN_ROOT_NOT_FOUND",
            } else 502
            error = PluginHostError(code, message, status_code=status_code)
            self.last_error = message
            raise error

        if "result" not in response:
            error = PluginHostError(
                "PLUGIN_PROTOCOL_ERROR",
                "plugin worker response has neither result nor error",
                status_code=502,
            )
            self._mark_failed(error, terminate=True)
            raise error
        return response["result"]

    def _spawn(self) -> None:
        if not self.worker_script.is_file():
            raise PluginHostError(
                "PLUGIN_WORKER_START_FAILED",
                f"plugin worker script not found: {self.worker_script}",
                status_code=502,
            )
        command = [self.python_executable, "-u", str(self.worker_script)]
        env = _build_worker_env(self.plugin_name, self.plugin_root)
        common = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": str(self.plugin_root),
            "env": env,
            "close_fds": True,
            "bufsize": 0,
        }

        if os.name == "nt":
            process: Optional[subprocess.Popen] = None
            job: Optional[Any] = None
            try:
                from backend.office.worker_job import WorkerJob

                create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                create_suspended = getattr(subprocess, "CREATE_SUSPENDED", 0x4)
                process = subprocess.Popen(
                    command,
                    creationflags=create_no_window | create_suspended,
                    **common,
                )
                job = WorkerJob(int(process._handle), self.limits.memory_bytes)  # noqa: SLF001
                job.resume(process.pid)
                self._job = job
                self.memory_limit_enforced = True
            except Exception as exc:  # noqa: BLE001 - fall back without an OS memory cap
                logger.warning(
                    "Plugin worker Job Object unavailable for %s; continuing without a "
                    "Windows memory cap: %s",
                    self.plugin_name,
                    exc,
                )
                if job is not None:
                    with contextlib.suppress(Exception):
                        job.close()
                if process is not None:
                    with contextlib.suppress(Exception):
                        process.kill()
                        process.wait(timeout=2)
                flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
                process = subprocess.Popen(command, creationflags=flags, **common)
                self._job = None
                self.memory_limit_enforced = False
            self._process = process
        else:
            self._process = subprocess.Popen(command, start_new_session=True, **common)

        if self._process is None:
            raise PluginHostError(
                "PLUGIN_WORKER_START_FAILED",
                "plugin worker process was not created",
                status_code=502,
            )
        self.pid = self._process.pid

    def _start_readers(self) -> None:
        if self._process is None:
            return
        self._stdout_thread = threading.Thread(
            target=self._stdout_reader,
            name=f"plugin-stdout-{self.plugin_name}",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_reader,
            name=f"plugin-stderr-{self.plugin_name}",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _stdout_reader(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._responses.put(("eof", None))
            return
        buffered = bytearray()
        try:
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                buffered.extend(chunk)
                while True:
                    newline = buffered.find(b"\n")
                    if newline < 0:
                        break
                    line = bytes(buffered[:newline])
                    del buffered[: newline + 1]
                    if len(line) > self.limits.max_message_bytes:
                        self._responses.put(("oversized", None))
                        return
                    if line.strip():
                        self._responses.put(("line", line))
                if len(buffered) > self.limits.max_message_bytes:
                    self._responses.put(("oversized", None))
                    return
        except (OSError, ValueError):
            pass
        self._responses.put(("eof", None))

    def _stderr_reader(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            while True:
                chunk = process.stderr.read(4096)
                if not chunk:
                    return
                text = chunk.decode("utf-8", errors="replace")
                with self._stderr_lock:
                    self._stderr_parts.append(text)
                    joined = "".join(self._stderr_parts)
                    if len(joined) > self.limits.max_stderr_chars:
                        joined = joined[-self.limits.max_stderr_chars :]
                        self._stderr_parts = [joined]
        except (OSError, ValueError):
            return

    def _stderr_tail(self) -> str:
        with self._stderr_lock:
            return "".join(self._stderr_parts)[-self.limits.max_stderr_chars :]

    def _mark_failed(self, error: PluginHostError, *, terminate: bool) -> None:
        self.last_error = error.message
        if terminate:
            self._terminate_process(self.limits.shutdown_timeout_seconds)
        elif self._process is not None:
            self.exit_code = self._process.poll()
        self.stopped_at = time.time()
        if not self._stopping:
            self.state = FiberState.FAILED

    def _terminate_process(self, grace_seconds: float) -> None:
        process = self._process
        if process is None:
            self._close_job()
            return

        if process.stdin is not None:
            with contextlib.suppress(OSError):
                process.stdin.close()

        if process.poll() is None:
            try:
                if self._job is not None:
                    self._close_job()
                elif os.name != "nt":
                    with contextlib.suppress(ProcessLookupError, PermissionError):
                        os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except OSError:
                logger.warning("Failed to terminate plugin worker %s", self.plugin_name, exc_info=True)

            try:
                process.wait(timeout=max(0.1, grace_seconds))
            except subprocess.TimeoutExpired:
                try:
                    if os.name != "nt":
                        with contextlib.suppress(ProcessLookupError, PermissionError):
                            os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except OSError:
                    logger.warning("Failed to kill plugin worker %s", self.plugin_name, exc_info=True)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=max(0.1, grace_seconds))

        self.exit_code = process.poll()
        self._close_job()

    def _close_job(self) -> None:
        if self._job is not None:
            with contextlib.suppress(Exception):
                self._job.close()
            self._job = None

    def _join_readers(self) -> None:
        for thread in (self._stdout_thread, self._stderr_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=0.2)



__all__ = [
    "PROTOCOL_VERSION",
    "PluginHostError",
    "PluginHostLimits",
    "PluginRuntimeStatus",
]
