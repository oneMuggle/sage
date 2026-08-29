"""子进程执行共享原语（bash_tool 与 repl_tool 共用）。

三件事在两个工具里需求完全相同，因此收在一处：

- **输出走临时文件**：子进程 stdout/stderr 重定向到磁盘而非父进程 PIPE。
  PIPE 会无限缓冲——命令打印几个 GB 就撑爆后端内存；临时文件把父进程
  内存占用固定为一次读取的上限。
- **有界读取**：只读前 ``cap`` 字节（可从 ``offset`` 起，供后台增量轮询）。
- **杀进程组**：POSIX 下 ``os.killpg`` 连孙进程一起收；无法安全验证独立
  进程组的平台（包括 Windows）直接 fail closed。调用方必须以
  ``start_new_session=True`` 启动进程，否则 POSIX 上拿不到独立进程组。
"""

from __future__ import annotations

# Python 3.8 compatibility requires Optional annotations in this module.
# ruff: noqa: UP045
import contextlib
import logging
import os
import select
import signal
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: 读取输出的共享最大上限，防止调用者请求一次性无界内存
MAX_OUTPUT_CAP_BYTES = 10 * 1024 * 1024

#: 文件偏移的共享最大上限，避免平台相关 seek 溢出
MAX_OUTPUT_OFFSET_BYTES = 2**63 - 1

#: 读输出时多读的字节数——超过上限 1 字节即判定截断
_OUTPUT_OVERREAD_MARGIN = 1

#: 杀进程组后回收子进程的宽限超时（秒）
_REAP_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class VerifiedProcess:
    process: Any
    process_group_id: int


