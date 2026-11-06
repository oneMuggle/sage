"""``BashSessionRegistry.restore()`` 重启恢复测试（Phase 2，POSIX only）。"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from typing import List

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(os.name == "nt", reason="恢复逻辑仅 POSIX"),
]

from backend.tools.bash_session import (  # noqa: E402
    STATUS_EXITED,
    STATUS_RUNNING,
    BashSessionRegistry,
)
from backend.tools.bash_session_persistence import StoredSessionRecord  # noqa: E402
from backend.tools.subprocess_util import (  # noqa: E402
    file_identity,
    make_temp_output_file,
    spawn_verified,
)


class FakeStore:
    def __init__(self, records: List[StoredSessionRecord]) -> None:
        self.records = list(records)
        self.removed: List[str] = []
        self.offsets: List[tuple] = []

    def list_all(self) -> List[StoredSessionRecord]:
        return list(self.records)

    def remove(self, shell_id: str) -> None:
        self.removed.append(shell_id)
        self.records = [r for r in self.records if r.shell_id != shell_id]

    def update_offsets(self, shell_id: str, out: int, err: int) -> None:
        self.offsets.append((shell_id, out, err))

    def persist(self, session) -> None:  # noqa: ANN001
        pass


@pytest.fixture()
def fresh_queue(monkeypatch):
    from backend.services import background_notifications as bn

    queue = bn.BackgroundNotificationQueue()
    monkeypatch.setattr(bn, "_global_queue", queue)
    return queue


def _spawn_live(seconds: int = 60):
    stdout_path = make_temp_output_file(prefix="sage_restore_")
    stderr_path = make_temp_output_file(prefix="sage_restore_")
    out = open(stdout_path, "wb")  # noqa: SIM115
    err = open(stderr_path, "wb")  # noqa: SIM115
    try:
        verified = spawn_verified(
            [sys.executable, "-c", f"import time; time.sleep({seconds})"],
            stdout=out,
            stderr=err,
        )
    finally:
        out.close()
        err.close()
    return verified, stdout_path, stderr_path


def _kill(verified) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(verified.process_group_id, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        verified.process.wait(timeout=5)


def _record(shell_id, verified, stdout_path, stderr_path, *, pgid_offset=0, identity=None):
    return StoredSessionRecord(
        shell_id=shell_id,
        pid=verified.process.pid,
        pgid=verified.process_group_id + pgid_offset,
        command="sleep 60",
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stdout_identity=identity if identity is not None else file_identity(stdout_path),
        stderr_identity=identity if identity is not None else file_identity(stderr_path),
        stdout_offset=0,
        stderr_offset=0,
        started_at=int(time.time()),
    )


class TestRestore:
    def test_alive_shell_is_resurrected(self, fresh_queue) -> None:
        verified, stdout_path, stderr_path = _spawn_live()
        store = FakeStore([_record("sh-alive", verified, stdout_path, stderr_path)])
        registry = BashSessionRegistry(store_getter=lambda: store)
        try:
            assert registry.restore() == 1
            session = registry.get("sh-alive")
            assert session is not None
            assert session.status() == STATUS_RUNNING
            assert store.removed == []
        finally:
            _kill(verified)
            registry._poll_watches()
            assert "sh-alive" in store.removed
            assert registry.get("sh-alive") is not None
            registry.clear()

    def test_dead_shell_is_removed_and_notified(self, fresh_queue) -> None:
        verified, stdout_path, stderr_path = _spawn_live(seconds=0)
        verified.process.wait(timeout=5)
        store = FakeStore([_record("sh-dead", verified, stdout_path, stderr_path)])
        registry = BashSessionRegistry(store_getter=lambda: store)
        assert registry.restore() == 0
        assert store.removed == ["sh-dead"]
        items = fresh_queue.drain()
        assert len(items) == 1
        assert items[0]["shell_id"] == "sh-dead"
        registry.shutdown()

    def test_identity_mismatch_abandons_restore(self, fresh_queue) -> None:
        verified, stdout_path, stderr_path = _spawn_live()
        store = FakeStore(
            [_record("sh-mismatch", verified, stdout_path, stderr_path, identity=(0, 0))]
        )
        registry = BashSessionRegistry(store_getter=lambda: store)
        try:
            assert registry.restore() == 0
            assert store.removed == ["sh-mismatch"]
            assert len(fresh_queue.drain()) == 1
        finally:
            _kill(verified)
            registry.shutdown()

    def test_pgid_mismatch_treated_as_exited(self, fresh_queue) -> None:
        verified, stdout_path, stderr_path = _spawn_live()
        store = FakeStore(
            [_record("sh-recycled", verified, stdout_path, stderr_path, pgid_offset=1)]
        )
        registry = BashSessionRegistry(store_getter=lambda: store)
        try:
            assert registry.restore() == 0
            assert store.removed == ["sh-recycled"]
        finally:
            _kill(verified)
            registry.shutdown()

    def test_no_store_is_noop(self) -> None:
        registry = BashSessionRegistry()
        assert registry.restore() == 0
        registry.shutdown()

    def test_exited_status_after_kill_reported(self, fresh_queue) -> None:
        verified, stdout_path, stderr_path = _spawn_live()
        store = FakeStore([_record("sh-killed", verified, stdout_path, stderr_path)])
        registry = BashSessionRegistry(store_getter=lambda: store)
        try:
            assert registry.restore() == 1
            _kill(verified)
            session = registry.get("sh-killed")
            assert session is not None
            assert session.status() == STATUS_EXITED
        finally:
            registry.clear()
