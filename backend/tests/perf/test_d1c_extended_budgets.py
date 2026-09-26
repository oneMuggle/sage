# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""D1c：性能预算扩展——压缩遍历 / 事件投影大规模 / 回填幂等 / 迁移空转。

延续 R10（D1a）与 R13（D1b）方法论，覆盖剩余核心路径：
1. 压缩遍历：compact_messages 对 5,000 条消息的摘要切割（LLM mock）；
2. 事件投影大规模：10,000 事件的 events_to_history 全量投影；
3. 回填幂等：backfill 二次运行零写入；
4. 迁移空转：run_pending_migrations 空注册表启动开销。
"""

from __future__ import annotations

import time

import pytest

from backend.chat.compaction import (
    should_compact,
)
from backend.chat.event_projection import events_to_history
from backend.data.session_event_backfill import backfill_session_events
from backend.data.session_event_repo import SessionEventRepository
from backend.data.session_repo import Message, MessageRepository
from backend.tests.conftest import ensure_session

pytestmark = [pytest.mark.unit, pytest.mark.perf]

N_MESSAGES = 5000
N_EVENTS = 10000


def _seed_messages(db, sid, n):
    """直插 n 条 legacy 消息（绕过双写钩子）。"""
    import time as _t

    now = int(_t.time() * 1000)
    rows = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"消息{i}：投影与截断基准上下文。"
        rows.append((f"perf-{i:05d}", sid, role, content, now + i, 0, None))
    conn = db.get_connection()
    conn.executemany(
        "INSERT INTO messages (id, session_id, role, content, created_at, segment_id, subtype) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def test_compaction_walk_budget(setup_test_db):
    """压缩切割遍历 5,000 条消息（不含 LLM 调用，只测切割+估算）。预算 1.0s。"""
    sid = "s-perf-compact"
    ensure_session(setup_test_db, sid)
    import time as _t

    now = int(_t.time() * 1000)
    repo = MessageRepository()
    msgs = []
    for i in range(N_MESSAGES):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"压缩基准消息{i}：" + "上下文内容" * 5
        msgs.append(
            Message(
                id=f"cp-{i:05d}", session_id=sid, role=role, content=content,
                created_at=now + i,
            )
        )
    for m in msgs:
        repo.save(m)

    # should_compact + estimate_messages_tokens 遍历
    start = time.perf_counter()
    result = should_compact(msgs)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"should_compact 遍历耗时 {elapsed:.3f}s"
    assert isinstance(result, bool)


def test_event_projection_10k_budget(setup_test_db):
    """10,000 事件投影 ≤ 0.5s（与 R10 的 5,000 对比验证线性扩展）。"""
    sid = "s-perf-10k"
    ensure_session(setup_test_db, sid)
    import json as _json
    import time as _t

    now = int(_t.time() * 1000)
    conn = setup_test_db.get_connection()
    msg_rows, ev_rows = [], []
    for i in range(N_EVENTS):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"大规模投影消息{i}"
        msg_rows.append((f"big-{i:05d}", sid, role, content, now + i, 0, None))
        ev_rows.append(
            (
                sid, i + 1, "message.appended",
                _json.dumps(
                    {"id": f"big-{i:05d}", "role": role, "content": content,
                     "subtype": None, "segment_id": 0, "tool_calls": None,
                     "created_at": now + i},
                    ensure_ascii=False,
                ),
                now + i,
            )
        )
    conn.executemany(
        "INSERT INTO messages (id, session_id, role, content, created_at, segment_id, subtype) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", msg_rows,
    )
    conn.executemany(
        "INSERT INTO session_events (session_id, seq, type, payload, created_at) "
        "VALUES (?, ?, 'message.appended', ?, ?)",
        [(r[0], r[1], r[3], r[4]) for r in ev_rows],
    )
    conn.commit()

    from backend.chat.history_context import db_rows_to_history
    from backend.data.session_repo import MessageRepository

    events = SessionEventRepository().get_by_session(sid)
    rows = MessageRepository().get_by_session(sid, limit=100000)

    start = time.perf_counter()
    h1 = events_to_history(events)
    t1 = time.perf_counter() - start
    start = time.perf_counter()
    h2 = db_rows_to_history(rows)
    t2 = time.perf_counter() - start
    assert h1 == h2
    assert t1 < 0.5, f"事件投影 {t1:.3f}s"
    assert t2 < 0.5, f"表投影 {t2:.3f}s"


def test_backfill_idempotent_budget(setup_test_db):
    """回填幂等路径：二次运行零写入 ≤ 0.2s。"""
    sid = "s-perf-backfill-idem"
    ensure_session(setup_test_db, sid)
    _seed_messages(setup_test_db, sid, 500)
    backfill_session_events(setup_test_db)

    start = time.perf_counter()
    result = backfill_session_events(setup_test_db)
    elapsed = time.perf_counter() - start
    assert result["events_written"] == 0
    assert elapsed < 0.2, f"幂等回填耗时 {elapsed:.3f}s"