class ProcessGroupVerificationError(RuntimeError):  # noqa: N818
    def __init__(
        self,
        message: str,
        process: Any,
        process_group_id: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.process = process
        self.process_group_id = process_group_id
        self.running = process.poll() is None


def spawn_verified(
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    stdin: Any = subprocess.DEVNULL,
    stdout: Any = None,
    stderr: Any = None,
) -> VerifiedProcess:
    """Start a process with a verifiable, dedicated POSIX process group."""
    if os.name == "nt" or not hasattr(os, "waitid"):
        raise RuntimeError("平台不支持安全进程组回收")
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    try:
        process_group_id = os.getpgid(process.pid)
    except (OSError, ProcessLookupError) as exc:
        raise ProcessGroupVerificationError(
            "进程组无法安全验证", process
        ) from exc
    if process_group_id != process.pid:
        raise ProcessGroupVerificationError(
            "进程未使用独立进程组", process, process_group_id
        )
    return VerifiedProcess(process, process_group_id)


def _validate_max_bytes(max_bytes: int) -> None:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if max_bytes > MAX_OUTPUT_CAP_BYTES:
        raise ValueError(
            f"max_bytes exceeds maximum of {MAX_OUTPUT_CAP_BYTES} bytes"
        )


class BoundedOutputCollector:
    """后台消费一个 PIPE，并将最多 ``max_bytes`` 写入临时文件。

    POSIX 管道使用非阻塞读取，因此停止请求不会把线程永久卡在 ``read``；达到
    上限后仍继续消费并丢弃后续数据，避免子进程因 PIPE 背压永久卡住。
    ``overflowed`` 和 ``output_lost`` 是可观察的生命周期状态。
    """

    def __init__(self, stream: Any, path: str, max_bytes: int) -> None:
        _validate_max_bytes(max_bytes)
        self._stream = stream
        self.path = path
        self.max_bytes = max_bytes
        self.bytes_written = 0
        self.overflowed = False
        self.output_lost = False
        self._stop_event = threading.Event()
        self._nonblocking_fd: Optional[int] = None
        self._thread = threading.Thread(target=self._collect, daemon=True)
        self._prepare_nonblocking_stream()

    def _prepare_nonblocking_stream(self) -> None:
        if os.name == "nt":
            return
        try:
            fd = self._stream.fileno()
            os.set_blocking(fd, False)
        except (AttributeError, OSError, ValueError):
            return
        self._nonblocking_fd = fd

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: Optional[float] = None) -> bool:
        """请求停止 collector，并返回线程是否已结束。"""
        self._stop_event.set()
        if self._thread.ident is None:
            self._close_stream()
            return True
        self._thread.join(timeout)
        if self._thread.is_alive():
            self.output_lost = True
            self._close_stream()
            self._thread.join(0.1)
        return not self._thread.is_alive()

    def finish(self, timeout: Optional[float] = None) -> bool:
        """等待输入流自然结束；超时后强制停止并返回完成状态。"""
        if self._thread.ident is None:
            self._close_stream()
            return True
        self._thread.join(timeout)
        if self._thread.is_alive():
            return self.stop(timeout=0.1)
        return True

    def close(self) -> None:
        """关闭 collector 持有的输入流，适用于尚未启动的线程。"""
        self._stop_event.set()
        self._close_stream()

    def abort(self, timeout: Optional[float] = None) -> bool:
        """停止 collector 并关闭其输入流，适用于启动回滚。"""
        stopped = self.stop(timeout=timeout)
        self._close_stream()
        return stopped

    def join(self, timeout: Optional[float] = None) -> None:
        self._thread.join(timeout)

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _close_stream(self) -> None:
        with contextlib.suppress(OSError, ValueError):
            self._stream.close()

    def _read_chunk(self) -> Optional[bytes]:
        if self._nonblocking_fd is not None:
            try:
                ready, _, _ = select.select([self._nonblocking_fd], [], [], 0.1)
            except (OSError, ValueError) as exc:
                if self._stop_event.is_set():
                    return b""
                raise exc
            if not ready:
                return None
            try:
                return os.read(self._nonblocking_fd, 64 * 1024)
            except BlockingIOError:
                return None
        return self._read_windows_or_blocking()

    def _read_windows_or_blocking(self) -> Optional[bytes]:
        """Poll Windows anonymous pipes; retain a fallback for file-like tests."""
        try:
            fd = self._stream.fileno()
        except (AttributeError, OSError, ValueError):
            return bytes(self._stream.read(64 * 1024))
        if os.name != "nt":
            return bytes(self._stream.read(64 * 1024))
        try:
            import ctypes  # noqa: PLC0415
            import msvcrt  # noqa: PLC0415
            from ctypes import wintypes  # noqa: PLC0415

            available = wintypes.DWORD()
            handle = msvcrt.get_osfhandle(fd)  # type: ignore[attr-defined]
            ok = ctypes.windll.kernel32.PeekNamedPipe(  # type: ignore[attr-defined]
                wintypes.HANDLE(handle), None, 0, None,
                ctypes.byref(available), None,
            )
            if not ok:
                error = ctypes.windll.kernel32.GetLastError()  # type: ignore[attr-defined]
                if error == 109:  # ERROR_BROKEN_PIPE
                    return b""
                raise OSError(error, "PeekNamedPipe failed")
            if available.value == 0:
                time.sleep(0.05)
                return None
            return os.read(fd, min(available.value, 64 * 1024))
        except ImportError:
            return bytes(self._stream.read(64 * 1024))

    def _open_output(self) -> Any:
        """Open the owned output file without following symlinks.

        The descriptor, rather than the pathname, remains the collector's
        output ownership after this point.  Comparing the initial and opened
        inode also rejects a replacement race for an existing file.
        """
        try:
            expected = Path(self.path).lstat()
        except FileNotFoundError:
            expected = None
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK
        if expected is None:
            flags |= os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        try:
            actual = os.fstat(fd)
            if not stat.S_ISREG(actual.st_mode):
                raise OSError("output path is not a regular file")
            if expected is not None and (
                actual.st_dev != expected.st_dev or actual.st_ino != expected.st_ino
            ):
                raise OSError("output file changed while opening")
            return os.fdopen(fd, "ab")
        except Exception:
            os.close(fd)
            raise

    def _collect(self) -> None:
        try:
            with self._open_output() as output:
                while not self._stop_event.is_set():
                    chunk = self._read_chunk()
                    if chunk is None:
                        continue
                    if not chunk:
                        return
                    remaining = self.max_bytes - self.bytes_written
                    if remaining > 0:
                        output.write(chunk[:remaining])
                        output.flush()
                        self.bytes_written += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        self.overflowed = True
        except Exception as exc:  # noqa: BLE001 — collector must expose lost output
            self.output_lost = True
            logger.warning(
                "输出 collector 失败（文件摘要=%s，错误类型=%s）",
                os.path.basename(self.path),
                type(exc).__name__,
            )
        finally:
            self._close_stream()


