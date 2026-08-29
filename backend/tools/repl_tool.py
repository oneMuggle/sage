"""
REPL 工具 - Python 代码片段隔离执行（移植 claw-code execute_repl）

- EXECUTE 能力：M1 权限执行器按模式矩阵门控（read_only 拒绝；
  workspace_write / prompt 逐次审批；full_access 放行；破坏性升级规则
  不适用——参数名是 ``code`` 而非 ``command``，bash 校验器天然跳过）。
- ``-I`` 只提供 Python import / environment 隔离：不构成 OS 沙箱。文件系统、网络、子进程、普通环境变量和资源限制仍不隔离。
- 代码经临时 ``.py`` 文件传递而非 ``-c`` argv：Windows CreateProcess
  命令行有 32 767 字符硬上限，大片段走 argv 会直接失败；临时文件无此
  限制（执行完毕后删除）。
- 子进程 stdout/stderr 重定向到临时文件，进程结束后**只读前 100 KiB**：
  片段打印几个 GB 也不会撑爆父进程内存（磁盘暴露面 = 片段输出体积，
  可接受的取舍——比在父进程 PIPE 里无限缓冲安全得多）。
- 超时杀**整个进程组**而非单个子进程：仅在支持 ``waitid(WNOWAIT)`` 的
  POSIX 平台启动，``start_new_session=True`` 开新会话/进程组，``os.killpg``
  连孙进程一起收掉。Windows 或缺少安全进程组原语的平台在启动前拒绝执行，
  不会留下无法管理的子进程。``start_new_session`` 是 Python 3.2+ 关键字参数。
- 超时/启动失败 → ``success=False``；代码非零退出（含异常 traceback）
  → ``success=True`` 且 stdout/stderr 完整回传，让 agent 自己看栈。
- stdout/stderr 各截断到 100 KiB 上限。
"""
# Python 3.8 compatibility requires Optional annotations in this module.
# ruff: noqa: UP045

import contextlib
import logging
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from .base import BaseTool, ToolResult, ToolSchema
from .subprocess_util import (
    BoundedOutputCollector,
    ProcessGroupVerificationError,
    file_identity,
    kill_process_tree,
    make_temp_output_file,
    observe_process_exit,
    read_capped_output,
    reap_process,
    spawn_verified,
    start_bounded_output_collectors,
    unlink_owned,
    unlink_quietly,
)

logger = logging.getLogger(__name__)

#: 默认 / 上下限超时（秒）——LLM 传越界值时夹到区间内
REPL_DEFAULT_TIMEOUT_SECONDS = 30.0
REPL_MIN_TIMEOUT_SECONDS = 1.0
REPL_MAX_TIMEOUT_SECONDS = 120.0

#: stdout / stderr 各自的输出截断上限（100 KiB）
MAX_OUTPUT_BYTES = 100 * 1024

#: 单次 REPL 源代码输入上限（按 UTF-8 字节计，避免无界临时文件写入）
MAX_CODE_BYTES = 1024 * 1024


@dataclass
class _PendingReplCleanup:
    process: Any
    collectors: Optional[Tuple[BoundedOutputCollector, BoundedOutputCollector]]  # noqa: UP045
    stdout_path: str
    stderr_path: str
    stdout_identity: Optional[Tuple[int, int]] = None
    stderr_identity: Optional[Tuple[int, int]] = None
    process_group_id: Optional[int] = None  # noqa: UP045
    leader_exit_observed: bool = False
    process_group_killed: bool = False


_PENDING_CLEANUPS: List[_PendingReplCleanup] = []
_PENDING_CLEANUPS_LOCK = threading.RLock()


def _close_process_streams(process: Any) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            with contextlib.suppress(OSError, ValueError):
                stream.close()


def _timeout_validation_error(timeout: object) -> Optional[str]:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):  # noqa: UP038 — py3.8 不支持 X | Y isinstance
        return "timeout 必须是数字"
    try:
        numeric_timeout = float(timeout)
    except (TypeError, ValueError, OverflowError):
        return "timeout 必须是有限数字"
    if not math.isfinite(numeric_timeout):
        return "timeout 必须是有限数字"
    return None


def _attempt_process_group_kill(
    process: Any,
    process_group_id: Optional[int],  # noqa: UP045
    leader_exit_observed: bool,
    process_group_killed: bool,
) -> Tuple[bool, bool]:
    if process_group_killed:
        return leader_exit_observed, True
    if process_group_id is None:
        return leader_exit_observed, False
    observed = True if leader_exit_observed else observe_process_exit(process, 0.0)
    if observed is True:
        leader_exit_observed = True
        return leader_exit_observed, kill_process_tree(
            process,
            reap=False,
            process_group_id=process_group_id,
            kill_exited_group=True,
            leader_exit_observed=True,
        )
    if observed is False:
        return leader_exit_observed, kill_process_tree(
            process,
            reap=False,
            process_group_id=process_group_id,
        )
    return leader_exit_observed, False


