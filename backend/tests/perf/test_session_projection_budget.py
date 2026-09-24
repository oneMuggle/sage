# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""按用户路径的性能预算基准（DSH 对标 R10，D1 第一刀）。

对标 deepseek-harness benchmarks 方法论：按用户路径（非微基准）、合成
负载、数值预算写死常量、环境变量不得覆盖。**默认进 CI**——预算取本地
实测的 8-10 倍余量，共享 runner 的正常波动不触线；回归（如 O(n²) 化）
则会成倍越线，信号明确。

用户路径（对标 dsh session-open / conversation-fold）：
1. 长会话打开：5,000 条消息 + 5,000 事件的合成会话全量读取；
2. 事件投影：events_to_history 全量投影；
3. 表投影：db_rows_to_history 全量投影（parity 另一侧）；
4. 请求装配：build_request_messages_from_events 带截断（预算收紧到
   触发 truncate_history 走完整遍历）。

预算（秒）：由 `perf_budget` 装置按 CI 倍率换算——本地参考机实测见
各用例注释；CI 若需收紧/放宽只改 `CI_SCALE`（env `SAGE_PERF_SCALE`
不得覆盖，对齐 dsh "环境变量不得覆盖预算"）。
"""

from __future__ import annotations

import time

import pytest

from backend.chat.event_projection import events_to_history
from backend.chat.history_context import (
    build_request_messages_from_events,
    db_rows_to_history,
)
from backend.data.session_event_repo import SessionEventRepository
from backend.data.session_repo import MessageRepository
from backend.tests.conftest import ensure_session

pytestmark = [pytest.mark.unit, pytest.mark.perf]

#: 合成会话规模（消息数）
N_MESSAGES = 5000
#: CI 倍率：本地参考机（Win10, Python 3.12）实测 × 该倍率 = 预算。
#: 预算写死为常量（本地实测值 × 10），不在运行时换算——对齐 dsh
#: "环境变量不得覆盖预算"纪律。
CI_SCALE = 10

#: 预算（秒）= 本地实测 × CI_SCALE：
#: 打开（get_by_session 全量）实测 ~0.05s / 投影 ~0.02s / 装配 ~0.03s
BUDGET_SESSION_OPEN = 0.5
BUDGET_EVENTS_PROJECTION = 0.5
BUDGET_ROWS_PROJECTION = 0.5
BUDGET_REQUEST_ASSEMBLY = 1.0


@pytest.fixture()
def big_session(setup_test_db):
    """合成 5,000 条消息（messages 表 + 事件日志双轨直插，绕过逐条 save）。"""
    import json
    import time

    sid = "s-perf-5000"
    ensure_session(setup_test_db, sid)
    now = int(time.time() * 1000)
    conn = setup_test_db.get_connection()
    msg_rows, ev_rows = [], []
    for i in range(N_MESSAGES):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"合成消息{i}：这是一段用于投影与截断基准的上下文文本。"
        created_at = now + i
        msg_id = f"perf-{i:05d}"
        msg_rows.append((msg_id, sid, role, content, created_at, i, None))
        ev_rows.append(
            (
                sid,
                i + 1,
                "message.appended",
                json.dumps(
                    {
                        "id": msg_id,
                        "role": role,
                        "content": content,
                        "subtype": None,
                        "segment_id": i,
                        "tool_calls": None,
                        "created_at": created_at,
                    },
                    ensure_ascii=False,
                ),
                created_at,
            )
        )
    conn.executemany(
        "INSERT INTO messages (id, session_id, role, content, created_at, segment_id, subtype) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        msg_rows,
    )
    conn.executemany(
        "INSERT INTO session_events (session_id, seq, type, payload, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ev_rows,
    )
    conn.commit()
    return sid


def _measure(fn):
    start = time.perf_counter()
    result = fn()
    return time.perf_counter() - start, result


class TestSessionPathBudgets:
    def test_session_open_budget(self, setup_test_db, big_session):
        """路径 1：长会话打开（全量读取）。预算 0.5s（本地实测 ×10）。"""
        repo = MessageRepository()
        elapsed, _ = _measure(
            lambda: repo.get_by_session(big_session, limit=100000)
        )
        assert elapsed < BUDGET_SESSION_OPEN, f"打开耗时 {elapsed:.3f}s"

    def test_events_projection_budget(self, setup_test_db, big_session):
        """路径 2：事件投影（5,000 事件）。预算 0.5s。"""
        events = SessionEventRepository().get_by_session(big_session)
        elapsed, history = _measure(lambda: events_to_history(events))
        assert elapsed < BUDGET_EVENTS_PROJECTION, f"投影耗时 {elapsed:.3f}s"
        assert len(history) == N_MESSAGES

    def test_rows_projection_budget(self, setup_test_db, big_session):
        """路径 3：messages 表投影（parity 另一侧，同预算）。"""
        rows = MessageRepository().get_by_session(big_session, limit=100000)
        elapsed, history = _measure(lambda: db_rows_to_history(rows))
        assert elapsed < BUDGET_ROWS_PROJECTION, f"表投影耗时 {elapsed:.3f}s"
        assert len(history) == N_MESSAGES

    def test_request_assembly_with_truncation_budget(self, setup_test_db, big_session):
        """路径 4：请求装配 + 强制截断（预算收紧触发 truncate 完整遍历）。"""
        events = SessionEventRepository().get_by_session(big_session)
        elapsed, (messages, omitted) = _measure(
            lambda: build_request_messages_from_events(
                system_content="系统提示",
                user_text="新问题",
                events=events,
                budget_tokens=2000,  # 收紧预算 → 强制截断遍历
                turn_limit=None,
            )
        )
        assert elapsed < BUDGET_REQUEST_ASSEMBLY, f"装配耗时 {elapsed:.3f}s"
        assert omitted > 0  # 确实触发了截断
        assert messages[0]["role"] == "system"

    def test_parity_on_big_session(self, setup_test_db, big_session):
        """大会话上的 parity 抽查：两端投影一致（正确性优先于耗时）。"""
        events = SessionEventRepository().get_by_session(big_session)
        rows = MessageRepository().get_by_session(big_session, limit=100000)
        assert events_to_history(events) == db_rows_to_history(rows)
