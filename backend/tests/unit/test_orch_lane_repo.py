"""双轨合并 Phase 1 (P0) — OrchLaneRepository / OrchLaneEventRepository 单元测试。

覆盖：
- 新 repo 的 CRUD / 查询方法与老 LaneRepository 的语义等价
- lane 事件 append / list_by_lane / list_by_task
- **数据迁移**：老表 orchestration_lanes / orchestration_lane_events 存量在
  init_db 时复制到新表（Phase 2），幂等且冲突保留新侧
"""

from __future__ import annotations

import json

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


def _seed_legacy_task(db, task_id: str = "t1") -> None:
    """老表 orchestration_lanes 有 FK 指向 orch_plan_tasks（Phase 3 改名） —— 插 lane 前
    必须先建 task 行（生产中由 Planner 写入）。"""
    conn = db.get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO orch_plan_tasks (task_id, name, created_at) "
        "VALUES (?, ?, ?)",
        (task_id, f"任务 {task_id}", 1700000000000),
    )
    conn.commit()


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


class TestLegacyMigration:
    """Phase 2 数据迁移：老表存量在 init_db 时复制到新表。"""

    def test_legacy_lanes_copied_to_new_table(self, tmp_path, monkeypatch):
        db = _fresh_db(tmp_path, monkeypatch, "migrate.db")
        _seed_legacy_task(db)

        # 模拟"历史数据只存在于老表"（升级前写入的行）。
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO orchestration_lanes "
            "(lane_id, task_id, agent_id, status, created_at, permission_preset, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "lane-legacy",
                "t1",
                "writer",
                "running",
                1700000000000,
                "implement",
                "{}",
            ),
        )
        conn.commit()

        # 重新 init → 迁移块执行。
        db2 = _reopen(tmp_path, monkeypatch, "migrate.db")

        row = (
            db2.get_connection()
            .execute(
                "SELECT lane_id, agent_id, status FROM orch_lanes WHERE lane_id = ?",
                ("lane-legacy",),
            )
            .fetchone()
        )
        assert row is not None
        assert row["agent_id"] == "writer"
        assert row["status"] == "running"

    def test_legacy_lane_events_copied(self, tmp_path, monkeypatch):
        db = _fresh_db(tmp_path, monkeypatch, "migrate_evt.db")
        _seed_legacy_task(db)
        conn = db.get_connection()
        # orchestration_lane_events 有 FK 指向 orchestration_lanes —— 先建 lane。
        conn.execute(
            "INSERT INTO orchestration_lanes "
            "(lane_id, task_id, status, created_at, permission_preset, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("lane-1", "t1", "created", 1700000000000, "implement", "{}"),
        )
        conn.execute(
            "INSERT INTO orchestration_lane_events "
            "(event_id, event_type, lane_id, task_id, agent_id, timestamp, provenance, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt-legacy",
                "lane.started",
                "lane-1",
                "t1",
                "writer",
                1700000000000,
                "LiveLane",
                json.dumps({"k": "v"}),
            ),
        )
        conn.commit()

        db2 = _reopen(tmp_path, monkeypatch, "migrate_evt.db")
        row = (
            db2.get_connection()
            .execute(
                "SELECT event_id, metadata FROM orch_lane_events WHERE event_id = ?",
                ("evt-legacy",),
            )
            .fetchone()
        )
        assert row is not None
        assert json.loads(row["metadata"]) == {"k": "v"}

    def test_migration_is_idempotent(self, tmp_path, monkeypatch):
        """重复 init 不产生重复行（INSERT OR IGNORE）。"""
        db = _fresh_db(tmp_path, monkeypatch, "idem.db")
        _seed_legacy_task(db)
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO orchestration_lanes "
            "(lane_id, task_id, status, created_at, permission_preset, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("lane-x", "t1", "created", 1700000000000, "implement", "{}"),
        )
        conn.commit()

        _reopen(tmp_path, monkeypatch, "idem.db")
        db3 = _reopen(tmp_path, monkeypatch, "idem.db")

        count = (
            db3.get_connection()
            .execute(
                "SELECT COUNT(*) AS n FROM orch_lanes WHERE lane_id = ?", ("lane-x",)
            )
            .fetchone()["n"]
        )
        assert count == 1

    def test_migration_preserves_newer_side_on_conflict(self, tmp_path, monkeypatch):
        """主键冲突时保留新表侧的值（INSERT OR IGNORE 语义）。"""
        db = _fresh_db(tmp_path, monkeypatch, "conflict.db")
        _seed_legacy_task(db)
        conn = db.get_connection()
        # 老表：agent_id=old；新表：agent_id=new（迁移前已写入）
        conn.execute(
            "INSERT INTO orchestration_lanes "
            "(lane_id, task_id, agent_id, status, created_at, permission_preset, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("lane-c", "t1", "old", "created", 1700000000000, "implement", "{}"),
        )
        conn.execute(
            "INSERT INTO orch_lanes "
            "(lane_id, task_id, agent_id, status, created_at, permission_preset, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("lane-c", "t1", "new", "running", 1700000000000, "implement", "{}"),
        )
        conn.commit()

        db2 = _reopen(tmp_path, monkeypatch, "conflict.db")
        row = (
            db2.get_connection()
            .execute(
                "SELECT agent_id, status FROM orch_lanes WHERE lane_id = ?",
                ("lane-c",),
            )
            .fetchone()
        )
        assert row["agent_id"] == "new"
        assert row["status"] == "running"

    def test_migration_noop_on_fresh_install(self, tmp_path, monkeypatch):
        """全新安装（老表为空）不报错、不产生数据。"""
        _fresh_db(tmp_path, monkeypatch, "fresh.db")
        db2 = _reopen(tmp_path, monkeypatch, "fresh.db")

        count = (
            db2.get_connection()
            .execute("SELECT COUNT(*) AS n FROM orch_lanes")
            .fetchone()["n"]
        )
        assert count == 0


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