def _retry_pending_cleanups() -> None:
    with _PENDING_CLEANUPS_LOCK:
        remaining: List[_PendingReplCleanup] = []
        for pending in _PENDING_CLEANUPS:
            pending.leader_exit_observed, pending.process_group_killed = (
                _attempt_process_group_kill(
                    pending.process,
                    pending.process_group_id,
                    pending.leader_exit_observed,
                    pending.process_group_killed,
                )
            )
            collectors = pending.collectors or ()
            for collector in collectors:
                with contextlib.suppress(Exception):
                    collector.finish(timeout=1.0)
                if collector.is_alive:
                    with contextlib.suppress(Exception):
                        collector.stop(timeout=0.1)
            # A live process whose group kill failed remains owned and must not
            # be reaped or have its files removed on this retry.
            if not pending.process_group_killed and pending.process.poll() is None:
                remaining.append(pending)
                continue
            reaped = reap_process(pending.process)
            if (
                not pending.process_group_killed
                or not reaped
                or any(collector.is_alive for collector in collectors)
            ):
                remaining.append(pending)
                continue
            _close_process_streams(pending.process)
            stdout_removed = unlink_owned(pending.stdout_path, pending.stdout_identity)
            stderr_removed = unlink_owned(pending.stderr_path, pending.stderr_identity)
            if not stdout_removed or not stderr_removed:
                remaining.append(pending)
        _PENDING_CLEANUPS[:] = remaining


def shutdown_pending_cleanups() -> None:
    """在后端关闭时尝试一次待处理的 REPL 资源清理。"""
    _retry_pending_cleanups()


def _retain_pending_cleanup(
    process: Any,
    collectors: Optional[Tuple[BoundedOutputCollector, BoundedOutputCollector]],  # noqa: UP045
    stdout_path: str,
    stderr_path: str,
    process_group_id: Optional[int],  # noqa: UP045
    *,
    stdout_identity: Optional[Tuple[int, int]] = None,
    stderr_identity: Optional[Tuple[int, int]] = None,
    leader_exit_observed: bool = False,
    process_group_killed: bool = False,
) -> None:
    with _PENDING_CLEANUPS_LOCK:
        _PENDING_CLEANUPS.append(
            _PendingReplCleanup(
                process,
                collectors,
                stdout_path,
                stderr_path,
                stdout_identity=stdout_identity,
                stderr_identity=stderr_identity,
                process_group_id=process_group_id,
                leader_exit_observed=leader_exit_observed,
                process_group_killed=process_group_killed,
            )
        )


def clamp_timeout(value: float) -> float:
    """把超时夹到 [MIN, MAX] 区间。"""
    try:
        numeric_value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("timeout 必须是有限数字") from exc
    if not math.isfinite(numeric_value):
        raise ValueError("timeout 必须是有限数字")
    return min(max(numeric_value, REPL_MIN_TIMEOUT_SECONDS), REPL_MAX_TIMEOUT_SECONDS)


