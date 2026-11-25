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

import logging
import time
import uuid
from types import SimpleNamespace

import backend.scheduler.evolution as evolution_module
from backend.memory.semantic import SemanticMemory
from backend.scheduler.evolution import (
    DailySummaryTask,
    ImportanceReevaluationTask,
    MemoryConsolidationTask,
    MemoryPruningTask,
    _write_evolution_log,
)
from backend.tests.conftest import ensure_session

MS_PER_DAY = 24 * 3600 * 1000


def _now_ms() -> int:
    """生产同款毫秒时间戳 — evolution.py 各任务 WHERE 子句按毫秒比较。"""
    return int(time.time() * 1000)


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
    created = created_at if created_at is not None else _now_ms()
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
        assert log["created_at"] > 1_000_000_000_000

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
            created_at=_now_ms() - 8 * MS_PER_DAY,
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
            created_at=_now_ms(),
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
        now = _now_ms()
        old = now - 31 * MS_PER_DAY
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
        _insert_episodic(db, content="健康记忆", importance=6, created_at=_now_ms())
        task = MemoryPruningTask(db=db)

        deleted = await task.run_async()

        assert deleted == 0
        assert _fetch_evolution_logs(db, operation="prune") == []

    async def test_quality_merge_drops_duplicates_keeps_leader(
        self, setup_test_db
    ):
        """三份近重复记忆只删冗余副本，组长受保护"""
        db = setup_test_db
        # 120 天 → recency = 0.5^(120/60) = 0.25
        # quality = 0.25*1.0 + 0.25*0.3 + 0.20*0.25 + 0 + 0 = 0.375 < 0.4 ✓
        old = _now_ms() - 120 * MS_PER_DAY
        same_content = "这是一条低质但重要性偏高的记忆内容，专门用来测试近重复"
        # 三份一模一样、importance 中等、无 session → 不会被规则 2/3 删
        ids = [
            _insert_episodic(
                db,
                content=same_content,
                importance=3,
                access_count=0,
                created_at=old,
            )
            for _ in range(3)
        ]

        deleted = await MemoryPruningTask(db=db).run_async()

        # 两份副本被质量合并软删除（is_valid=0），组长保留（仍有效）
        remaining_valid = [
            mid for mid in ids if _fetch_episodic(db, mid)["is_valid"] == 1
        ]
        assert len(remaining_valid) == 1
        leader_id = remaining_valid[0]
        # 质量合并按条写审计日志
        quality_logs = [
            log
            for log in _fetch_evolution_logs(db, operation="prune")
            if log["reason"] == "memory_pruning:quality_merge"
        ]
        assert len(quality_logs) == 2
        # 组长不出现在 quality_merge 日志里
        assert leader_id not in {log["memory_id"] for log in quality_logs}
        assert deleted == 2
        # 与其它失效路径同口径：副本既置 is_valid=0 也写 invalid_at
        for mid in ids:
            if mid == leader_id:
                assert _fetch_episodic(db, mid)["invalid_at"] is None
            else:
                assert _fetch_episodic(db, mid)["invalid_at"] is not None

    async def test_quality_prune_never_wipes_whole_duplicate_group(
        self, setup_test_db
    ):
        """近重复组必须留下至少一条 —— 不能整组消失。

        质量合并有单次上限（``_PRUNE_QUALITY_DELETE_MAX``），超出后副本没
        删完。此时若组长也走"低质量软失效"被废掉，整组内容就从检索里
        消失 —— 组的大小成了决定内容生死的因素，而非内容本身的质量：
        三份一样的低质记忆会留下组长一份，一百二十份却一条不剩。
        """
        db = setup_test_db
        # 120 天 → recency = 0.5^(120/60) = 0.25
        # quality = 0.25*1.0 + 0.25*0.3 + 0.20*0.25 + 0 + 0 = 0.375 < 0.4 ✓
        old = _now_ms() - 120 * MS_PER_DAY
        same_content = "这是一条低质但重要性偏高的记忆内容，专门用来测试近重复"
        # 条数超过质量合并的单次上限（100），确保副本没被删完
        ids = [
            _insert_episodic(
                db,
                content=same_content,
                importance=3,
                access_count=0,
                created_at=old,
            )
            for _ in range(120)
        ]

        await MemoryPruningTask(db=db).run_async()

        remaining_valid = [
            mid for mid in ids if _fetch_episodic(db, mid)["is_valid"] == 1
        ]
        assert remaining_valid, "整组近重复被清空，内容从检索中消失"


