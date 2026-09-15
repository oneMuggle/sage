"""
进化任务单元测试 (WS-D: 晋升软删 + 进化日志落表)

覆盖:
- MemoryConsolidationTask 晋升后软删源 episodic 行 (is_valid=0) 且 semantic 有新行
- memories_evolution_log 写入 promote / importance_adjust / prune 记录
- 日志表写入失败时进化任务本身不受影响 (best-effort)

注: memories_evolution_log 真实列名 (PRAGMA table_info 确认):
    id, memory_type, memory_id, operation, before_content,
    after_content, reason, created_at
"""

import time
import uuid
from types import SimpleNamespace

from backend.memory.semantic import SemanticMemory
from backend.scheduler.evolution import (
    ImportanceReevaluationTask,
    MemoryConsolidationTask,
    MemoryPruningTask,
    _write_evolution_log,
)
from backend.tests.conftest import ensure_session

SECONDS_PER_DAY = 24 * 3600


def _now_s() -> int:
    """秒级时间戳 — evolution.py 各任务 WHERE 子句按秒比较 created_at"""
    return int(time.time())


def _insert_episodic(
    db,
    *,
    content="测试记忆内容",
    importance=5,
    access_count=0,
    memory_type="conversation",
    created_at=None,
    expires_at=None,
    session_id=None,
):
    """直接插入一条 episodic 记忆行，返回记忆 id"""
    memory_id = str(uuid.uuid4())
    created = created_at if created_at is not None else _now_s()
    db.get_connection().execute(
        """
        INSERT INTO memories_episodic
        (id, session_id, content, summary, memory_type, importance, source, tags,
         created_at, access_count, is_valid, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            memory_id,
            session_id,
            content,
            content[:50],
            memory_type,
            importance,
            "test",
            "[]",
            created,
            access_count,
            expires_at,
        ),
    )
    db.get_connection().commit()
    return memory_id


def _fetch_episodic(db, memory_id):
    row = (
        db.get_connection()
        .execute("SELECT * FROM memories_episodic WHERE id = ?", [memory_id])
        .fetchone()
    )
    return dict(row) if row else None


def _fetch_evolution_logs(db, operation=None):
    conn = db.get_connection()
    if operation:
        rows = conn.execute(
            "SELECT * FROM memories_evolution_log WHERE operation = ? ORDER BY created_at",
            [operation],
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM memories_evolution_log ORDER BY created_at"
        ).fetchall()
    return [dict(row) for row in rows]


class TestMemoryConsolidationSoftDelete:
    """晋升路径：episodic → semantic 后源行必须软删"""

    async def test_promote_soft_deletes_source_and_writes_semantic(self, setup_test_db):
        db = setup_test_db
        content = "用户喜欢火锅，每周都去吃"
        mid = _insert_episodic(db, content=content, importance=6, access_count=6)
        task = MemoryConsolidationTask(
            db=db, memory_manager=SimpleNamespace(semantic=SemanticMemory(db=db))
        )

        result = await task.run_async()

        assert result["promoted"] == 1
        # 源 episodic 行被软删
        source = _fetch_episodic(db, mid)
        assert source["is_valid"] == 0
        # semantic 表出现对应新行
        semantic_rows = db.get_connection().execute(
            "SELECT * FROM memories_semantic"
        ).fetchall()
        assert any(row["content"] == content for row in semantic_rows)

    async def test_promote_writes_evolution_log(self, setup_test_db):
        db = setup_test_db
        mid = _insert_episodic(db, content="用户正在学习 Rust 语言", access_count=5)
        task = MemoryConsolidationTask(
            db=db, memory_manager=SimpleNamespace(semantic=SemanticMemory(db=db))
        )

        await task.run_async()

        logs = _fetch_evolution_logs(db, operation="promote")
        assert len(logs) == 1
        log = logs[0]
        assert log["memory_type"] == "episodic"
        assert log["memory_id"] == mid
        # 新旧位置描述：episodic:<id> → semantic:<id>
        assert log["before_content"] == f"episodic:{mid}"
        assert log["after_content"].startswith("semantic:")
        assert log["reason"] == "memory_consolidation"
        # created_at 用毫秒（与 memories_episodic/memories_semantic 一致）
        assert log["created_at"] > _now_s() * 100

    async def test_duplicate_content_not_promoted_nor_soft_deleted(self, setup_test_db):
        db = setup_test_db
        semantic = SemanticMemory(db=db)
        content = "项目发布日期是下周五"
        semantic.save(content=content)
        mid = _insert_episodic(db, content=content, access_count=9)
        task = MemoryConsolidationTask(
            db=db, memory_manager=SimpleNamespace(semantic=semantic)
        )

        result = await task.run_async()

        assert result["promoted"] == 0
        # 已存在相似语义记忆时：不晋升、不软删、不写日志
        assert _fetch_episodic(db, mid)["is_valid"] == 1
        assert _fetch_evolution_logs(db, operation="promote") == []


class TestImportanceReevaluationLog:
    """importance 变更必须落 memories_evolution_log"""

    async def test_high_importance_decay_writes_log(self, setup_test_db):
        db = setup_test_db
        mid = _insert_episodic(
            db,
            content="陈旧的高重要性记忆",
            importance=8,
            access_count=1,
            created_at=_now_s() - 8 * SECONDS_PER_DAY,
        )
        task = ImportanceReevaluationTask(db=db)

        adjusted = await task.run_async()

        assert adjusted == 1
        assert _fetch_episodic(db, mid)["importance"] == 7
        logs = _fetch_evolution_logs(db, operation="importance_adjust")
        assert len(logs) == 1
        assert logs[0]["memory_type"] == "episodic"
        assert logs[0]["memory_id"] == mid
        assert logs[0]["before_content"] == "8"
        assert logs[0]["after_content"] == "7"
        assert logs[0]["reason"] == "importance_reevaluation"

    async def test_low_importance_boost_writes_log(self, setup_test_db):
        db = setup_test_db
        mid = _insert_episodic(
            db,
            content="频繁访问的低重要性记忆",
            importance=3,
            access_count=6,
            created_at=_now_s(),
        )
        task = ImportanceReevaluationTask(db=db)

        adjusted = await task.run_async()

        assert adjusted == 1
        assert _fetch_episodic(db, mid)["importance"] == 4
        logs = _fetch_evolution_logs(db, operation="importance_adjust")
        assert len(logs) == 1
        assert logs[0]["memory_id"] == mid
        assert logs[0]["before_content"] == "3"
        assert logs[0]["after_content"] == "4"


class TestMemoryPruningLog:
    """修剪按规则写汇总日志（不按条写）"""

    async def test_prune_writes_summary_logs_per_rule(self, setup_test_db):
        db = setup_test_db
        # §1.3a: FK enforcement — parent session row for "sess-orphan" must
        # exist before the episodic insert below.
        ensure_session(db, "sess-orphan")
        now = _now_s()
        old = now - 31 * SECONDS_PER_DAY
        # 规则一，已过期记忆
        _insert_episodic(db, content="过期记忆", importance=5, expires_at=now - 100)
        # 规则二，极低价值且从未访问且超过30天
        _insert_episodic(
            db, content="低价值记忆", importance=1, access_count=0, created_at=old
        )
        # 规则3: 孤儿记忆（关联会话但低重要性、长期未访问）
        _insert_episodic(
            db,
            content="孤儿记忆",
            importance=3,
            access_count=0,
            created_at=old,
            session_id="sess-orphan",
        )
        # 不应被删除：近期 + 正常重要性
        keep_id = _insert_episodic(db, content="近期正常记忆", importance=5, created_at=now)
        task = MemoryPruningTask(db=db)

        deleted = await task.run_async()

        assert deleted == 3
        assert _fetch_episodic(db, keep_id) is not None
        logs = _fetch_evolution_logs(db, operation="prune")
        by_reason = {log["reason"]: log for log in logs}
        assert set(by_reason) == {
            "memory_pruning:expired",
            "memory_pruning:low_value",
            "memory_pruning:orphaned",
        }
        # 每条汇总记录删除条数
        assert by_reason["memory_pruning:expired"]["before_content"] == "1"
        assert by_reason["memory_pruning:low_value"]["before_content"] == "1"
        assert by_reason["memory_pruning:orphaned"]["before_content"] == "1"
        # 批次汇总用合成 memory_id
        for log in logs:
            assert log["memory_id"].startswith("batch:")
            assert log["memory_type"] == "episodic"

    async def test_prune_no_deletions_writes_no_log(self, setup_test_db):
        db = setup_test_db
        _insert_episodic(db, content="健康记忆", importance=6, created_at=_now_s())
        task = MemoryPruningTask(db=db)

        deleted = await task.run_async()

        assert deleted == 0
        assert _fetch_evolution_logs(db, operation="prune") == []


class TestEvolutionLogBestEffort:
    """日志写入失败只 warning，不能让进化任务失败"""

    def test_write_evolution_log_swallows_errors(self):
        class _BrokenDb:
            def get_connection(self):
                raise RuntimeError("模拟 DB 故障")

        # 不应抛异常
        _write_evolution_log(
            _BrokenDb(), memory_type="episodic", memory_id="m1", operation="promote"
        )

    async def test_pruning_survives_log_table_failure(self, setup_test_db):
        db = setup_test_db
        _insert_episodic(db, content="过期记忆", expires_at=_now_s() - 100)
        # 模拟日志表损坏：重命名后 INSERT 必失败
        db.get_connection().execute(
            "ALTER TABLE memories_evolution_log RENAME TO memories_evolution_log_bak"
        )
        db.get_connection().commit()
        task = MemoryPruningTask(db=db)

        deleted = await task.run_async()

        assert deleted == 1

    async def test_consolidation_survives_log_table_failure(self, setup_test_db):
        db = setup_test_db
        mid = _insert_episodic(db, content="高频访问记忆", access_count=7)
        db.get_connection().execute(
            "ALTER TABLE memories_evolution_log RENAME TO memories_evolution_log_bak"
        )
        db.get_connection().commit()
        task = MemoryConsolidationTask(
            db=db, memory_manager=SimpleNamespace(semantic=SemanticMemory(db=db))
        )

        result = await task.run_async()

        # 日志失败不影响晋升与软删
        assert result["promoted"] == 1
        assert _fetch_episodic(db, mid)["is_valid"] == 0

    async def test_importance_reevaluation_survives_log_table_failure(self, setup_test_db):
        db = setup_test_db
        mid = _insert_episodic(
            db,
            content="陈旧的高重要性记忆",
            importance=9,
            access_count=0,
            created_at=_now_s() - 8 * SECONDS_PER_DAY,
        )
        db.get_connection().execute(
            "ALTER TABLE memories_evolution_log RENAME TO memories_evolution_log_bak"
        )
        db.get_connection().commit()
        task = ImportanceReevaluationTask(db=db)

        adjusted = await task.run_async()

        assert adjusted == 1
        assert _fetch_episodic(db, mid)["importance"] == 8
