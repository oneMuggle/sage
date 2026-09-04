"""``safe_run``：适配器与 runtime_exec 共用的安全子进程封装。

设计目标：

- argv 数组启动，**禁止** shell 拼接或 ``shell=True``。
- stdout/stderr 走 ``subprocess_util`` 的临时文件 + 上限读取。
- 超时强制走进程组回收（POSIX）；Windows 下退化为 ``process.kill()``。
- 可选 stdin 写入。
- 错误信息绝不返回完整环境变量或敏感路径内容。
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import List, Optional

from backend.tools.runtime_adapter import SafeRunResult
from backend.tools.subprocess_util import (
    kill_process_tree,
    make_temp_output_file,
    read_capped_output,
)

logger = logging.getLogger(__name__)


DEFAULT_OUTPUT_CAP = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_OUTPUT_CAP = 10 * 1024 * 1024


def safe_run(
    argv: List[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    input_text: Optional[str] = None,
    output_cap: int = DEFAULT_OUTPUT_CAP,
) -> SafeRunResult:
    """统一的子进程调用入口。

    Args:
        argv: 命令参数数组（首元素为可执行文件）。
        timeout: 超时秒数；超时后强制回收进程组。
        cwd: 工作目录。
        env: 环境变量映射；``None`` 表示使用隔离环境（只保留最小白名单）。
        input_text: 通过 stdin 写入的文本。
        output_cap: stdout/stderr 读取上限（字节）。

    Returns:
        ``SafeRunResult`` 结构化结果。
    """

    if not argv:
        return SafeRunResult(
            exit_code=None,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            error="argv 不能为空",
        )

    capped_output = min(int(output_cap), MAX_OUTPUT_CAP)
    sanitized_env = _sanitized_env(env)
    stdout_path = make_temp_output_file(prefix="sage_probe_stdout_")
    stderr_path = make_temp_output_file(prefix="sage_probe_stderr_")

    start = time.monotonic()
    process: Optional[subprocess.Popen] = None
    try:
        process = subprocess.Popen(  # noqa: S603
            list(argv),
            cwd=str(cwd) if cwd else None,
            env=sanitized_env,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=open(stdout_path, "wb"),  # noqa: SIM115
            stderr=open(stderr_path, "wb"),  # noqa: SIM115
            start_new_session=True,
            shell=False,
        )
    except FileNotFoundError as exc:
        return SafeRunResult(
            exit_code=None,
            stdout="",
            stderr="",
            duration_seconds=time.monotonic() - start,
            error=f"找不到可执行文件: {argv[0]} ({exc})",
        )
    except OSError as exc:
        return SafeRunResult(
            exit_code=None,
            stdout="",
            stderr="",
            duration_seconds=time.monotonic() - start,
            error=f"启动失败: {exc}",
        )

    timed_out = False
    exit_code: Optional[int] = None
    try:
        if input_text is not None and process.stdin is not None:
            try:
                process.stdin.write(input_text.encode("utf-8", errors="replace"))
                process.stdin.close()
            except BrokenPipeError:
                # 子进程已退出
                pass

        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            logger.warning(
                "safe_run timeout argv=%s after %.1fs", argv[0], timeout
            )
            try:
                kill_process_tree(process)
            except Exception as cleanup_exc:  # noqa: BLE001
                logger.debug("kill_process_tree 失败", exc_info=cleanup_exc)
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                with suppress(Exception):
                    stream.close()

    stdout_text, stdout_truncated, _ = read_capped_output(stdout_path, capped_output, 0)
    stderr_text, stderr_truncated, _ = read_capped_output(stderr_path, capped_output, 0)
    output_truncated = stdout_truncated or stderr_truncated

    for path in (stdout_path, stderr_path):
        with suppress(OSError):
            os.unlink(path)

    return SafeRunResult(
        exit_code=exit_code,
        stdout=stdout_text,
        stderr=stderr_text,
        duration_seconds=time.monotonic() - start,
        timed_out=timed_out,
        output_truncated=output_truncated,
        error="safe_run 超时" if timed_out else None,
    )


SAFE_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
    }
)


def _sanitized_env(overrides: Optional[dict]) -> Optional[dict]:
    """构造最小白名单环境；``None`` 表示使用父进程白名单结果。"""

    base: dict
    if overrides is not None:
        base = {k: v for k, v in os.environ.items() if k in SAFE_ENV_ALLOWLIST}
        base.update(overrides)
        return base
    return {k: v for k, v in os.environ.items() if k in SAFE_ENV_ALLOWLIST}
