"""A4 留存/清扫 — ChatDispatcher retention unit tests.

_retain_worktree_for_acceptance 与 _sweep_stale_worktrees 的 A4 语义：
- 成功 lane 留存 worktree + 打 acceptance_pending 标记；
- 标记失败回落清理（防孤儿）；
- 本 run 清扫跳过留存目录；其他 run 只清过期目录。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from backend.orchestration.chat_dispatcher import (
    WORKTREES_ROOT,
    ChatDispatcher,
    ChatTaskState,
)


class DictLaneRegistry:
    def __init__(self, fail_update: bool = False, fail_get: bool = False):
        self.lanes = {}
        self.fail_update = fail_update
        self.fail_get = fail_get

    def get_lane(self, lane_id):
        if self.fail_get:
            raise RuntimeError("db down")
        return self.lanes.get(lane_id)

    def update_lane(self, lane):
        if self.fail_update:
            return False
        self.lanes[lane.lane_id] = lane
        return True


def _dispatcher(**attrs):
    d = ChatDispatcher.__new__(ChatDispatcher)
    d.run_id = "run1"
    d.workspace_root = None
    d.lane_registry = DictLaneRegistry()
    d._worktree_dirs = []
    for k, v in attrs.items():
        setattr(d, k, v)
    return d


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True,
        text=True, timeout=60, check=True,
    )


def _make_lane(lane_id: str, **meta):
    return SimpleNamespace(lane_id=lane_id, metadata=dict(meta))


class TestRetain:
    def test_marks_pending_and_keeps_dir(self, tmp_path):
        d = _dispatcher()
        d.lane_registry.lanes["lane-t1"] = _make_lane("lane-t1")
        wt = tmp_path / "wt"
        wt.mkdir()
        state = ChatTaskState(task_id="t1", agent_id="coder", goal="g")
        asyncio.run(d._retain_worktree_for_acceptance(state, wt))
        lane = d.lane_registry.lanes["lane-t1"]
        assert lane.metadata["acceptance_pending"] is True
        assert lane.metadata["acceptance_retained_at"] > 0
        assert wt.exists()

    def test_missing_lane_falls_back_to_remove(self, tmp_path):
        d = _dispatcher()
        main = tmp_path / "main"
        main.mkdir()
        _git("init", cwd=main)
        _git("config", "user.email", "t@t", cwd=main)
        _git("config", "user.name", "t", cwd=main)
        (main / "a.txt").write_text("v1\n", encoding="utf-8")
        _git("add", ".", cwd=main)
        _git("commit", "-m", "init", cwd=main)
        wt = tmp_path / "wt"
        (tmp_path).mkdir(exist_ok=True)
        _git("worktree", "add", "--detach", str(wt), "HEAD", cwd=main)
        state = ChatTaskState(task_id="t9", agent_id="coder", goal="g")
        asyncio.run(d._retain_worktree_for_acceptance(state, wt))
        assert not wt.exists()  # lane 缺失 → 回落清理

    def test_update_failure_falls_back_to_remove(self, tmp_path):
        d = _dispatcher(lane_registry=DictLaneRegistry(fail_update=True))
        d.lane_registry.lanes["lane-t1"] = _make_lane("lane-t1")
        main = tmp_path / "main"
        main.mkdir()
        _git("init", cwd=main)
        _git("config", "user.email", "t@t", cwd=main)
        _git("config", "user.name", "t", cwd=main)
        (main / "a.txt").write_text("v1\n", encoding="utf-8")
        _git("add", ".", cwd=main)
        _git("commit", "-m", "init", cwd=main)
        wt = tmp_path / "wt"
        _git("worktree", "add", "--detach", str(wt), "HEAD", cwd=main)
        state = ChatTaskState(task_id="t1", agent_id="coder", goal="g")
        asyncio.run(d._retain_worktree_for_acceptance(state, wt))
        assert not wt.exists()  # update 失败 → 回落清理


class TestSweep:
    def _db(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "backend.orchestration.chat_dispatcher.get_database",
            lambda: SimpleNamespace(db_path=str(tmp_path / "db.sqlite")),
        )
        return tmp_path / WORKTREES_ROOT

    def test_own_run_skips_pending(self, monkeypatch, tmp_path):
        root = self._db(monkeypatch, tmp_path)
        stale = root / "run1" / "t1"
        stale.mkdir(parents=True)
        pending = root / "run1" / "t2"
        pending.mkdir(parents=True)
        d = _dispatcher()
        d.lane_registry.lanes["lane-t2"] = _make_lane(
            "lane-t2", acceptance_pending=True
        )
        d._sweep_stale_worktrees()
        assert not stale.exists()
        assert pending.exists()  # 留存目录受保护
        assert (root / "run1").exists()  # 非空 run 根保留

    def test_own_run_all_stale_removes_root(self, monkeypatch, tmp_path):
        root = self._db(monkeypatch, tmp_path)
        (root / "run1" / "t1").mkdir(parents=True)
        d = _dispatcher()
        d._sweep_stale_worktrees()
        assert not (root / "run1").exists()

    def test_expired_other_run_swept(self, monkeypatch, tmp_path):
        root = self._db(monkeypatch, tmp_path)
        old = root / "runOld" / "t1"
        old.mkdir(parents=True)
        old_ts = time.time() - 8 * 86400
        os.utime(root / "runOld", (old_ts, old_ts))
        fresh = root / "runFresh" / "t1"
        fresh.mkdir(parents=True)
        d = _dispatcher()
        d._sweep_stale_worktrees()
        assert not (root / "runOld").exists()
        assert fresh.exists()  # 新鲜他 run 目录不动

    def test_registry_failure_fails_open(self, monkeypatch, tmp_path):
        root = self._db(monkeypatch, tmp_path)
        stale = root / "run1" / "t1"
        stale.mkdir(parents=True)
        d = _dispatcher(lane_registry=DictLaneRegistry(fail_get=True))
        d._sweep_stale_worktrees()
        assert not stale.exists()  # 查询失败 → 照清（旧行为）
