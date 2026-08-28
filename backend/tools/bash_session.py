"""线程安全的后台 shell 会话注册表。"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .subprocess_util import (
    MAX_OUTPUT_CAP_BYTES,
    kill_process_tree,
    read_capped_output,
    start_bounded_output_collectors,
    unlink_quietly,
)

logger = logging.getLogger(__name__)
MAX_BACKGROUND_SESSIONS: int = 32
STATUS_RUNNING = "running"
STATUS_EXITED = "exited"


class SessionLimitExceeded(RuntimeError):  # noqa: N818
    """后台会话数已达上限。"""


def _validate_cap(cap: int) -> None:
    if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
        raise ValueError("cap must be a positive integer")
    if cap > MAX_OUTPUT_CAP_BYTES:
        raise ValueError(f"cap exceeds maximum of {MAX_OUTPUT_CAP_BYTES} bytes")


@dataclass
class BashSession:
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
    """线程安全的后台会话表；shell_id 永不用于构造文件路径。"""

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
        with self._lock:
            if len(self._sessions) >= MAX_BACKGROUND_SESSIONS:
                kill_process_tree(process)
                unlink_quietly(stdout_path)
                unlink_quietly(stderr_path)
                raise SessionLimitExceeded(
                    "后台 shell 数已达上限 %d，请先用 kill_shell 结束不需要的会话"
                    % MAX_BACKGROUND_SESSIONS
                )
            self._check_process_group_contract(process)
            session = BashSession(
                shell_id=uuid.uuid4().hex,
                process=process,
                command=command,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            self._sessions[session.shell_id] = session
            # 不记录 command：它可能含有凭据或其他用户秘密。
            logger.info("注册后台 shell: %s", session.shell_id)
            return session

    @staticmethod
    def _check_process_group_contract(process: subprocess.Popen) -> None:
        if os.name == "nt":
            return
        try:
            isolated = os.getpgid(process.pid) == process.pid
        except (OSError, ProcessLookupError):
            logger.warning("后台 shell 进程组无法验证")
            return
        if not isolated:
            logger.warning("后台 shell 未使用独立进程组；终止时仅安全回收进程本体")

    def get(self, shell_id: str) -> Optional[BashSession]:
        with self._lock:
            return self._sessions.get(shell_id)

    def read_increment(self, shell_id: str, cap: int) -> Optional[Dict[str, Any]]:
        _validate_cap(cap)
        with self._lock:
            session = self._sessions.get(shell_id)
            if session is None:
                return None
            payload = self._drain(session, cap)
            payload["shell_id"] = shell_id
            return payload

    def terminate(self, shell_id: str, cap: int) -> Optional[Dict[str, Any]]:
        _validate_cap(cap)
        with self._lock:
            session = self._sessions.get(shell_id)
            if session is None:
                return None
            kill_process_tree(session.process)
            drain_error = None
            try:
                payload = self._drain(session, cap)
            except Exception as exc:  # preserve logic errors after cleanup
                drain_error = exc
                payload = {
                    "status": session.status(),
                    "exit_code": session.process.returncode,
                    "stdout": "",
                    "stderr": "",
                    "truncated": False,
                }
            finally:
                unlink_quietly(session.stdout_path)
                unlink_quietly(session.stderr_path)
                self._sessions.pop(shell_id, None)
            if drain_error is not None:
                raise drain_error
            payload["shell_id"] = shell_id
            payload["killed"] = True
            logger.info("终止后台 shell: %s", shell_id)
            return payload

    def clear(self) -> None:
        with self._lock:
            for shell_id in list(self._sessions):
                try:
                    self.terminate(shell_id, cap=1024)
                except Exception:
                    logger.warning("后台 shell 收尾读取失败: %s", shell_id)

    def _drain(self, session: BashSession, cap: int) -> Dict[str, Any]:
        stdout, out_truncated, out_offset = read_capped_output(
            session.stdout_path, cap=cap, offset=session.stdout_offset
        )
        stderr, err_truncated, err_offset = read_capped_output(
            session.stderr_path, cap=cap, offset=session.stderr_offset
        )
        session.stdout_offset = out_offset
        session.stderr_offset = err_offset
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
    return _REGISTRY


__all__ = [
    "MAX_BACKGROUND_SESSIONS", "STATUS_RUNNING", "STATUS_EXITED",
    "BashSession", "BashSessionRegistry", "SessionLimitExceeded", "get_registry",
]