def _write_temp_script(code: str) -> str:
    """把代码写入临时 ``.py`` 脚本，返回路径（调用方负责删除）。

    规避 Windows ``-c`` argv 的 32 767 字符 CreateProcess 上限；
    ``delete=False`` + 先 close 保证 Windows 上子进程能再打开该文件。
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix="sage_repl_",
        suffix=".py",
        encoding="utf-8",
        delete=False,
    ) as handle:
        path = handle.name
        try:
            handle.write(code)
        except Exception:
            unlink_quietly(path)
            raise
    return path


def _make_temp_output_file() -> str:
    """建一个承接子进程输出的空临时文件（repl 前缀）。"""
    return make_temp_output_file(prefix="sage_repl_")


def _read_capped_output(file_path: str) -> Tuple[str, bool]:
    """读输出文件前 ``MAX_OUTPUT_BYTES`` 字节；返回 (文本, 是否截断)。"""
    text, truncated, _offset = read_capped_output(file_path, cap=MAX_OUTPUT_BYTES)
    return text, truncated


class ReplTool(BaseTool):
    """REPL 工具 - 在隔离子进程中执行 Python 片段"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="repl",
            description=(
                "在隔离 Python 子进程中执行代码片段并返回 stdout/stderr/exit_code。"
                "适合快速数值验证、数据处理试验、算法草稿。"
                "python -I 仅隔离 import 与 Python 环境；不是 OS 沙箱，文件系统、网络、"
                "子进程、普通环境变量和资源限制仍不隔离。非零退出仍返回执行结果（含 traceback）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要执行的 Python 源代码"},
                    "timeout": {
                        "type": "number",
                        "description": (
                            f"超时秒数 (默认 {REPL_DEFAULT_TIMEOUT_SECONDS:.0f}，"
                            f"上限 {REPL_MAX_TIMEOUT_SECONDS:.0f})"
                        ),
                    },
                },
                "required": ["code"],
            },
        )

    def execute(
        self, code: str = "", timeout: float = REPL_DEFAULT_TIMEOUT_SECONDS, **kwargs: object
    ) -> ToolResult:
        """执行 Python 代码片段并返回执行结果。"""
        error: Optional[str] = None
        if kwargs:
            names = ", ".join(sorted(kwargs))
            error = f"未知参数: {names}（合法参数: code, timeout）"
        elif not isinstance(code, str) or not code.strip():
            error = "code 不能为空"
        elif len(code.encode("utf-8")) > MAX_CODE_BYTES:
            error = f"code 超过 {MAX_CODE_BYTES // 1024} KiB 大小上限"
        else:
            error = _timeout_validation_error(timeout)

        if error is not None:
            result = ToolResult(success=False, error=error)
        else:
            _retry_pending_cleanups()
            effective_timeout = clamp_timeout(timeout)
            script_path = None
            stdout_path = None
            stderr_path = None
            subprocess_called = False
            try:
                script_path = _write_temp_script(code)
                stdout_path = _make_temp_output_file()
                stderr_path = _make_temp_output_file()
                subprocess_called = True
                result = self._run_subprocess(
                    script_path, stdout_path, stderr_path, effective_timeout
                )
            except OSError as exc:
                result = ToolResult(success=False, error=f"REPL 子进程启动失败: {exc}")
            except Exception as exc:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
                logger.error("repl 执行失败（异常类型=%s）", type(exc).__name__)
                result = ToolResult(success=False, error="REPL 执行错误")
            finally:
                if script_path is not None:
                    unlink_quietly(script_path)
                if not subprocess_called:
                    for path in (stdout_path, stderr_path):
                        if path is not None:
                            unlink_quietly(path)

        return result

    def _run_subprocess(
        self,
        script_path: str,
        stdout_path: str,
        stderr_path: str,
        effective_timeout: float,
    ) -> ToolResult:
        """Popen + bounded PIPE collectors; kill path is owned here."""
        started = time.monotonic()
        process = None
        collectors = None
        process_group_id: Optional[int] = None
        process_group_killed = False
        leader_exit_observed = False
        owns_output_paths = False
        stdout_identity: Optional[Tuple[int, int]] = None
        stderr_identity: Optional[Tuple[int, int]] = None
        try:
            if os.name == "nt" or not hasattr(os, "waitid"):
                raise RuntimeError("REPL 平台不支持安全进程组回收")
            try:
                verified = spawn_verified(
                    [sys.executable, "-I", script_path],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except ProcessGroupVerificationError as exc:
                # Popen succeeded; retain the exposed process for fail-closed
                # cleanup instead of losing ownership during exception unwinding.
                process = exc.process
                process_group_id = exc.process_group_id
                owns_output_paths = True
                stdout_identity = file_identity(stdout_path)
                stderr_identity = file_identity(stderr_path)
                raise
            process = verified.process
            process_group_id = verified.process_group_id
            owns_output_paths = True
            stdout_identity = file_identity(stdout_path)
            stderr_identity = file_identity(stderr_path)
            assert stdout_identity is not None
            assert stderr_identity is not None
            assert process.stdout is not None
            assert process.stderr is not None
            collectors = start_bounded_output_collectors(
                process.stdout, process.stderr, stdout_path, stderr_path,
                max_bytes=MAX_OUTPUT_BYTES,
            )
            timed_out = False
            observed_exit = observe_process_exit(process, effective_timeout)
            if observed_exit is True:
                leader_exit_observed = True
                process_group_killed = kill_process_tree(
                    process,
                    reap=False,
                    process_group_id=process_group_id,
                    kill_exited_group=True,
                    leader_exit_observed=True,
                )
            elif observed_exit is False:
                timed_out = True
                process_group_killed = kill_process_tree(
                    process, reap=False, process_group_id=process_group_id
                )
            else:
                try:
                    process.wait(timeout=effective_timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    process_group_killed = kill_process_tree(
                        process, reap=False, process_group_id=process_group_id
                    )

            cleanup_error: Optional[BaseException] = None
            if not process_group_killed:
                cleanup_error = RuntimeError("REPL 进程组无法安全终止")
            for collector in collectors:
                try:
                    finished = collector.finish(timeout=1.0)
                    if not finished:
                        cleanup_error = cleanup_error or RuntimeError(
                            "REPL 输出 collector 未能停止"
                        )
                except Exception as exc:  # noqa: BLE001
                    cleanup_error = cleanup_error or exc
                if collector.is_alive:
                    try:
                        stopped = collector.stop(timeout=0.5)
                        if not stopped:
                            cleanup_error = cleanup_error or RuntimeError(
                                "REPL 输出 collector 仍在运行"
                            )
                    except Exception as exc:  # noqa: BLE001
                        cleanup_error = cleanup_error or exc
            can_reap = process_group_killed or process.poll() is not None
            reaped = reap_process(process) if can_reap else False
            if not reaped:
                cleanup_error = cleanup_error or RuntimeError("REPL 子进程仍在运行")
            if cleanup_error is not None:
                logger.error("repl 资源清理失败（异常类型=%s）", type(cleanup_error).__name__)
                return ToolResult(success=False, error="REPL 资源清理失败")
            if timed_out:
                return ToolResult(
                    success=False,
                    error=f"REPL 执行超时（{effective_timeout:g} 秒），子进程已被终止",
                )

            duration = time.monotonic() - started
            stdout, stdout_truncated = _read_capped_output(stdout_path)
            stderr, stderr_truncated = _read_capped_output(stderr_path)
            stdout_collector_truncated = collectors[0].overflowed or collectors[0].output_lost
            stderr_collector_truncated = collectors[1].overflowed or collectors[1].output_lost
            if stdout_collector_truncated and not stdout_truncated:
                stdout = f"{stdout}\n...[输出超过 {MAX_OUTPUT_BYTES // 1024} KiB 上限，已截断]"
                stdout_truncated = True
            if stderr_collector_truncated and not stderr_truncated:
                stderr = f"{stderr}\n...[输出超过 {MAX_OUTPUT_BYTES // 1024} KiB 上限，已截断]"
                stderr_truncated = True
            return ToolResult(
                success=True,
                content={"exit_code": process.returncode, "stdout": stdout,
                         "stderr": stderr, "duration_seconds": round(duration, 3),
                         "truncated": stdout_truncated or stderr_truncated or
                         stdout_collector_truncated or stderr_collector_truncated},
            )
        finally:
            final_cleanup_error: Optional[BaseException] = None
            if process is not None:
                if collectors is None:
                    if process_group_id is not None and not leader_exit_observed:
                        observed = observe_process_exit(process, 0.0)
                        if observed is True:
                            leader_exit_observed = True
                    if process_group_id is not None and leader_exit_observed:
                        process_group_killed = kill_process_tree(
                            process,
                            reap=False,
                            process_group_id=process_group_id,
                            kill_exited_group=True,
                            leader_exit_observed=True,
                        )
                    elif process_group_id is not None and process.poll() is None:
                        process_group_killed = kill_process_tree(
                            process,
                            reap=False,
                            process_group_id=process_group_id,
                        )
                    else:
                        process_group_killed = False
                    if not process_group_killed:
                        final_cleanup_error = RuntimeError("REPL 进程组无法安全终止")
                    safe_to_remove = (
                        (process_group_killed or process.poll() is not None)
                        and reap_process(process)
                    )
                else:
                    safe_to_remove = (
                        process_group_killed
                        and process.poll() is not None
                        and not any(collector.is_alive for collector in collectors)
                    )
                if not safe_to_remove:
                    _retain_pending_cleanup(
                        process,
                        collectors,
                        stdout_path,
                        stderr_path,
                        process_group_id,
                        stdout_identity=stdout_identity,
                        stderr_identity=stderr_identity,
                        leader_exit_observed=leader_exit_observed,
                        process_group_killed=process_group_killed,
                    )
                    if final_cleanup_error is not None:
                        logger.error(
                            "repl 资源清理失败（异常类型=%s）",
                            type(final_cleanup_error).__name__,
                        )
            else:
                safe_to_remove = not owns_output_paths
            if safe_to_remove:
                if process is not None:
                    _close_process_streams(process)
                stdout_removed = unlink_owned(stdout_path, stdout_identity)
                stderr_removed = unlink_owned(stderr_path, stderr_identity)
                cleanup_ok = stdout_removed and stderr_removed
                if not cleanup_ok:
                    final_cleanup_error = final_cleanup_error or RuntimeError(
                        "REPL 输出文件清理失败"
                    )
                    if process is not None:
                        _retain_pending_cleanup(
                            process,
                            collectors,
                            stdout_path,
                            stderr_path,
                            process_group_id,
                            stdout_identity=stdout_identity,
                            stderr_identity=stderr_identity,
                            leader_exit_observed=leader_exit_observed,
                            process_group_killed=process_group_killed,
                        )
                    logger.error(
                        "repl 资源清理失败（异常类型=%s）",
                        type(final_cleanup_error).__name__,
                    )
                    raise final_cleanup_error