class TestSoleValidGroupMembers:
    """组内"有效"判定必须与全局同口径：is_valid=1 且 invalid_at IS NULL。"""

    def test_row_with_invalid_at_is_not_counted_as_valid(self, setup_test_db):
        db = setup_test_db
        leader_id = _insert_episodic(db, content="组长记忆")
        dup_id = _insert_episodic(db, content="副本记忆")
        # 副本仍是 is_valid=1，但已带失效时间 —— 语义上已无效，不应被
        # 当作"组内另一条有效成员"来证明组长不孤单。
        db.get_connection().execute(
            "UPDATE memories_episodic SET invalid_at = ? WHERE id = ?",
            (_now_ms(), dup_id),
        )
        db.get_connection().commit()
        leaders = {leader_id: leader_id, dup_id: leader_id}

        sole = MemoryPruningTask(db=db)._sole_valid_group_members(leaders)

        assert sole == {leader_id}


class TestPruneScanWindow:
    """近重复分组窗口必须随 max_memories 放大，且超窗时告警。"""

    def test_scan_limit_scales_with_max_memories(self, setup_test_db):
        db = setup_test_db
        floor = evolution_module._PRUNE_SCAN_MIN_ROWS
        # 默认 max_memories=1000 → 窗口取 floor（2000），留两倍余量
        assert MemoryPruningTask(db=db)._scan_limit() == floor
        # max_memories 放大后窗口至少是其两倍，保证保留的记忆都在窗口内
        big = MemoryPruningTask(db=db, config={"max_memories": floor})
        assert big._scan_limit() >= 2 * floor

    def test_load_prunable_rows_warns_when_exceeding_window(
        self, setup_test_db, monkeypatch, caplog
    ):
        db = setup_test_db
        # 窗口 = max(下限, 2*max_memories) → 3；插入 5 条，只应取最新 3 条
        monkeypatch.setattr(evolution_module, "_PRUNE_SCAN_MIN_ROWS", 3)
        task = MemoryPruningTask(db=db, config={"max_memories": 1})
        base = _now_ms() - 10 * MS_PER_DAY
        ids = [
            _insert_episodic(db, content=f"窗口测试记忆{i}", created_at=base + i * 1000)
            for i in range(5)
        ]

        with caplog.at_level(logging.WARNING):
            rows = task._load_prunable_rows()

        assert len(rows) == 3
        # 最新在前：created_at 最大的三条
        assert [r["id"] for r in rows] == [ids[4], ids[3], ids[2]]
        assert any(
            r.levelno == logging.WARNING and "扫描窗口" in r.getMessage()
            for r in caplog.records
        )


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
        _insert_episodic(db, content="过期记忆", expires_at=_now_ms() - 100)
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
            created_at=_now_ms() - 8 * MS_PER_DAY,
        )
        db.get_connection().execute(
            "ALTER TABLE memories_evolution_log RENAME TO memories_evolution_log_bak"
        )
        db.get_connection().commit()
        task = ImportanceReevaluationTask(db=db)

        adjusted = await task.run_async()

        assert adjusted == 1
        assert _fetch_episodic(db, mid)["importance"] == 8


class _FakeLLM:
    """Test LLM stub."""

    async def complete(self, prompt: str) -> str:
        return "测试摘要：对话讨论了记忆系统"


