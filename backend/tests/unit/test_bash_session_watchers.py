"""``BashSessionRegistry`` 退出观察器单元测试（2026-11-06 Phase 1）。"""

from __future__ import annotations

import os
import sys
import time

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        os.name == "nt",
        reason="bash session 依赖 POSIX 进程组（start_verified_process 在 Windows 按设计拒绝）",
    ),
]

from backend.tools.bash_session import (  # noqa: E402
    STATUS_EXITED,
    BashSessionRegistry,
)
from backend.tools.subprocess_util import (  # noqa: E402
    make_temp_output_file,
    spawn_verified,
)


def _spawn(registry: BashSessionRegistry, code: str):
    stdout_path = make_temp_output_file(prefix="sage_test_")
    stderr_path = make_temp_output_file(prefix="sage_test_")
    out_handle = open(stdout_path, "wb")  # noqa: SIM115
    err_handle = open(stderr_path, "wb")  # noqa: SIM115
    try:
        verified = spawn_verified(
            [sys.executable, "-c", code], stdout=out_handle, stderr=err_handle
        )
    finally:
        out_handle.close()
        err_handle.close()
    return registry.register(
        verified, command=code, stdout_path=stdout_path, stderr_path=stderr_path
    )


class TestRegisterWatcher:
    def test_unknown_shell_returns_false(self) -> None:
        registry = BashSessionRegistry()
        try:
            assert registry.register_watcher("does-not-exist", lambda *a: None) is False
        finally:
            registry.shutdown()

    def test_already_exited_fires_immediately(self) -> None:
        registry = BashSessionRegistry()
        try:
            session = _spawn(registry, "pass")
            # 等待子进程结束
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and session.status() != STATUS_EXITED:
                time.sleep(0.05)
            assert session.status() == STATUS_EXITED

            calls: list = []
            assert (
                registry.register_watcher(
                    session.shell_id,
                    lambda sid, code: calls.append((sid, code)),
                )
                is True
            )
            assert len(calls) == 1
            assert calls[0][0] == session.shell_id
            assert calls[0][1] == 0
        finally:
            registry.clear()

    def test_running_shell_fires_on_exit(self) -> None:
        registry = BashSessionRegistry()
        try:
            _spawn(registry, "import time; time.sleep(0.3)")
            # 刚 spawn 的 shell 还在运行
            sessions = list(registry._sessions.values())
            assert len(sessions) == 1
            session = sessions[0]

            calls: list = []
            registry.register_watcher(
                session.shell_id, lambda sid, code: calls.append((sid, code))
            )
            # watcher 线程轮询 + 触发
            deadline = time.monotonic() + 10
            while not calls and time.monotonic() < deadline:
                time.sleep(0.1)
            assert len(calls) == 1
            assert calls[0][1] == 0
        finally:
            registry.clear()

    def test_callback_exception_does_not_break_watcher(self) -> None:
        registry = BashSessionRegistry()
        try:
            session = _spawn(registry, "pass")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and session.status() != STATUS_EXITED:
                time.sleep(0.05)

            calls: list = []

            def bad_callback(*a):  # noqa: ANN001
                raise RuntimeError("boom")

            # 第一次注册：立即触发异常回调
            registry.register_watcher(session.shell_id, bad_callback)
            # 第二次注册（不同回调）也应同步触发
            registry.register_watcher(
                session.shell_id, lambda sid, code: calls.append((sid, code))
            )
            assert len(calls) == 1
        finally:
            registry.clear()


class TestShutdown:
    def test_shutdown_is_idempotent(self) -> None:
        registry = BashSessionRegistry()
        registry.shutdown()
        registry.shutdown()

    def test_clear_stops_watcher(self) -> None:
        registry = BashSessionRegistry()
        session = _spawn(registry, "pass")
        registry.register_watcher(session.shell_id, lambda *a: None)
        thread = registry._watcher_thread
        assert thread is not None
        assert thread.is_alive()
        registry.clear()
        assert registry._watcher_thread is None or not registry._watcher_thread.is_alive()


class TestRegisterExitNotification:
    def test_pushes_to_background_notification_queue(self, monkeypatch) -> None:
        from backend.services import background_notifications as bn_mod

        fresh = bn_mod.BackgroundNotificationQueue()
        monkeypatch.setattr(bn_mod, "_global_queue", fresh)

        registry = BashSessionRegistry()
        try:
            session = _spawn(registry, "pass")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and session.status() != STATUS_EXITED:
                time.sleep(0.05)
            assert registry.register_exit_notification(session.shell_id, session_id="s-1") is True
            # 已退出 → 立即推入队列
            items = fresh.drain()
            assert len(items) == 1
            assert items[0]["shell_id"] == session.shell_id
            assert items[0]["status"] == "succeeded"
            assert items[0]["session_id"] == "s-1"
        finally:
            registry.clear()
