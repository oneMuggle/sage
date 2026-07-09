"""Subprocess 沙箱适配器（v2）。

实现 ``SandboxPort`` 协议，使用 ``asyncio.create_subprocess_exec`` 执行 Python 脚本。

设计要点
--------

- argv 构造: 元组拼接，不使用 shell=True (防命令注入)
- 环境变量: 合并父进程 env + request.env，剥离 ``env_denylist`` 中的敏感键
- cwd: 默认为脚本所在目录，可在 request 中覆盖
- 超时: ``asyncio.wait_for`` + ``proc.kill()`` + ``await proc.wait()`` 防僵尸进程
- stdout/stderr: ``PIPE`` 收集，避免泄漏到父进程
- 异常处理: 任何错误都通过 ``SandboxResult.success=False`` 表达，不向上抛异常
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Dict, FrozenSet

from backend.skills.skill_md.sandbox import (
    DEFAULT_ENV_DENYLIST,
    SandboxRequest,
    SandboxResult,
)

logger = logging.getLogger(__name__)


class SubprocessSandboxAdapter:
    """基于 asyncio subprocess 的沙箱适配器（v2）。

    Args:
        python_executable: Python 解释器路径（默认 = 当前进程的解释器）
        default_timeout_s: 默认超时时间（秒），默认 30s
        max_timeout_s: 超时上限（秒），默认 300s（防止单次脚本执行占用过多资源）
        env_denylist: 敏感环境变量黑名单（frozenset[str]），默认 ``DEFAULT_ENV_DENYLIST``
    """

    def __init__(
        self,
        *,
        python_executable: str = sys.executable,
        default_timeout_s: float = 30.0,
        max_timeout_s: float = 300.0,
        env_denylist: FrozenSet[str] = DEFAULT_ENV_DENYLIST,
    ) -> None:
        self._python_executable = python_executable
        self._default_timeout_s = default_timeout_s
        self._max_timeout_s = max_timeout_s
        self._env_denylist = env_denylist

    async def run(self, req: SandboxRequest) -> SandboxResult:
        """执行沙箱请求（永不抛异常）。

        Args:
            req: 沙箱请求

        Returns:
            ``SandboxResult``: 执行结果
        """
        start_time = time.monotonic()

        # 限制 timeout 不超过 max_timeout_s
        timeout = min(req.timeout_s, self._max_timeout_s)
        # 如果 request 的 timeout 是默认值（30.0），使用 default_timeout_s
        if req.timeout_s == 30.0:
            timeout = self._default_timeout_s

        # 构造 argv: [python, script_path, *args]
        argv = [
            self._python_executable,
            str(req.script_path.resolve()),
            *req.args,
        ]

        # 确定 cwd
        cwd = req.cwd if req.cwd is not None else req.script_path.parent
        cwd = cwd.resolve()

        # 构造 env: 父进程 env + request.env（去敏感键）
        env = self._build_env(req.env)

        try:
            # 启动子进程（无 shell=True，argv 直接拼接）
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE
                if req.stdin_data is not None
                else asyncio.subprocess.DEVNULL,
                env=env,
                cwd=cwd,
            )
        except OSError as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("Sandbox subprocess spawn failed: %s", exc)
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                error=f"spawn failed: {exc}",
            )

        # 通信 + 超时
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=req.stdin_data),
                timeout=timeout,
            )
        except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041
            # 超时: kill 子进程
            # 注: Python 3.10 中 asyncio.wait_for 抛出 asyncio.TimeoutError，
            # 而 Python 3.11+ 中它抛出内置 TimeoutError，因此需要同时捕获两者
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass  # 子进程已退出
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(
                "Sandbox subprocess timeout after %.1fs: %s",
                timeout,
                req.script_path,
            )
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                timed_out=True,
                error=f"timeout after {timeout:.1f}s",
            )

        duration_ms = int((time.monotonic() - start_time) * 1000)
        exit_code = process.returncode if process.returncode is not None else -1

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        success = exit_code == 0

        return SandboxResult(
            success=success,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )

    def _build_env(self, request_env: Dict[str, str]) -> Dict[str, str]:
        """构造子进程环境变量（剥离敏感键）。

        Args:
            request_env: request 中要求注入的环境变量

        Returns:
            合并后的环境变量 dict（敏感键已剥离）
        """
        # 从父进程继承
        env = dict(os.environ)

        # 注入 request.env（覆盖父进程同名键）
        env.update(request_env)

        # 剥离敏感键
        for key in self._env_denylist:
            env.pop(key, None)

        return env
