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
from typing import Any, Callable, Dict, List, Optional, Tuple

from .subprocess_util import (
    MAX_OUTPUT_CAP_BYTES,
    BoundedOutputCollector,
    ResurrectedProcess,
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
#: 退出观察器扫描间隔（Phase 1 wake_on_background 依赖）。
EXIT_WATCH_POLL_SECONDS = 5.0


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

    def __init__(
        self,
        max_sessions: Optional[int] = None,
        store_getter: Optional[Callable[[], Any]] = None,
    ) -> None:
        # max_sessions=None → 模块默认（PR-2 前的硬编码行为）。经 get_registry()
        # 创建的实例由 load_bash_config() 供给配置值；直接构造（多数单测）不变。
        self._max_sessions = MAX_BACKGROUND_SESSIONS if max_sessions is None else int(max_sessions)
        self._sessions: Dict[str, BashSession] = {}
        self._pending_cleanup: List[_PendingCleanup] = []
        self._lock = threading.RLock()
        # 2026-11-06 Phase 1：退出观察器（wake_on_background 等工具登记回调，
        # daemon 线程每 5s 扫一次，检测 running → exited 转换并触发）。
        self._exit_watches: Dict[str, List[Callable[[str, Optional[int]], None]]] = {}
        self._exited_seen: set = set()
        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_stop = threading.Event()
        # 2026-11-06 Phase 2：SQLite 持久化（None = 纯内存，单测默认）。
        self._store_getter = store_getter

    def _get_store(self) -> Optional[Any]:
        if self._store_getter is None:
            return None
        try:
            return self._store_getter()
        except Exception:  # noqa: BLE001 — 持久化不可用不阻断内存路径
            logger.exception("后台 shell 持久化仓储不可用")
            return None

    def _store_remove(self, shell_id: str) -> None:
        store = self._get_store()
        if store is None:
            return
        try:
            store.remove(shell_id)
        except Exception:  # noqa: BLE001 — 删除失败不阻断清理
            logger.exception("后台 shell 持久化删除失败: %s", shell_id)

    @property
    def max_sessions(self) -> int:
        return self._max_sessions

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def list_sessions(self) -> List[BashSession]:
        """返回当前注册表快照（供 ``GET /api/v1/shells`` 使用）。"""
        with self._lock:
            return list(self._sessions.values())

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
            if len(self._sessions) >= self._max_sessions:
                self._reject_over_limit(
                    process,
                    verified.process_group_id,
                    stdout_path,
                    stderr_path,
                    collectors,
                )
                raise SessionLimitExceeded(
                    f"后台 shell 数已达上限 {self._max_sessions}，请先用 kill_shell 结束不需要的会话"
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
        store = self._get_store()
        if store is not None:
            try:
                store.persist(session)
            except Exception:  # noqa: BLE001 — 持久化失败不阻断注册
                logger.exception("后台 shell 持久化失败: %s", session.shell_id)
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

    # ---------- 2026-11-06 Phase 1: 退出观察器 ----------

    def register_watcher(
        self,
        shell_id: str,
        callback: Callable[[str, Optional[int]], None],
    ) -> bool:
        """为后台 shell 登记退出回调。

        - shell 不存在 → 返回 ``False``；
        - shell 已退出 → 立即同步触发一次（exit_code 可能为 None）；
        - 否则登记并由 daemon 线程在检测到 running → exited 时触发。

        回调异常被隔离，不影响其它观察者或 watcher 线程。
        """
        with self._lock:
            session = self._sessions.get(shell_id)
            if session is None:
                return False
            fired_already = shell_id in self._exited_seen
            if fired_already:
                pending: List[Callable[[str, Optional[int]], None]] = [callback]
            else:
                pending = self._exit_watches.setdefault(shell_id, [])
                pending.append(callback)
                self._ensure_watcher()
            already_exited = fired_already or session.status() == STATUS_EXITED
            if already_exited:
                self._exited_seen.add(shell_id)
                self._exit_watches.pop(shell_id, None)
            else:
                pending = []
        if already_exited:
            exit_code = observe_process_exit_code(session.process, 0.0)
            for cb in pending:
                self._safe_invoke(cb, shell_id, exit_code)
        return True

    def unregister_watcher(
        self,
        shell_id: str,
        callback: Optional[Callable[[str, Optional[int]], None]] = None,
    ) -> None:
        """移除某 shell 的全部（或指定）退出回调。"""
        with self._lock:
            if callback is None:
                self._exit_watches.pop(shell_id, None)
                return
            pending = self._exit_watches.get(shell_id)
            if not pending:
                return
            if callback in pending:
                pending.remove(callback)
            if not pending:
                self._exit_watches.pop(shell_id, None)

    def register_exit_notification(
        self, shell_id: str, session_id: Optional[str] = None
    ) -> bool:
        """登记默认退出通知：完成时推入后台任务通知队列（Phase 1）。

        Electron 主进程轮询 drain 端点后转成 OS 通知；与定时任务/待办提醒
        共用同一消费节奏。
        """
        session = self.get(shell_id)
        if session is None:
            return False
        command = session.command

        def _notify(finished_shell_id: str, exit_code: Optional[int]) -> None:
            try:
                from backend.services.background_notifications import (
                    get_background_notification_queue,
                )

                get_background_notification_queue().push(
                    shell_id=finished_shell_id,
                    command=command,
                    exit_code=exit_code,
                    session_id=session_id,
                )
            except Exception:  # noqa: BLE001 — 通知失败不影响唤醒链
                logger.exception("后台 shell 完成通知入队失败: %s", finished_shell_id)

        return self.register_watcher(shell_id, _notify)

    def _ensure_watcher(self) -> None:
        """首次登记时启动 daemon 线程（调用方需持有 self._lock）。"""
        if self._watcher_thread is not None and self._watcher_thread.is_alive():
            return
        self._watcher_stop.clear()
        thread = threading.Thread(
            target=self._run_watcher,
            daemon=True,
            name="bash-session-watcher",
        )
        self._watcher_thread = thread
        thread.start()

    def _run_watcher(self) -> None:
        while not self._watcher_stop.wait(EXIT_WATCH_POLL_SECONDS):
            try:
                self._poll_watches()
            except Exception:  # noqa: BLE001 — watcher 线程不得因单次异常退出
                logger.exception("后台 shell 退出观察器 tick 失败")

    def _poll_watches(self) -> None:
        with self._lock:
            shell_ids = list(self._exit_watches)
        for shell_id in shell_ids:
            session = self.get(shell_id)
            if session is None:
                # 会话已被 terminate/clear 移除：按"已结束（无退出码）"触发，
                # 避免 COMPLETION wake 永远停留在 PENDING。
                with self._lock:
                    if shell_id in self._exited_seen:
                        self._exit_watches.pop(shell_id, None)
                        continue
                    self._exited_seen.add(shell_id)
                    callbacks = self._exit_watches.pop(shell_id, [])
                self._store_remove(shell_id)
                for cb in callbacks:
                    self._safe_invoke(cb, shell_id, None)
                continue
            if session.status() != STATUS_EXITED:
                continue
            with self._lock:
                if shell_id in self._exited_seen:
                    continue
                self._exited_seen.add(shell_id)
                callbacks = self._exit_watches.pop(shell_id, [])
            self._store_remove(shell_id)
            exit_code = observe_process_exit_code(session.process, 0.0)
            for cb in callbacks:
                self._safe_invoke(cb, shell_id, exit_code)

    @staticmethod
    def _safe_invoke(
        callback: Callable[[str, Optional[int]], None],
        shell_id: str,
        exit_code: Optional[int],
    ) -> None:
        try:
            callback(shell_id, exit_code)
        except Exception:  # noqa: BLE001 — 单个回调失败不阻断其它观察者
            logger.exception("后台 shell 退出回调失败: %s", shell_id)

    # ---------- 2026-11-06 Phase 2: 重启恢复 ----------

    def restore(self) -> int:
        """从持久化恢复存活 shell；返回恢复数量。

        - 仍存活（POSIX: pgid 匹配；Windows: tasklist 探测）→ 加入注册表并
          登记默认退出通知；
        - 已结束 / PID 被复用 / 输出文件身份不匹配 → 删除记录并推一条
          「未知退出码」完成通知（用户重启后仍能感知任务已结束）。
        """
        store = self._get_store()
        if store is None:
            return 0
        restored = 0
        for rec in store.list_all():
            proc = ResurrectedProcess(pid=rec.pid, pgid=rec.pgid)
            if proc.poll() is not None:
                self._notify_restored_exit(rec)
                self._store_remove(rec.shell_id)
                continue
            if not self._restored_files_match(rec):
                logger.warning("后台 shell 输出文件身份不匹配，放弃恢复: %s", rec.shell_id)
                self._notify_restored_exit(rec)
                self._store_remove(rec.shell_id)
                continue
            session = BashSession(
                shell_id=rec.shell_id,
                process=proc,
                command=rec.command,
                stdout_path=rec.stdout_path,
                stderr_path=rec.stderr_path,
                stdout_identity=rec.stdout_identity,
                stderr_identity=rec.stderr_identity,
                stdout_offset=rec.stdout_offset,
                stderr_offset=rec.stderr_offset,
                process_group_id=rec.pgid,
            )
            with self._lock:
                # 恢复路径不执行 max_sessions 检查：这些进程已经存在，
                # 拒绝恢复只会让它们变成不可管理的孤儿。
                self._sessions[rec.shell_id] = session
            self.register_exit_notification(rec.shell_id)
            restored += 1
            logger.info("恢复后台 shell: %s (pid=%s)", rec.shell_id, rec.pid)
        return restored

    @staticmethod
    def _restored_files_match(rec: Any) -> bool:
        if rec.stdout_identity is None or rec.stderr_identity is None:
            return False
        return (
            file_identity(rec.stdout_path) == rec.stdout_identity
            and file_identity(rec.stderr_path) == rec.stderr_identity
        )

    def _notify_restored_exit(self, rec: Any) -> None:
        try:
            from backend.services.background_notifications import (
                get_background_notification_queue,
            )

            get_background_notification_queue().push(
                shell_id=rec.shell_id,
                command=rec.command,
                exit_code=None,
            )
        except Exception:  # noqa: BLE001 — 通知失败不阻断恢复
            logger.exception("恢复时后台任务完成通知入队失败: %s", rec.shell_id)

    def shutdown(self, timeout_s: float = 1.0) -> None:
        """停止退出观察器线程（幂等）。"""
        self._watcher_stop.set()
        thread = self._watcher_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_s)
        self._watcher_thread = None

    def read_increment(self, shell_id: str, cap: int) -> Optional[Dict[str, Any]]:
        _validate_cap(cap)
        with self._lock:
            session = self._sessions.get(shell_id)
        if session is None:
            return None
        with session.operation_lock:
            payload = self._drain(session, cap)
        payload["shell_id"] = shell_id
        # 2026-11-06 Phase 2：回写读取偏移，重启恢复后不重复吐旧输出。
        store = self._get_store()
        if store is not None:
            try:
                store.update_offsets(
                    shell_id, session.stdout_offset, session.stderr_offset
                )
            except Exception:  # noqa: BLE001 — 偏移写回是增强信息
                logger.exception("后台 shell 偏移持久化失败: %s", shell_id)
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
            self._store_remove(shell_id)
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
        self.shutdown()
        with self._lock:
            self._retry_pending_cleanup()
            for shell_id in list(self._sessions):
                try:
                    self.terminate(shell_id, cap=1024)
                except Exception:
                    # 继续处理其余会话；失败项由 terminate 保留以便重试。
                    logger.warning("后台 shell 收尾失败: %s", shell_id)
            self._retry_pending_cleanup()
            self._exit_watches.clear()
            self._exited_seen.clear()

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


#: 进程级单例。惰性创建（首次 get_registry() 才读 bash_config，import 期
#: 不碰 DB —— 同 conftest "AST-only tests 不在收集期 import application" 约束）。
_REGISTRY: Optional[BashSessionRegistry] = None


def get_registry() -> BashSessionRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        # 函数内 import：bash_config 仅标准库，但保持与消费方同一注入时点
        from .bash_config import load_bash_config

        # 2026-11-06 Phase 3：两平台都接入 SQLite 持久化（Windows 恢复通过
        # tasklist 探测存活；延迟 import，避免 import 期触碰数据库）。
        from .bash_session_persistence import get_bash_session_store

        _REGISTRY = BashSessionRegistry(
            max_sessions=load_bash_config().max_sessions,
            store_getter=get_bash_session_store,
        )
        try:
            _REGISTRY.restore()
        except Exception:  # noqa: BLE001 — 恢复失败按纯内存模式继续
            logger.exception("后台 shell 重启恢复失败")
    return _REGISTRY


__all__ = [
    "MAX_BACKGROUND_SESSIONS", "STATUS_RUNNING", "STATUS_EXITED",
    "BashSession", "BashSessionRegistry", "SessionLimitExceeded", "get_registry",
]
