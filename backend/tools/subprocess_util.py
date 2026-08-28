"""子进程执行共享原语（bash_tool 与 repl_tool 共用）。

三件事在两个工具里需求完全相同，因此收在一处：

- **输出走临时文件**：子进程 stdout/stderr 重定向到磁盘而非父进程 PIPE。
  PIPE 会无限缓冲——命令打印几个 GB 就撑爆后端内存；临时文件把父进程
  内存占用固定为一次读取的上限。
- **有界读取**：只读前 ``cap`` 字节（可从 ``offset`` 起，供后台增量轮询）。
- **杀进程组**：POSIX 下 ``os.killpg`` 连孙进程一起收；Windows 退化为
  ``process.kill()``（杀不到孙进程，已知限制）。调用方必须以
  ``start_new_session=True`` 启动进程，否则 POSIX 上拿不到独立进程组。
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import tempfile
import threading
from typing import BinaryIO, Optional, Tuple

logger = logging.getLogger(__name__)

#: 读取输出的共享最大上限，防止调用者请求一次性无界内存
MAX_OUTPUT_CAP_BYTES = 10 * 1024 * 1024

#: 文件偏移的共享最大上限，避免平台相关 seek 溢出
MAX_OUTPUT_OFFSET_BYTES = 2**63 - 1

#: 读输出时多读的字节数——超过上限 1 字节即判定截断
_OUTPUT_OVERREAD_MARGIN = 1

#: 杀进程组后回收子进程的宽限超时（秒）
_REAP_TIMEOUT_SECONDS = 5.0


class BoundedOutputCollector:
    """后台消费一个 PIPE，并将最多 ``max_bytes`` 写入临时文件。

    线程持续消费 PIPE，即使达到上限也继续读取并丢弃后续数据，避免子进程
    因 PIPE 背压永久卡住。``overflowed`` 是可观察的生命周期状态。
    """

    def __init__(self, stream: BinaryIO, path: str, max_bytes: int) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self._stream = stream
        self.path = path
        self.max_bytes = max_bytes
        self.bytes_written = 0
        self.overflowed = False
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._collect, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: Optional[float] = None) -> None:
        """停止 collector；关闭 PIPE 使阻塞读取在各平台可返回。"""
        self._stop_event.set()
        with contextlib.suppress(OSError, ValueError):
            self._stream.close()
        self._thread.join(timeout)
    def join(self, timeout: Optional[float] = None) -> None:
        self._thread.join(timeout)

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _collect(self) -> None:
        try:
            with open(self.path, "ab") as output:
                while True:
                    chunk = self._stream.read(64 * 1024)
                    if not chunk:
                        return
                    remaining = self.max_bytes - self.bytes_written
                    if remaining > 0:
                        output.write(chunk[:remaining])
                        output.flush()
                        self.bytes_written += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        self.overflowed = True
        except (OSError, ValueError) as exc:
            logger.warning("输出 collector 失败（文件摘要=%s）: %s", os.path.basename(self.path), exc)


def start_bounded_output_collectors(
    stdout: BinaryIO, stderr: BinaryIO, stdout_path: str, stderr_path: str,
    max_bytes: int = MAX_OUTPUT_CAP_BYTES,
) -> Tuple[BoundedOutputCollector, BoundedOutputCollector]:
    """启动 stdout/stderr 有界 collector；调用方把返回对象随会话保存并 join。"""
    collectors = (
        BoundedOutputCollector(stdout, stdout_path, max_bytes),
        BoundedOutputCollector(stderr, stderr_path, max_bytes),
    )
    for collector in collectors:
        collector.start()
    return collectors


def make_temp_output_file(prefix: str = "sage_") -> str:
    """建一个承接子进程输出的空临时文件，返回路径（调用方负责删除）。"""
    handle = tempfile.NamedTemporaryFile(prefix=prefix, suffix=".out", delete=False)
    handle.close()
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

    try:
        with open(file_path, "rb") as handle:
            handle.seek(offset)
            raw = handle.read(cap + _OUTPUT_OVERREAD_MARGIN)
    except (OSError, OverflowError) as exc:
        return f"[读取子进程输出失败: {exc}]", False, offset
    if len(raw) <= cap:
        return raw.decode("utf-8", errors="replace"), False, offset + len(raw)
    capped = raw[:cap].decode("utf-8", errors="replace")
    cap_kib = cap // 1024
    return (
        f"{capped}\n...[输出超过 {cap_kib} KiB 上限，已截断]",
        True,
        offset + cap,
    )


def kill_process_tree(process: subprocess.Popen) -> None:
    """杀整个进程组（POSIX）或进程自身（Windows 尽力，杀不到孙进程）。"""
    try:
        if os.name != "nt":
            try:
                pgid = os.getpgid(process.pid)
            except (ProcessLookupError, PermissionError):
                # 组号拿不到（极端竞态）→ 退化只杀子进程本体
                process.kill()
            else:
                if pgid == process.pid:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    process.kill()
        else:
            process.kill()
    except Exception:  # noqa: BLE001 — 清理路径：杀失败也不允许抛出
        logger.debug("子进程终止失败", exc_info=True)
    try:
        process.communicate(timeout=_REAP_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 — 同上
        logger.debug("子进程回收失败", exc_info=True)


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
    "read_capped_output",
    "kill_process_tree",
    "unlink_quietly",
    "BoundedOutputCollector",
    "start_bounded_output_collectors",
    "MAX_OUTPUT_CAP_BYTES",
    "MAX_OUTPUT_OFFSET_BYTES",
]