class TestDailySummaryMilliseconds:
    """每日摘要按毫秒窗口筛选"今天有活动"的会话。"""

    async def test_summarizes_session_active_today_and_dedupes_same_day(
        self, setup_test_db
    ):
        db = setup_test_db
        now = _now_ms()
        session_id = "sess-daily"
        conn = db.get_connection()
        conn.execute(
            """
            INSERT INTO sessions
            (id, title, created_at, updated_at, last_message_at, message_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, "今日会话", now - 2 * MS_PER_DAY, now, now, 3),
        )
        messages = [
            ("msg-1", "user", "我想聊聊记忆系统"),
            ("msg-2", "assistant", "好的，我们开始"),
            ("msg-3", "user", "请继续"),
        ]
        for idx, (message_id, role, content) in enumerate(messages):
            conn.execute(
                """
                INSERT INTO messages (id, session_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, now - 1000 + idx),
            )
        conn.commit()

        task = DailySummaryTask(db=db, llm_client=_FakeLLM())
        processed = await task.run_async()

        assert processed == 1
        row = conn.execute(
            """
            SELECT memory_type, importance FROM memories_episodic
            WHERE session_id = ?
            """,
            [session_id],
        ).fetchone()
        assert row is not None
        assert row["memory_type"] == "daily_summary"
        assert row["importance"] == 6

        # 同一会话当天重复执行（启动补跑/重启）不再生成第二条摘要
        assert await task.run_async() == 0

    async def test_daily_summary_skips_when_llm_unavailable(self, setup_test_db):
        """LLM 不可用时每日摘要跳过，不写关键词兜底摘要。"""
        db = setup_test_db
        now = _now_ms()
        session_id = "sess-no-llm"
        conn = db.get_connection()
        conn.execute(
            """
            INSERT INTO sessions
            (id, title, created_at, updated_at, last_message_at, message_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, "无 LLM 会话", now - 2 * MS_PER_DAY, now, now, 3),
        )
        for idx, (role, content) in enumerate(
            [("user", "消息1"), ("assistant", "消息2"), ("user", "消息3")]
        ):
            conn.execute(
                """
                INSERT INTO messages (id, session_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (f"m-{idx}", session_id, role, content, now - 1000 + idx),
            )
        conn.commit()

        # 不传 llm_client → _resolve_llm() 返回 None
        processed = await DailySummaryTask(db=db).run_async()

        assert processed == 0
        # 不写兜底摘要
        row = conn.execute(
            "SELECT 1 FROM memories_episodic WHERE session_id = ?",
            [session_id],
        ).fetchone()
        assert row is None
        # 任务级进化日志标 skipped_no_llm
        log_row = conn.execute(
            "SELECT status FROM evolution_log WHERE evolution_type = 'daily_summary'"
            " ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert log_row is not None
        assert log_row["status"] == "skipped_no_llm"


class TestMemoryConsolidationDecayMilliseconds:
    """固化任务的 30 天衰减必须使用毫秒时间戳。"""

    async def test_decays_stale_memory_with_millisecond_created_at(self, setup_test_db):
        db = setup_test_db
        old = _now_ms() - 40 * MS_PER_DAY
        mid = _insert_episodic(
            db,
            content="四十天前的重要记忆",
            importance=6,
            access_count=0,
            created_at=old,
        )
        task = MemoryConsolidationTask(
            db=db, memory_manager=SimpleNamespace(semantic=SemanticMemory(db=db))
        )

        result = await task.run_async()

        assert result["decayed"] >= 1
        assert _fetch_episodic(db, mid)["importance"] == 5

    async def test_environment_memory_is_not_decayed(self, setup_test_db):
        db = setup_test_db
        old = _now_ms() - 40 * MS_PER_DAY
        mid = _insert_episodic(
            db,
            content="PowerShell 5.1 不支持三元运算符",
            importance=6,
            created_at=old,
        )
        conn = db.get_connection()
        conn.execute(
            "UPDATE memories_episodic SET tags = ? WHERE id = ?",
            ('["environment"]', mid),
        )
        conn.commit()
        task = MemoryConsolidationTask(
            db=db, memory_manager=SimpleNamespace(semantic=SemanticMemory(db=db))
        )

        await task.run_async()

        assert _fetch_episodic(db, mid)["importance"] == 6
