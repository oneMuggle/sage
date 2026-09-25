# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""D1b：R9/R2 代码路径的性能预算（迁移应用 + 存量回填 + 事件追加）。

延续 R10 的方法论（按用户路径、合成负载、预算写死常量 ×10 余量），
把 D1a 未覆盖的两条 R2/R9 路径纳入数值门：

1. 存量回填：5,000 条 legacy messages → backfill_session_events 全量
   补写事件（SE2 的启动路径，随 init_db 每次启动执行——必须恒定快）；
2. 事件追加吞吐：经 MessageRepository.save 双写 5,000 条消息（热路径，
   含事件 INSERT + FTS 索引挂钩）。

用户语义提醒：回填是"SE1 之前的存量会话"启动路径，若其耗时随历史
线性劣化，用户每次启动都买单——这正是数值门要守的。
"""

from __future__ import annotations

import time

import pytest

from backend.data.migrations.runner import run_pending_migrations
from backend.data.session_event_backfill import backfill_session_events
from backend.data.session_event_repo import SessionEventRepository
from backend.data.session_repo import Message, MessageRepository
from backend.tests.conftest import ensure_session

pytestmark = [pytest.mark.unit, pytest.mark.perf]

#: 合成规模（与 R10 的 D1a 对齐）
N_MESSAGES = 5000

#: 预算（秒）= 本地实测 × 10：
#: 回填 5,000 条实测 ~0.4s；双写 5,000 条实测 ~2.5s
BUDGET_BACKFILL = 4.0
BUDGET_DUAL_WRITE = 25.0


def _seed_legacy_messages(db, sid, n):
    """直插 legacy messages（绕过双写——模拟 SE1 之前的存量行）。"""
    import time

    now = int(time.time() * 1000)
    rows = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"存量消息{i}：回填基准文本。"
        rows.append(
            (f"legacy-{i:05d}", sid, role, content, now + i, 0, None)
        )
    conn = db.get_connection()
    conn.executemany(
        "INSERT INTO messages (id, session_id, role, content, created_at, segment_id, subtype) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def test_backfill_5000_budget(setup_test_db):
    """路径：存量回填（5,000 行）≤ 4s（本地实测 ~0.4s × 10）。"""
    sid = "s-perf-backfill"
    ensure_session(setup_test_db, sid)
    _seed_legacy_messages(setup_test_db, sid, N_MESSAGES)

    start = time.perf_counter()
    result = backfill_session_events(setup_test_db)
    elapsed = time.perf_counter() - start

    assert result["events_written"] == N_MESSAGES
    assert elapsed < BUDGET_BACKFILL, f"回填耗时 {elapsed:.3f}s"


def test_migration_runner_overhead_budget(setup_test_db):
    """路径：迁移框架空转（init_db 每次启动的固定开销）≤ 0.2s。"""
    conn = setup_test_db.get_connection()
    start = time.perf_counter()
    run_pending_migrations(conn)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.2, f"空转耗时 {elapsed:.3f}s"


def test_dual_write_throughput_budget(setup_test_db):
    """路径：消息双写吞吐（5,000 条 save，含事件+FTS 挂钩）≤ 25s。

    本地实测 ~2.5s（×10 余量）；显著劣化说明事件/索引挂钩出现
    逐条全表扫描类回归。
    """
    sid = "s-perf-dual"
    ensure_session(setup_test_db, sid)
    repo = MessageRepository()
    import time

    start = time.perf_counter()
    for i in range(N_MESSAGES):
        role = "user" if i % 2 == 0 else "assistant"
        repo.save(
            Message(
                id=f"dual-{i:05d}",
                session_id=sid,
                role=role,
                content=f"双写消息{i}",
                created_at=int(time.time() * 1000) + i,
            )
        )
    elapsed = time.perf_counter() - start
    assert elapsed < BUDGET_DUAL_WRITE, f"双写耗时 {elapsed:.1f}s"
    assert SessionEventRepository().count_by_session(sid) == N_MESSAGES
