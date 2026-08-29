"""线程安全的后台 shell 会话注册表。

注册表只保存在当前后端进程内；后端重启后已注册的会话不会恢复，相关进程
可能成为孤儿。Windows 上的进程树终止也无法保证递归回收所有孙进程。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .subprocess_util import (
    MAX_OUTPUT_CAP_BYTES,
    BoundedOutputCollector,
    VerifiedProcess,
    file_identity,
    kill_process_tree,
    observe_process_exit,
    observe_process_exit_code,
    read_capped_output,
    reap_process,
    unlink_owned,
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
    process: Any
    command: str
    stdout_path: str
    stderr_path: str
    stdout_identity: Optional[Tuple[int, int]] = None
    stderr_identity: Optional[Tuple[int, int]] = None
    stdout_offset: int = 0
    stderr_offset: int = 0
    started_at: float = field(default_factory=time.monotonic)
    collectors: Optional[Tuple[BoundedOutputCollector, BoundedOutputCollector]] = None
    process_group_id: Optional[int] = None
    leader_exit_observed: bool = False
    process_group_killed: bool = False
    operation_lock: threading.RLock = field(
        default_factory=threading.RLock,
        repr=False,
        compare=False,
    )

    def status(self) -> str:
        with self.operation_lock:
            if self.leader_exit_observed or self.process_group_killed:
                return STATUS_EXITED
            if self.process_group_id is not None:
                observed = observe_process_exit(self.process, 0.0)
                if observed is True:
                    self.leader_exit_observed = True
                    return STATUS_EXITED
                if observed is False:
                    return STATUS_RUNNING
            return STATUS_RUNNING if self.process.poll() is None else STATUS_EXITED


@dataclass
class _PendingCleanup:
    process: Any
    stdout_path: str
    stderr_path: str
    collectors: Optional[Tuple[BoundedOutputCollector, BoundedOutputCollector]]
    stdout_identity: Optional[Tuple[int, int]] = None
    stderr_identity: Optional[Tuple[int, int]] = None
    process_group_id: Optional[int] = None
    leader_exit_observed: bool = False
    process_group_killed: bool = False


class BashSessionRegistry:
    """线程安全的后台会话表；shell_id 永不用于构造文件路径。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, BashSession] = {}
        self._pending_cleanup: List[_PendingCleanup] = []
        self._lock = threading.RLock()

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def register(
        self,
        verified: VerifiedProcess,
        command: str,
        stdout_path: str,
        stderr_path: str,
        collectors: Optional[Tuple[BoundedOutputCollector, BoundedOutputCollector]] = None,
    ) -> BashSession:
        if not isinstance(verified, VerifiedProcess):
            raise TypeError("registry requires VerifiedProcess from spawn_verified")
        process = verified.process
        with self._lock:
            self._retry_pending_cleanup()
            if len(self._sessions) >= MAX_BACKGROUND_SESSIONS:
                self._reject_over_limit(
                    process,
                    verified.process_group_id,
                    stdout_path,
                    stderr_path,
                    collectors,
                )
                raise SessionLimitExceeded(
                    f"后台 shell 数已达上限 {MAX_BACKGROUND_SESSIONS}，请先用 kill_shell 结束不需要的会话"
                )
            session = BashSession(
                shell_id=uuid.uuid4().hex,
                process=process,
                command=command,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                collectors=collectors,
                process_group_id=verified.process_group_id,
                stdout_identity=file_identity(stdout_path),
                stderr_identity=file_identity(stderr_path),
            )
            self._sessions[session.shell_id] = session
            # 不记录 command：它可能含有凭据或其他用户秘密。
            logger.info("注册后台 shell: %s", session.shell_id)
            return session

    def _reject_over_limit(
        self,
        process: Any,
        process_group_id: int,
        stdout_path: str,
        stderr_path: str,
        collectors: Optional[Tuple[BoundedOutputCollector, BoundedOutputCollector]],
    ) -> None:
        observed = observe_process_exit(process, 0.0)
        leader_exit_observed = observed is True
        process_group_killed = kill_process_tree(
            process,
            reap=False,
            process_group_id=process_group_id,
            kill_exited_group=leader_exit_observed,
            leader_exit_observed=leader_exit_observed,
        )
        cleanup_error = self._finish_collectors(collectors)
        reaped = reap_process(process) if process_group_killed else False
        pending = _PendingCleanup(
            process=process,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            collectors=collectors,
            stdout_identity=file_identity(stdout_path),
            stderr_identity=file_identity(stderr_path),
            process_group_id=process_group_id,
            leader_exit_observed=leader_exit_observed,
            process_group_killed=process_group_killed,
        )
        if not process_group_killed or not reaped or not self._cleanup_ready(pending):
            self._pending_cleanup.append(pending)
        else:
            stdout_removed = unlink_owned(stdout_path, pending.stdout_identity)
            stderr_removed = unlink_owned(stderr_path, pending.stderr_identity)
            if not stdout_removed or not stderr_removed:
                self._pending_cleanup.append(pending)
        if cleanup_error is not None:
            logger.warning("后台 shell 输出 collector 收尾失败")

    def _cleanup_ready(self, pending: _PendingCleanup) -> bool:
        return pending.process.poll() is not None and not self._collectors_alive(
            pending.collectors
        )

    def get(self, shell_id: str) -> Optional[BashSession]:
        with self._lock:
            return self._sessions.get(shell_id)

    def read_increment(self, shell_id: str, cap: int) -> Optional[Dict[str, Any]]:
        _validate_cap(cap)
        with self._lock:
            session = self._sessions.get(shell_id)
        if session is None:
            return None
        with session.operation_lock:
            payload = self._drain(session, cap)
        payload["shell_id"] = shell_id
        return payload

    def terminate(self, shell_id: str, cap: int) -> Optional[Dict[str, Any]]:
        _validate_cap(cap)
        with self._lock:
            session = self._sessions.get(shell_id)
            if session is None:
                return None

            kill_ok = self._terminate_process_group(session)
            if kill_ok:
                session.process_group_killed = True
            cleanup_error = self._finish_collectors(session.collectors)
            # A failed kill must not turn into an unconditional wait/reap while
            # the leader is still live: ownership remains with this session.
            can_reap = kill_ok or session.process.poll() is not None
            reaped = reap_process(session.process) if can_reap else False
            if not kill_ok or not reaped or self._collectors_alive(session.collectors):
                if cleanup_error is None:
                    cleanup_error = RuntimeError("后台 shell 资源仍在使用或无法安全清理")
                raise cleanup_error
            drain_error = cleanup_error
            try:
                payload = self._drain(session, cap)
            except Exception as exc:  # preserve logic errors after cleanup
                if drain_error is None:
                    drain_error = exc
                payload = {
                    "status": session.status(),
                    "exit_code": session.process.returncode,
                    "stdout": "",
                    "stderr": "",
                    "truncated": True,
                }
            stdout_removed = unlink_owned(session.stdout_path, session.stdout_identity)
            stderr_removed = unlink_owned(session.stderr_path, session.stderr_identity)
            cleanup_done = stdout_removed and stderr_removed
            if not cleanup_done:
                if drain_error is None:
                    drain_error = RuntimeError("后台 shell 输出文件清理失败")
                raise drain_error
            self._sessions.pop(shell_id, None)
            if drain_error is not None:
                raise drain_error
            payload["shell_id"] = shell_id
            payload["killed"] = True
            logger.info("终止后台 shell: %s", shell_id)
            return payload

    def _terminate_process_group(self, session: BashSession) -> bool:
        if session.process_group_killed:
            return True
        if session.leader_exit_observed:
            return kill_process_tree(
                session.process,
                reap=False,
                process_group_id=session.process_group_id,
                kill_exited_group=True,
                leader_exit_observed=True,
            )

        observed = observe_process_exit(session.process, 0.0)
        if observed is True:
            session.leader_exit_observed = True
            return kill_process_tree(
                session.process,
                reap=False,
                process_group_id=session.process_group_id,
                kill_exited_group=True,
                leader_exit_observed=True,
            )
        if observed is None and session.process.poll() is not None:
            raise RuntimeError("后台 shell 已退出但无法安全观察进程组")
        return kill_process_tree(
            session.process,
            reap=False,
            process_group_id=session.process_group_id,
        )

    def _retry_pending_cleanup(self) -> None:
        remaining: List[_PendingCleanup] = []
        for pending in self._pending_cleanup:
            kill_ok = pending.process_group_killed
            if not kill_ok and pending.process.poll() is None:
                kill_ok = kill_process_tree(
                    pending.process,
                    reap=False,
                    process_group_id=pending.process_group_id,
                )
            elif not kill_ok and pending.process_group_id is not None:
                observed = observe_process_exit(pending.process, 0.0)
                if observed is True:
                    kill_ok = kill_process_tree(
                        pending.process,
                        reap=False,
                        process_group_id=pending.process_group_id,
                        kill_exited_group=True,
                        leader_exit_observed=True,
                    )
            if not kill_ok and pending.process.poll() is None:
                # A live process with a failed group kill must not be reaped.
                pending.process_group_killed = False
                remaining.append(pending)
                continue
            self._finish_collectors(pending.collectors)
            if kill_ok and pending.process.poll() is None:
                reap_process(pending.process)
            reaped = pending.process.poll() is not None
            if not kill_ok or not reaped or not self._cleanup_ready(pending):
                pending.process_group_killed = kill_ok
                remaining.append(pending)
                continue
            stdout_removed = unlink_owned(pending.stdout_path, pending.stdout_identity)
            stderr_removed = unlink_owned(pending.stderr_path, pending.stderr_identity)
            if not stdout_removed or not stderr_removed:
                remaining.append(pending)
        self._pending_cleanup = remaining

    def pending_cleanup_count(self) -> int:
        with self._lock:
            self._retry_pending_cleanup()
            return len(self._pending_cleanup)

    def _finish_collectors(
        self,
        collectors: Optional[Tuple[BoundedOutputCollector, BoundedOutputCollector]],
    ) -> Optional[BaseException]:
        first_error: Optional[BaseException] = None
        if collectors:
            for collector in collectors:
                try:
                    finished = collector.finish(timeout=1.0)
                    if not finished:
                        if first_error is None:
                            first_error = RuntimeError(
                                "后台 shell 输出 collector 未能在超时内结束"
                            )
                        try:
                            collector.stop(timeout=0.1)
                        except Exception as stop_exc:  # noqa: BLE001 — continue cleanup
                            if first_error is None:
                                first_error = stop_exc
                except Exception as exc:  # noqa: BLE001 — continue all cleanup
                    if first_error is None:
                        first_error = exc
                    try:
                        stopped = collector.stop(timeout=0.1)
                        if not stopped and first_error is None:
                            first_error = RuntimeError(
                                "后台 shell 输出 collector 仍在运行"
                            )
                    except Exception as stop_exc:  # noqa: BLE001 — continue cleanup
                        if first_error is None:
                            first_error = stop_exc
        return first_error

    @staticmethod
    def _collectors_alive(
        collectors: Optional[Tuple[BoundedOutputCollector, BoundedOutputCollector]],
    ) -> bool:
        return any(bool(collector.is_alive) for collector in collectors or ())

    def clear(self) -> None:
        with self._lock:
            self._retry_pending_cleanup()
            for shell_id in list(self._sessions):
                try:
                    self.terminate(shell_id, cap=1024)
                except Exception:
                    # 继续处理其余会话；失败项由 terminate 保留以便重试。
                    logger.warning("后台 shell 收尾失败: %s", shell_id)
            self._retry_pending_cleanup()

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
        # 退出码：已退出时优先用 ``observe_process_exit_code`` 观察真实退出码
        # （``process.returncode`` 在 leader 已退出但未被 ``wait`` 时仍为 None）。
        # 仍运行时退到 ``returncode``（同样是 None），调用方按 status 区分即可。
        if status == STATUS_EXITED:
            observed_code = observe_process_exit_code(session.process, timeout=0.0)
            exit_code = (
                observed_code
                if observed_code is not None
                else session.process.returncode
            )
        else:
            exit_code = None
        collector_truncated = any(
            collector.overflowed or collector.output_lost
            for collector in (session.collectors or ())
        )
        return {
            "status": status,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": out_truncated or err_truncated or collector_truncated,
        }


_REGISTRY = BashSessionRegistry()


def get_registry() -> BashSessionRegistry:
    return _REGISTRY


__all__ = [
    "MAX_BACKGROUND_SESSIONS", "STATUS_RUNNING", "STATUS_EXITED",
    "BashSession", "BashSessionRegistry", "SessionLimitExceeded", "get_registry",
]
