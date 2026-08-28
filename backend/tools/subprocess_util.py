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
from typing import Tuple

logger = logging.getLogger(__name__)

#: 读取输出的共享最大上限，防止调用者请求一次性无界内存
MAX_OUTPUT_CAP_BYTES = 10 * 1024 * 1024

#: 文件偏移的共享最大上限，避免平台相关 seek 溢出
MAX_OUTPUT_OFFSET_BYTES = 2**63 - 1

#: 读输出时多读的字节数——超过上限 1 字节即判定截断
_OUTPUT_OVERREAD_MARGIN = 1

#: 杀进程组后回收子进程的宽限超时（秒）
_REAP_TIMEOUT_SECONDS = 5.0


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
    """删临时文件；不存在/被占用等一律静默（清理路径不报错）。"""
    with contextlib.suppress(OSError):
        os.unlink(path)


__all__ = [
    "make_temp_output_file",
    "read_capped_output",
    "kill_process_tree",
    "unlink_quietly",
    "MAX_OUTPUT_CAP_BYTES",
    "MAX_OUTPUT_OFFSET_BYTES",
]