def start_bounded_output_collectors(
    stdout: Any,
    stderr: Any,
    stdout_path: str,
    stderr_path: str,
    max_bytes: int = MAX_OUTPUT_CAP_BYTES,
) -> Tuple[BoundedOutputCollector, BoundedOutputCollector]:
    """启动 stdout/stderr 有界 collector；调用方把返回对象随会话保存并 join。"""
    _validate_max_bytes(max_bytes)
    collectors = []
    try:
        collectors.append(BoundedOutputCollector(stdout, stdout_path, max_bytes))
        collectors.append(BoundedOutputCollector(stderr, stderr_path, max_bytes))
        for collector in collectors:
            collector.start()
    except Exception:
        # Construction may fail before the second collector is appended.  Close
        # both streams explicitly, including the stream belonging to that
        # unconstructed collector.
        for collector in collectors:
            try:
                stopped = collector.abort(timeout=0.5)
                if not stopped:
                    collector.output_lost = True
            except Exception:
                with contextlib.suppress(Exception):
                    collector.close()
                collector.output_lost = True
        for stream in (stdout, stderr):
            with contextlib.suppress(Exception):
                stream.close()
        raise
    return collectors[0], collectors[1]


def make_temp_output_file(prefix: str = "sage_") -> str:
    """建一个承接子进程输出的空临时文件，返回路径（调用方负责删除）。"""
    with tempfile.NamedTemporaryFile(prefix=prefix, suffix=".out", delete=False) as handle:
        return handle.name


def read_capped_output(file_path: str, cap: int, offset: int = 0) -> Tuple[str, bool, int]:
    """从 ``offset`` 起读至多 ``cap`` 字节；返回 ``(文本, 是否截断, 新偏移)``。

    父进程内存占用恒定 ≤ ``cap`` + margin——子进程打印多少都不全量读。
    ``offset`` 支持后台 shell 的增量轮询：调用方存下返回的新偏移，下次
    从那里继续。

    读取失败（文件被删、权限变更等）返回说明文本而非抛异常——本函数常在
    清理路径调用，不允许崩。
    """
    if isinstance(cap, bool) or not isinstance(cap, int):
        raise ValueError("cap must be an integer")
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ValueError("offset must be an integer")
    if cap < 0 or offset < 0:
        raise ValueError("cap and offset must be non-negative")
    if cap > MAX_OUTPUT_CAP_BYTES:
        raise ValueError(f"cap exceeds maximum of {MAX_OUTPUT_CAP_BYTES} bytes")
    if offset > MAX_OUTPUT_OFFSET_BYTES:
        raise ValueError(
            f"offset exceeds maximum of {MAX_OUTPUT_OFFSET_BYTES} bytes"
        )

    fd = None
    try:
        try:
            expected = Path(file_path).lstat()
        except FileNotFoundError:
            expected = None
        except OSError as exc:
            return f"[读取子进程输出失败: {exc}]", False, offset
        flags = os.O_RDONLY | os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(file_path, flags)
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise OSError("输出路径不是普通文件")
        if expected is not None and (
            file_stat.st_dev != expected.st_dev or file_stat.st_ino != expected.st_ino
        ):
            raise OSError("输出文件在打开前后发生变化")
        with os.fdopen(fd, "rb") as handle:
            fd = None
            handle.seek(offset)
            raw = handle.read(cap + _OUTPUT_OVERREAD_MARGIN)
    except (OSError, OverflowError) as exc:
        return f"[读取子进程输出失败: {exc}]", False, offset
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
    if len(raw) <= cap:
        return raw.decode("utf-8", errors="replace"), False, offset + len(raw)
    capped = raw[:cap].decode("utf-8", errors="replace")
    cap_kib = cap // 1024
    return (
        f"{capped}\n...[输出超过 {cap_kib} KiB 上限，已截断]",
        True,
        offset + cap,
    )


def reap_process(
    process: Any,
    timeout: float = _REAP_TIMEOUT_SECONDS,
) -> bool:
    """等待进程退出而不读取 stdout/stderr，并报告是否已回收。"""
    try:
        process.wait(timeout=timeout)
    except Exception:  # noqa: BLE001 — cleanup must remain retryable
        logger.debug("子进程等待失败", exc_info=True)
    return process.poll() is not None


