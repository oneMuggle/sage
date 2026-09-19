"""双轨合并 Phase 1 (P0) — OrchLaneRepository / OrchLaneEventRepository 单元测试。

覆盖：
- 新 repo 的 CRUD / 查询方法与老 LaneRepository 的语义等价
- lane 事件 append / list_by_lane / list_by_task
- Phase 3/5 后：老 lane 表已删除，本套走新表 orch_lanes / orch_lane_events
"""

from __future__ import annotations

import pytest

from backend.data import database as db_mod
from backend.orchestration.models import Lane, LaneHeartbeat, LaneStatus


def _fresh_db(tmp_path, monkeypatch, name: str = "test.db"):
    """建一个新的 tmp DB 并返回已 init 的 Database 实例。"""
    db_path = tmp_path / name
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return db


def _reopen(tmp_path, monkeypatch, name: str = "test.db"):
    """重置单例并重新 init（触发迁移块）。"""
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    return _fresh_db(tmp_path, monkeypatch)


def _repo():
    from backend.data.orch_lane_repo import OrchLaneRepository

    return OrchLaneRepository()


class TestOrchLaneRepository:
    def test_create_and_get(self, db):
        repo = _repo()
        lane = Lane(lane_id="lane-1", task_id="t1", agent_id="writer")
        repo.create(lane)

        got = repo.get("lane-1")
        assert got is not None
        assert got.lane_id == "lane-1"
        assert got.task_id == "t1"
        assert got.agent_id == "writer"
        assert got.status == LaneStatus.CREATED
        assert got.permission_preset == "implement"

    def test_get_missing_returns_none(self, db):
        assert _repo().get("nope") is None

    def test_create_is_idempotent_upsert(self, db):
        """确定性 ID（如 lane-review-{run_id}）可安全重复 create。"""
        repo = _repo()
        repo.create(Lane(lane_id="lane-review-r1", task_id="t1", agent_id="a"))
        repo.create(Lane(lane_id="lane-review-r1", task_id="t1", agent_id="b"))

        rows = repo.list_all()
        assert len(rows) == 1
        assert rows[0].agent_id == "b"

    def test_update_changes_fields(self, db):
        repo = _repo()
        lane = Lane(lane_id="lane-1", task_id="t1", agent_id="writer")
        repo.create(lane)

        lane.status = LaneStatus.RUNNING
        lane.started_at = 1700000000000
        lane.metadata = {"source": "planner"}
        assert repo.update(lane) is True

        got = repo.get("lane-1")
        assert got.status == LaneStatus.RUNNING
        assert got.started_at == 1700000000000
        assert got.metadata == {"source": "planner"}

    def test_update_missing_returns_false(self, db):
        assert _repo().update(Lane(lane_id="nope", task_id="t1")) is False

    def test_delete(self, db):
        repo = _repo()
        repo.create(Lane(lane_id="lane-1", task_id="t1"))
        assert repo.delete("lane-1") is True
        assert repo.get("lane-1") is None
        assert repo.delete("lane-1") is False

    def test_list_by_task(self, db):
        repo = _repo()
        repo.create(Lane(lane_id="lane-1", task_id="t1"))
        repo.create(Lane(lane_id="lane-2", task_id="t1"))
        repo.create(Lane(lane_id="lane-3", task_id="t2"))

        assert {lane.lane_id for lane in repo.list_by_task("t1")} == {
            "lane-1",
            "lane-2",
        }
        assert {lane.lane_id for lane in repo.list_by_task("t2")} == {"lane-3"}

    def test_list_by_status(self, db):
        repo = _repo()
        repo.create(Lane(lane_id="lane-1", task_id="t1", status=LaneStatus.RUNNING))
        repo.create(Lane(lane_id="lane-2", task_id="t1", status=LaneStatus.CREATED))

        running = repo.list_by_status(LaneStatus.RUNNING)
        assert [lane.lane_id for lane in running] == ["lane-1"]

    def test_list_by_agent(self, db):
        repo = _repo()
        repo.create(Lane(lane_id="lane-1", task_id="t1", agent_id="writer"))
        repo.create(Lane(lane_id="lane-2", task_id="t2", agent_id="researcher"))

        assert [lane.lane_id for lane in repo.list_by_agent("writer")] == ["lane-1"]

    def test_update_heartbeat(self, db):
        repo = _repo()
        repo.create(Lane(lane_id="lane-1", task_id="t1"))

        hb = LaneHeartbeat(last_ping_at=1700000000000)
        assert repo.update_heartbeat("lane-1", hb) is True

        got = repo.get("lane-1")
        assert got.heartbeat is not None
        assert got.heartbeat.last_ping_at == 1700000000000

    def test_worktree_and_permission_preset_roundtrip(self, db):
        """lane 独有字段（老表存在、orch_tasks 没有）必须完整往返。"""
        repo = _repo()
        repo.create(
            Lane(
                lane_id="lane-1",
                task_id="t1",
                worktree="/tmp/wt-1",
                permission_preset="audit",
            )
        )
        got = repo.get("lane-1")
        assert got.worktree == "/tmp/wt-1"
        assert got.permission_preset == "audit"


