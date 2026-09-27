"""会话归属的远程命令任务（对齐 LocalBridge ``jobs.cjs``）。

- 每个任务属于创建它的 MCP 会话（owner），其他会话不可读取 / 取消；
- 全局最多 4 个运行中任务；单任务最长 120 秒，超时终止整个进程树；
- 输出合并 stdout+stderr，只保留最后 64K 字符；
- Windows 用 ``powershell -EncodedCommand``（UTF-16LE base64）并强制 UTF-8
  输出，避免中文乱码与引号转义问题；其他平台用 ``/bin/sh -c``。
**命令不是沙箱**：拥有当前用户权限，可访问工作区外文件。
"""

from __future__ import annotations

import base64
import codecs
import contextlib
import os
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.tools.subprocess_util import kill_process_tree, spawn_verified

MAX_RUNNING = 4
MAX_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 65536
_FINISHED_RETENTION_SECONDS = 30 * 60

_PS_PRELUDE = (
    "[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false);"
    "$OutputEncoding=[Console]::OutputEncoding;$ErrorActionPreference='Stop';\n"
)


class JobError(RuntimeError):
    """``str(exc)`` 为可直接返回给远程 Agent 的错误码 + 说明。"""


def build_argv(command: str) -> List[str]:
    if os.name == "nt":
        encoded = base64.b64encode((_PS_PRELUDE + command).encode("utf-16-le")).decode("ascii")
        return ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    return ["/bin/sh", "-c", command]


class _Job:
    def __init__(self, job_id: str, owner: str, workspace_id: str, verified: Any) -> None:
        self.id = job_id
        self.owner = owner
        self.workspace_id = workspace_id
        self.verified = verified
        self.output = ""
        self.truncated = False
        self.done = False
        self.exit_code: Optional[int] = None
        self.timed_out = False
        self.cancelled = False
        self.created = time.time()
        self.finished: Optional[float] = None
        self.lock = threading.Lock()

    def append(self, text: str) -> None:
        if not text:
            return
        with self.lock:
            self.output += text
            if len(self.output) > MAX_OUTPUT_CHARS:
                self.output = self.output[-MAX_OUTPUT_CHARS:]
                self.truncated = True

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            status = "running"
            if self.done:
                status = "timed_out" if self.timed_out else "cancelled" if self.cancelled else "completed"
            return {
                "jobId": self.id,
                "status": status,
                "exitCode": self.exit_code,
                "output": self.output,
                "truncated": self.truncated,
            }


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, _Job] = {}
        self._lock = threading.Lock()

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if not j.done)

    def run(self, owner: str, workspace_id: str, cwd: str, command: str,
            timeout_seconds: int = 30, wait_seconds: float = 10.0) -> Dict[str, Any]:
        """启动命令；最多同步等待 ``wait_seconds`` 秒，未结束则返回 running + jobId。"""
        timeout_seconds = max(1, min(int(timeout_seconds), MAX_TIMEOUT_SECONDS))
        with self._lock:
            self._prune_locked()
            if sum(1 for j in self._jobs.values() if not j.done) >= MAX_RUNNING:
                raise JobError(f"BUSY: at most {MAX_RUNNING} running commands")
            try:
                verified = spawn_verified(
                    build_argv(command), cwd=cwd, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    extra_env={"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                )
            except OSError as exc:
                raise JobError(f"SPAWN_FAILED: {exc}") from exc
            job = _Job(str(uuid.uuid4()), owner, workspace_id, verified)
            self._jobs[job.id] = job
        threading.Thread(target=self._pump, args=(job,), daemon=True).start()
        timer = threading.Timer(timeout_seconds, self._timeout, args=(job,))
        timer.daemon = True
        timer.start()
        deadline = time.time() + max(0.0, min(wait_seconds, float(timeout_seconds)))
        while time.time() < deadline and not job.done:
            time.sleep(0.05)
        return job.snapshot()

    def _pump(self, job: _Job) -> None:
        process = job.verified.process
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        stream = process.stdout
        try:
            while True:
                chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
                if not chunk:
                    break
                job.append(decoder.decode(chunk))
            job.append(decoder.decode(b"", final=True))
        except (OSError, ValueError):
            pass
        code = process.wait()
        with job.lock:
            job.exit_code = code
            job.done = True
            job.finished = time.time()

    def _kill(self, job: _Job) -> None:
        if job.done:
            return
        try:
            kill_process_tree(job.verified.process, reap=False,
                              process_group_id=job.verified.process_group_id)
        except Exception:  # noqa: BLE001 — 尽力终止
            with contextlib.suppress(OSError):
                job.verified.process.kill()

    def _timeout(self, job: _Job) -> None:
        if not job.done:
            job.timed_out = True
            self._kill(job)

    def _owned(self, job_id: str, owner: str) -> _Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.owner != owner:
            raise JobError("JOB_NOT_FOUND: unknown jobId for this session")
        return job

    def output(self, job_id: str, owner: str) -> Dict[str, Any]:
        return self._owned(job_id, owner).snapshot()

    def cancel(self, job_id: str, owner: str) -> Dict[str, Any]:
        job = self._owned(job_id, owner)
        if not job.done:
            job.cancelled = True
            self._kill(job)
        return job.snapshot()

    def stop_where(self, *, owner: Optional[str] = None, workspace_id: Optional[str] = None) -> int:
        """终止匹配的运行中任务（会话关闭 / 权限撤销 / 急停）；返回终止数。"""
        with self._lock:
            targets = [
                j for j in self._jobs.values()
                if not j.done
                and (owner is None or j.owner == owner)
                and (workspace_id is None or j.workspace_id == workspace_id)
            ]
        for job in targets:
            job.cancelled = True
            self._kill(job)
        return len(targets)

    def _prune_locked(self) -> None:
        cutoff = time.time() - _FINISHED_RETENTION_SECONDS
        for job_id in [k for k, j in self._jobs.items() if j.done and (j.finished or 0) < cutoff]:
            del self._jobs[job_id]


__all__ = ["MAX_RUNNING", "JobError", "JobManager", "build_argv"]