def _waitid_exit_result(
    process: Any, timeout: float
) -> Any:
    if os.name == "nt" or not hasattr(os, "waitid"):
        return None
    try:
        waitid = os.waitid
        flags = os.WEXITED | os.WNOHANG | os.WNOWAIT
    except AttributeError:
        return None
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        try:
            result = waitid(os.P_PID, process.pid, flags)
        except (ChildProcessError, OSError):
            return None
        if result is not None and getattr(result, "si_pid", 0) == process.pid:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def observe_process_exit(
    process: Any, timeout: float
) -> Optional[bool]:
    """用 ``waitid(WNOWAIT)`` 观察退出而不回收；不可用时返回 ``None``。"""
    result = _waitid_exit_result(process, timeout)
    return None if result is None else result is not False


def observe_process_exit_code(
    process: Any, timeout: float = 0.0
) -> Optional[int]:
    """返回已观察到的退出码，同时保留 leader 为 unreaped 状态。"""
    result = _waitid_exit_result(process, timeout)
    if result is None or result is False:
        return None
    status = int(getattr(result, "si_status", 0))
    return status if getattr(result, "si_code", 0) == getattr(os, "CLD_EXITED", 1) else -status


def kill_process_tree(  # noqa: PLR0917
    process: Any,
    reap: bool = True,
    process_group_id: Optional[int] = None,
    kill_exited_group: bool = False,
    leader_exit_observed: bool = False,
) -> bool:
    """终止安全归属的进程组/进程，并报告进程是否已回收。

    ``process_group_id`` 必须是在 ``Popen`` 后捕获的、且确认等于进程 PID 的
    独立组；不能在父进程退出后再依赖 ``getpgid`` 查找。Windows、缺少独立组
    或无法安全验证时返回 ``False``，绝不退化为只杀 leader。
    """
    if leader_exit_observed and not kill_exited_group:
        raise ValueError("leader_exit_observed requires kill_exited_group")
    if leader_exit_observed:
        process_running = False
    else:
        observed_exit = observe_process_exit(process, 0.0)
        if observed_exit is True:
            process_running = False
        elif observed_exit is False:
            process_running = True
        else:
            process_running = not isinstance(process.poll(), int)
    killed = not process_running
    should_signal = process_running or (kill_exited_group and leader_exit_observed)
    if should_signal:
        # 只有启动后捕获并验证的独立组才允许发信号。任何不确定性（包括
        # Windows、缺少 waitid 的 exited leader、或组验证失败）均 fail closed。
        if os.name == "nt" or process_group_id is None or process_group_id != process.pid:
            return False
        try:
            os.killpg(process_group_id, signal.SIGKILL)
            killed = True
        except ProcessLookupError:
            if process_running:
                killed = False
        except Exception:  # noqa: BLE001 — caller retains ownership on failure
            logger.debug("子进程组终止失败", exc_info=True)
            killed = False
    if reap:
        return reap_process(process)
    return killed


def _unlink_owned(path: str, identity: Optional[Tuple[int, int]]) -> bool:
    """Only unlink a path when it still names the originally owned regular file."""
    if identity is None:
        return False
    try:
        current = os.lstat(path)
        if not stat.S_ISREG(current.st_mode):
            return False
        if (current.st_dev, current.st_ino) != identity:
            return False
        os.unlink(path)
        return True
    except FileNotFoundError:
        # The originally owned file may have been removed externally; deletion
        # is already complete and therefore idempotently successful.
        return True
    except OSError:
        return False


def file_identity(path: str) -> Optional[Tuple[int, int]]:
    try:
        current = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(current.st_mode):
        return None
    return current.st_dev, current.st_ino


def unlink_owned(path: str, identity: Optional[Tuple[int, int]]) -> bool:
    return _unlink_owned(path, identity)


def unlink_quietly(path: str) -> None:
    """删除临时文件；失败不抛出，但记录非敏感 basename 便于观测。"""
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("临时输出文件清理失败: %s", os.path.basename(path))


__all__ = [
    "make_temp_output_file",
    "file_identity",
    "unlink_owned",
    "spawn_verified",
    "VerifiedProcess",
    "ProcessGroupVerificationError",
    "read_capped_output",
    "reap_process",
    "observe_process_exit",
    "observe_process_exit_code",
    "kill_process_tree",
    "unlink_quietly",
    "BoundedOutputCollector",
    "start_bounded_output_collectors",
    "MAX_OUTPUT_CAP_BYTES",
    "MAX_OUTPUT_OFFSET_BYTES",
]