class TestOrchLaneEventRepository:
    def _event_repo(self):
        from backend.data.orch_lane_repo import OrchLaneEventRepository

        return OrchLaneEventRepository()

    def test_append_and_list_by_lane(self, db):
        repo = self._event_repo()
        event_id = repo.append("lane.started", "lane-1", "t1", agent_id="writer")
        assert event_id.startswith("evt-")

        events = repo.list_by_lane("lane-1")
        assert len(events) == 1
        assert events[0]["event_type"] == "lane.started"
        assert events[0]["agent_id"] == "writer"
        assert events[0]["provenance"] == "LiveLane"

    def test_list_by_task_across_lanes(self, db):
        repo = self._event_repo()
        repo.append("lane.started", "lane-1", "t1")
        repo.append("lane.started", "lane-2", "t1")
        repo.append("lane.started", "lane-3", "t2")

        assert len(repo.list_by_task("t1")) == 2
        assert len(repo.list_by_task("t2")) == 1

    def test_metadata_roundtrip(self, db):
        repo = self._event_repo()
        repo.append("lane.failed", "lane-1", "t1", metadata={"reason": "timeout"})

        events = repo.list_by_lane("lane-1")
        assert events[0]["metadata"] == {"reason": "timeout"}


class TestLegacyTableRename:
    """Phase 3：orchestration_tasks / orchestration_teams 改名消除命名混淆，
    并解除 idx_orch_tasks_status 与 orch_tasks 同名索引的冲突。"""

    def test_legacy_plan_tasks_renamed(self, tmp_path, monkeypatch):
        db = _fresh_db(tmp_path, monkeypatch, "rename.db")
        conn = db.get_connection()
        # 删掉 init_db 建的新表，让 migration 块认为"旧版 DB"。
        conn.execute("DROP TABLE IF EXISTS orch_plan_tasks")
        # 释放老索引名（init_db 已在 orch_tasks 上建了 idx_orch_tasks_status）。
        conn.execute("DROP INDEX IF EXISTS idx_orch_tasks_status")
        # 建老表 + 老索引（模拟旧版部署；含 status/team_id 列以支持索引）。
        conn.execute(
            "CREATE TABLE orchestration_tasks "
            "(task_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at INTEGER NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'created', team_id TEXT)"
        )
        conn.execute(
            "INSERT INTO orchestration_tasks VALUES (?, ?, ?, ?, ?)",
            ("t-old", "老任务", 1700000000000, "created", None),
        )
        conn.execute("CREATE INDEX idx_orch_tasks_status ON orchestration_tasks(status)")
        conn.commit()

        db2 = _reopen(tmp_path, monkeypatch, "rename.db")
        conn2 = db2.get_connection()

        tables = {
            r["name"]
            for r in conn2.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "orch_plan_tasks" in tables
        assert "orchestration_tasks" not in tables

        row = conn2.execute(
            "SELECT name FROM orch_plan_tasks WHERE task_id = ?", ("t-old",)
        ).fetchone()
        assert row["name"] == "老任务"

    def test_index_name_conflict_resolved(self, tmp_path, monkeypatch):
        """改名后 idx_orch_tasks_status 归属 orch_tasks（此前被老表占用而缺失）。"""
        db = _fresh_db(tmp_path, monkeypatch, "idxfix.db")
        conn = db.get_connection()
        conn.execute("DROP TABLE IF EXISTS orch_plan_tasks")
        conn.execute("DROP INDEX IF EXISTS idx_orch_tasks_status")
        conn.execute(
            "CREATE TABLE orchestration_tasks "
            "(task_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at INTEGER NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'created', team_id TEXT)"
        )
        conn.execute("CREATE INDEX idx_orch_tasks_status ON orchestration_tasks(status)")
        conn.commit()

        db2 = _reopen(tmp_path, monkeypatch, "idxfix.db")
        owner = (
            db2.get_connection()
            .execute(
                "SELECT tbl_name FROM sqlite_master "
                "WHERE type='index' AND name='idx_orch_tasks_status'"
            )
            .fetchone()
        )
        assert owner is not None
        assert owner["tbl_name"] == "orch_tasks"

    def test_legacy_teams_renamed(self, tmp_path, monkeypatch):
        db = _fresh_db(tmp_path, monkeypatch, "renameteam.db")
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO orch_plan_teams (team_id, name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("team-old", "老团队", 1700000000000, 1700000000000),
        )
        conn.execute("ALTER TABLE orch_plan_teams RENAME TO orchestration_teams")
        conn.commit()

        db2 = _reopen(tmp_path, monkeypatch, "renameteam.db")
        conn2 = db2.get_connection()
        tables = {
            r["name"]
            for r in conn2.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "orch_plan_teams" in tables
        assert "orchestration_teams" not in tables
        row = conn2.execute(
            "SELECT name FROM orch_plan_teams WHERE team_id = ?", ("team-old",)
        ).fetchone()
        assert row["name"] == "老团队"

class TestLegacyLaneMigration:
    """Phase 1/5：老表存量在 init_db 时复制到新表（老表无 DDL，仅旧库存在）。"""

    def test_legacy_lanes_copied_on_init(self, tmp_path, monkeypatch):
        db = _fresh_db(tmp_path, monkeypatch, "lanemig.db")
        conn = db.get_connection()
        # 手工重建老表（Phase 5 已移除其 DDL，仅模拟旧库残留）。
        conn.execute(
            "CREATE TABLE orchestration_lanes ("
            "lane_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, agent_id TEXT, "
            "status TEXT NOT NULL DEFAULT 'created', created_at INTEGER NOT NULL, "
            "started_at INTEGER, completed_at INTEGER, worktree TEXT, "
            "heartbeat TEXT, error TEXT, "
            "permission_preset TEXT NOT NULL DEFAULT 'implement', "
            "metadata TEXT NOT NULL DEFAULT '{}')"
        )
        conn.execute(
            "INSERT INTO orchestration_lanes "
            "(lane_id, task_id, agent_id, status, created_at, permission_preset, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("lane-legacy", "t1", "writer", "running", 1700000000000, "implement", "{}"),
        )
        conn.commit()

        db2 = _reopen(tmp_path, monkeypatch, "lanemig.db")
        row = (
            db2.get_connection()
            .execute(
                "SELECT agent_id, status FROM orch_lanes WHERE lane_id = ?",
                ("lane-legacy",),
            )
            .fetchone()
        )
        assert row is not None
        assert row["agent_id"] == "writer"
        assert row["status"] == "running"

    def test_missing_legacy_table_is_fail_open(self, tmp_path, monkeypatch):
        """全新安装无老表 → 迁移静默跳过，不阻塞 init_db。"""
        _fresh_db(tmp_path, monkeypatch, "nolegacy.db")
        db2 = _reopen(tmp_path, monkeypatch, "nolegacy.db")
        count = (
            db2.get_connection()
            .execute("SELECT COUNT(*) AS n FROM orch_lanes")
            .fetchone()["n"]
        )
        assert count == 0
