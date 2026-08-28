"""后台 shell 会话注册表。

后台进程状态保存在进程内存中；shell_id 只用于查表，绝不参与路径构造。
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .subprocess_util import kill_process_tree, read_capped_output, unlink_quietly

logger = logging.getLogger(__name__)

MAX_BACKGROUND_SESSIONS: int = 32
STATUS_RUNNING = "running"
STATUS_EXITED = "exited"


class SessionLimitExceeded(RuntimeError):  # noqa: N818
    """后台会话数已达上限。"""


@dataclass
class BashSession:
    """一个后台 shell 的状态及增量输出游标。"""

    shell_id: str
    process: subprocess.Popen
    command: str
    stdout_path: str
    stderr_path: str
    stdout_offset: int = 0
    stderr_offset: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def status(self) -> str:
        return STATUS_RUNNING if self.process.poll() is None else STATUS_EXITED


class BashSessionRegistry:
    """线程安全的后台会话表。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, BashSession] = {}
        self._lock = threading.RLock()

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def register(
        self,
        process: subprocess.Popen,
        command: str,
        stdout_path: str,
        stderr_path: str,
    ) -> BashSession:
        """登记进程；容量满时抛出 ``SessionLimitExceeded``。"""
        with self._lock:
            if len(self._sessions) >= MAX_BACKGROUND_SESSIONS:
                # 注册失败时调用方仍把进程和临时文件交给了我们；清理它们，
                # 否则达到容量上限会留下不可达的进程和输出文件。
                kill_process_tree(process)
                unlink_quietly(stdout_path)
                unlink_quietly(stderr_path)
                raise SessionLimitExceeded(
                    "后台 shell 数已达上限 %d，请先用 kill_shell 结束不需要的会话"
                    % MAX_BACKGROUND_SESSIONS
                )
            session = BashSession(
                shell_id=uuid.uuid4().hex,
                process=process,
                command=command,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            self._sessions[session.shell_id] = session
            logger.info("注册后台 shell: %s (%s)", session.shell_id, command[:80])
            return session

    def get(self, shell_id: str) -> Optional[BashSession]:
        with self._lock:
            return self._sessions.get(shell_id)

    def read_increment(self, shell_id: str, cap: int) -> Optional[Dict[str, Any]]:
        """读取新增输出；未知 shell_id 返回 ``None``。"""
        with self._lock:
            session = self._sessions.get(shell_id)
            if session is None:
                return None
            payload = self._drain(session, cap)
            payload["shell_id"] = shell_id
            return payload

    def terminate(self, shell_id: str, cap: int) -> Optional[Dict[str, Any]]:
        """终止进程、读取残余输出、清理文件并移除会话。"""
        with self._lock:
            session = self._sessions.pop(shell_id, None)
            if session is None:
                return None
            kill_process_tree(session.process)
            payload = self._drain(session, cap)
            payload["shell_id"] = shell_id
            payload["killed"] = True
            unlink_quietly(session.stdout_path)
            unlink_quietly(session.stderr_path)
            logger.info("终止后台 shell: %s", shell_id)
            return payload

    def clear(self) -> None:
        """杀掉并清空全部会话。"""
        with self._lock:
            for shell_id in list(self._sessions):
                self.terminate(shell_id, cap=1024)

    def _drain(self, session: BashSession, cap: int) -> Dict[str, Any]:
        stdout, out_truncated, session.stdout_offset = read_capped_output(
            session.stdout_path, cap=cap, offset=session.stdout_offset
        )
        stderr, err_truncated, session.stderr_offset = read_capped_output(
            session.stderr_path, cap=cap, offset=session.stderr_offset
        )
        status = session.status()
        return {
            "status": status,
            "exit_code": session.process.returncode if status == STATUS_EXITED else None,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": out_truncated or err_truncated,
        }


_REGISTRY = BashSessionRegistry()


def get_registry() -> BashSessionRegistry:
    """返回进程级单例注册表。"""
    return _REGISTRY


__all__ = [
    "MAX_BACKGROUND_SESSIONS",
    "STATUS_RUNNING",
    "STATUS_EXITED",
    "BashSession",
    "BashSessionRegistry",
    "SessionLimitExceeded",
    "get_registry",
]
