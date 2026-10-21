"""Subprocess 沙箱适配器（v2）。

该 runner 仅提供受限环境、超时和输出边界，不是 OS-level sandbox；脚本仍与宿主进程共享操作系统权限。
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from contextlib import suppress
from typing import Dict, FrozenSet, Optional, Tuple

from backend.skills.skill_md.sandbox import (
    DEFAULT_ENV_ALLOWLIST,
    DEFAULT_ENV_DENYLIST,
    SandboxRequest,
    SandboxResult,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024
_READ_CHUNK_BYTES = 4096
_WINDOWS_TASKKILL = "taskkill.exe"
_WINDOWS_TASKKILL_TIMEOUT_S = 5.0
_MAX_STDIN_BYTES = 1024 * 1024


class SubprocessSandboxAdapter:
    """基于 asyncio subprocess 的沙箱适配器（v2）。"""

    def __init__(
        self,
        *,
        python_executable: str = sys.executable,
        default_timeout_s: float = 30.0,
        max_timeout_s: float = 300.0,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        env_denylist: FrozenSet[str] = DEFAULT_ENV_DENYLIST,
    ) -> None:
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self._python_executable = python_executable
        self._default_timeout_s = default_timeout_s
        self._max_timeout_s = max_timeout_s
        self._max_output_bytes = max_output_bytes
        self._env_denylist = env_denylist

    async def run(self, req: SandboxRequest) -> SandboxResult:
        start_time = time.monotonic()
        if req.stdin_data is not None and len(req.stdin_data) > _MAX_STDIN_BYTES:
            return self._failure(
                start_time,
                f"stdin exceeds limit of {_MAX_STDIN_BYTES} bytes",
            )
        timeout = min(req.timeout_s, self._max_timeout_s)
        if req.timeout_s == 30.0:
            timeout = self._default_timeout_s
        argv = [self._python_executable, str(req.script_path.resolve()), *req.args]
        cwd = (req.cwd if req.cwd is not None else req.script_path.parent).resolve()
        env = self._build_env(req.env)
        kwargs = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "stdin": asyncio.subprocess.PIPE
            if req.stdin_data is not None
            else asyncio.subprocess.DEVNULL,
            "env": env,
            "cwd": cwd,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        else:
            # Windows lacks a portable asyncio API for terminating a process tree.
            # _terminate_process_tree uses the native taskkill.exe fallback below.
            logger.debug("Sandbox subprocess will use taskkill.exe for tree cleanup")

        try:
            process = await asyncio.create_subprocess_exec(*argv, **kwargs)
        except OSError as exc:
            logger.warning("Sandbox subprocess spawn failed: %s", exc)
            return self._failure(start_time, f"spawn failed: {exc}")

        try:
            stdout, stderr, output_exceeded = await asyncio.wait_for(
                self._collect_output(process, req.stdin_data), timeout=timeout
            )
        except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041
            await self._terminate_process_tree(process)
            return self._failure(
                start_time, f"timeout after {timeout:.1f}s", timed_out=True
            )
        except Exception as exc:
            logger.warning("Sandbox subprocess execution failed: %s", exc)
            await self._terminate_process_tree(process)
            return self._failure(start_time, f"execution failed: {exc}")

        if output_exceeded:
            await self._terminate_process_tree(process)
            return SandboxResult(
                success=False,
                exit_code=process.returncode if process.returncode is not None else -1,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                duration_ms=self._duration_ms(start_time),
                error=f"output exceeded limit of {self._max_output_bytes} bytes",
            )

        exit_code = process.returncode if process.returncode is not None else -1
        return SandboxResult(
            success=exit_code == 0,
            exit_code=exit_code,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            duration_ms=self._duration_ms(start_time),
        )

    async def _collect_output(
        self, process: asyncio.subprocess.Process, stdin_data: Optional[bytes]  # noqa: UP045
    ) -> Tuple[bytes, bytes, bool]:
        """并发增量读取；任一流超限即停止等待并由调用方终止进程树。"""
        if not isinstance(process.stdout, asyncio.StreamReader) or not isinstance(
            process.stderr, asyncio.StreamReader
        ):
            stdout, stderr = await process.communicate(input=stdin_data)
            stdout, stderr, exceeded = self._cap_output(stdout or b"", stderr or b"")
            return stdout, stderr, exceeded

        budget = [self._max_output_bytes]
        stdout_task = asyncio.ensure_future(self._read_stream(process.stdout, budget))
        stderr_task = asyncio.ensure_future(self._read_stream(process.stderr, budget))
        stdin_task = (
            asyncio.ensure_future(self._write_stdin(process, stdin_data))
            if stdin_data is not None and process.stdin is not None
            else None
        )
        tasks = {stdout_task, stderr_task}
        if stdin_task is not None:
            tasks.add(stdin_task)
        stdout_result = (b"", b"", False)
        stderr_result = (b"", b"", False)
        try:
            while tasks:
                done, tasks = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    if task is stdin_task:
                        task.result()
                        continue
                    result = task.result()
                    if task is stdout_task:
                        stdout_result = result
                    else:
                        stderr_result = result
                if stdout_result[2] or stderr_result[2]:
                    return stdout_result[0], stderr_result[0], True
            await process.wait()
            return stdout_result[0], stderr_result[0], False
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _write_stdin(self, process, stdin_data: bytes) -> None:
        try:
            process.stdin.write(stdin_data)
            await process.stdin.drain()
        finally:
            process.stdin.close()

    def _cap_output(self, stdout: bytes, stderr: bytes) -> Tuple[bytes, bytes, bool]:
        """Cap both streams against one shared byte budget."""
        combined = stdout + stderr
        exceeded = len(combined) > self._max_output_bytes
        if not exceeded:
            return stdout, stderr, False
        limited = combined[: self._max_output_bytes]
        stdout_len = min(len(stdout), len(limited))
        return limited[:stdout_len], limited[stdout_len:], True

    async def _read_stream(self, stream, budget) -> Tuple[bytes, bytes, bool]:
        chunks = bytearray()
        while True:
            chunk = await stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                return bytes(chunks), b"", False
            remaining = budget[0]
            if remaining > 0:
                accepted = chunk[:remaining]
                chunks.extend(accepted)
                budget[0] -= len(accepted)
            if len(chunk) > remaining:
                return bytes(chunks), b"", True

    async def _terminate_process_tree(self, process: asyncio.subprocess.Process) -> None:
        """Terminate the child and all descendants without invoking a shell."""
        if process.returncode is not None:
            return

        if os.name == "posix" and process.pid is not None:
            with suppress(ProcessLookupError, OSError):
                os.killpg(process.pid, signal.SIGKILL)
            await self._wait_for_process(process)
            return

        if os.name == "nt" and process.pid is not None:
            taskkill_argv = [
                _WINDOWS_TASKKILL,
                "/PID",
                str(process.pid),
                "/T",
                "/F",
            ]
            killer = None
            taskkill_succeeded = False
            try:
                # Use a separate native process with a bounded wait.  In
                # particular, do not use shell=True or interpolate user data.
                killer = await asyncio.create_subprocess_exec(
                    *taskkill_argv,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    stdin=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), _WINDOWS_TASKKILL_TIMEOUT_S)
                if killer.returncode not in (None, 0):
                    raise OSError(
                        f"taskkill exited with code {killer.returncode}"
                    )
                taskkill_succeeded = True
            except (OSError, asyncio.TimeoutError, TimeoutError) as exc:  # noqa: UP041
                logger.warning("taskkill failed for sandbox pid %s: %s", process.pid, exc)
                if killer is not None and killer.returncode is None:
                    with suppress(ProcessLookupError, OSError):
                        killer.kill()
                    await self._wait_for_process(killer)
            finally:
                # taskkill can race with process exit or be unavailable (for
                # example in a restricted test environment), so retain a
                # direct-kill fallback and always reap the asyncio process.
                if not taskkill_succeeded and process.returncode is None:
                    with suppress(ProcessLookupError, OSError):
                        process.kill()
                await self._wait_for_process(process)
            return

        with suppress(ProcessLookupError, OSError):
            process.kill()
        await self._wait_for_process(process)

    @staticmethod
    async def _wait_for_process(process: asyncio.subprocess.Process) -> None:
        with suppress(ProcessLookupError, OSError):
            await process.wait()

    @staticmethod
    def _duration_ms(start_time: float) -> int:
        return int((time.monotonic() - start_time) * 1000)

    def _failure(
        self, start_time: float, error: str, timed_out: bool = False
    ) -> SandboxResult:
        return SandboxResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            duration_ms=self._duration_ms(start_time),
            timed_out=timed_out,
            error=error,
        )

    def _build_env(self, request_env: Dict[str, str]) -> Dict[str, str]:
        """Build a small, non-sensitive environment for the skill process."""
        inherited = {
            key: value
            for key, value in os.environ.items()
            if key in DEFAULT_ENV_ALLOWLIST and key not in self._env_denylist
        }
        # Runtime policy wins: request.env may add only non-sensitive custom
        # variables and cannot replace inherited values such as PATH/cert paths.
        for key, value in request_env.items():
            if (
                _is_safe_env_key(key)
                and key not in self._env_denylist
                and key not in inherited
                and _is_safe_env_value(value)
            ):
                inherited[key] = value
        return inherited


def _is_safe_env_key(key: object) -> bool:
    """Reject identity, transport, and credential-bearing environment names."""
    if not isinstance(key, str) or not key or "\x00" in key:
        return False
    normalized = key.upper()
    if not all(char.isalnum() or char == "_" for char in normalized):
        return False
    forbidden_exact = {
        "HOME",
        "USERPROFILE",
        "SSH_AUTH_SOCK",
        "DOCKER_HOST",
        "KUBECONFIG",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "FTP_PROXY",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TMP",
        "TEMP",
        "TMPDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
    if normalized in forbidden_exact:
        return normalized in DEFAULT_ENV_ALLOWLIST and normalized not in {
            "NO_PROXY"
        }
    sensitive_fragments = (
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "API_KEY",
        "APIKEY",
        "PRIVATE_KEY",
        "CREDENTIAL",
        "AUTH",
    )
    return not any(fragment in normalized for fragment in sensitive_fragments)


def _is_safe_env_value(value: object) -> bool:
    """Accept only scalar, bounded environment values without control chars."""
    return (
        isinstance(value, str)
        and len(value) <= 4096
        and "\x00" not in value
        and "\r" not in value
        and "\n" not in value
    )
