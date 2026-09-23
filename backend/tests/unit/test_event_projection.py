# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""事件投影 parity 测试（DSH 对标 R1，SE1）。

核心契约：**同一会话经 MessageRepository 写入后，
``events_to_history(事件日志) ≡ db_rows_to_history(messages 表)``** ——
「凡进模型请求的内容能从事件日志重建」。覆盖：角色白名单、tool_calls
跳过、空内容跳过、双 segment 切片、insert() 路径、压缩事件不影响投影。
"""

from __future__ import annotations

import time

import pytest

from backend.chat.event_projection import events_to_history
from backend.chat.history_context import db_rows_to_history
from backend.data.session_event_repo import (
    EVENT_COMPACTION_PERFORMED,
    SessionEventRepository,
)
from backend.data.session_repo import Message, MessageRepository
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


def _msg(sid, idx, role, content, created_at, **kwargs):
    return Message(
        id=f"msg-{idx:03d}",
        session_id=sid,
        role=role,
        content=content,
        created_at=created_at,
        **kwargs,
    )


def _assert_parity(db, sid):
    """parity 契约断言：事件日志投影 ≡ messages 表投影。"""
    messages = MessageRepository().get_by_session(sid, limit=100000)
    events = SessionEventRepository().get_by_session(sid)
    assert events_to_history(events) == db_rows_to_history(messages)


# ---- parity：复杂消息序列 ----


def test_parity_roles_tool_calls_empty_content(setup_test_db):
    sid = "s-parity-1"
    ensure_session(setup_test_db, sid)
    repo = MessageRepository()
    now = 1700000000000

    repo.save(_msg(sid, 1, "user", "第一句", now + 1))
    repo.save(_msg(sid, 2, "assistant", "第一答", now + 2))
    # tool 行：白名单外 → 两边都跳过
    repo.save(_msg(sid, 3, "tool", "工具结果", now + 3))
    # system 行：白名单外 → 两边都跳过
    repo.save(_msg(sid, 4, "system", "内嵌 system", now + 4))
    # 带 tool_calls 的 assistant 行（裸 ReAct 中间态）→ 两边都跳过
    repo.save(
        _msg(
            sid,
            5,
            "assistant",
            "调用工具",
            now + 5,
            tool_calls='[{"id":"t1","function":{"name":"bash"}}]',
        )
    )
    # 空 content → 两边都跳过
    repo.save(_msg(sid, 6, "assistant", "   ", now + 6))
    repo.save(_msg(sid, 7, "user", "第二句", now + 7))
    repo.save(_msg(sid, 8, "assistant", "第二答", now + 8))

    _assert_parity(setup_test_db, sid)
    history = events_to_history(SessionEventRepository().get_by_session(sid))
    assert history == [
        {"role": "user", "content": "第一句"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二句"},
        {"role": "assistant", "content": "第二答"},
    ]


def test_parity_segment_slicing(setup_test_db):
    sid = "s-parity-2"
    ensure_session(setup_test_db, sid)
    repo = MessageRepository()
    now = 1700000000000

    repo.save(_msg(sid, 1, "user", "旧段-问", now + 1))
    repo.save(_msg(sid, 2, "assistant", "旧段-答", now + 2))
    # 段切换标记（context-isolation）：两边都从它之后切片
    repo.save(_msg(sid, 3, "user", "---", now + 3, subtype="topic_separator"))
    repo.save(_msg(sid, 4, "user", "新段-问", now + 4))
    repo.save(_msg(sid, 5, "assistant", "新段-答", now + 5))

    _assert_parity(setup_test_db, sid)
    history = events_to_history(SessionEventRepository().get_by_session(sid))
    assert history == [
        {"role": "user", "content": "新段-问"},
        {"role": "assistant", "content": "新段-答"},
    ]


def test_parity_insert_path(setup_test_db):
    """insert()（scheduler 定时消息路径）同样双写且 parity。"""
    sid = "s-parity-3"
    ensure_session(setup_test_db, sid)
    repo = MessageRepository()
    now = 1700000000000

    repo.save(_msg(sid, 1, "user", "第一轮", now + 1))
    repo.insert(sid, "user", "定时提醒", created_at=now + 2)

    _assert_parity(setup_test_db, sid)


# ---- compaction 事件 ----


def test_compaction_event_written_and_ignored_by_projection(setup_test_db):
    sid = "s-compact-1"
    ensure_session(setup_test_db, sid)
    repo = MessageRepository()
    now = 1700000000000

    kept_prefix_ids = []
    for i in range(1, 6):
        m = _msg(sid, i, "user", f"消息{i}", now + i)
        repo.save(m)
        kept_prefix_ids.append(m.id)
    tail = _msg(sid, 6, "assistant", "保留的尾部", now + 6)
    repo.save(tail)

    continuation = Message(
        id="msg-cont-1",
        session_id=sid,
        role="assistant",
        content="[上下文已压缩] 此前对话摘要：……",
        created_at=now + 100,
    )
    repo.replace_prefix_with_continuation(
        sid, kept_prefix_ids, continuation, new_message_count=2
    )

    # 1) 压缩事件已落日志，payload 完整
    events = SessionEventRepository().get_by_session(sid)
    compaction_events = [e for e in events if e.type == EVENT_COMPACTION_PERFORMED]
    assert len(compaction_events) == 1
    payload = compaction_events[0].payload
    assert payload["deleted_ids"] == kept_prefix_ids
    assert payload["continuation_id"] == "msg-cont-1"
    assert payload["removed_count"] == 5
    assert payload["reason"] == "compaction"

    # 2) 事件日志仍能完整重建压缩前的事实（append-only 的意义所在）：
    #    5 条被删前缀在 messages 已不在，但其 message.appended 事件仍在
    appended_user_events = [
        e.payload
        for e in events
        if e.type == "message.appended" and e.payload["role"] == "user"
    ]
    assert len(appended_user_events) == 5

    # 3) 投影折叠压缩（deleted_ids 不进当前视图）+ 续接消息事件在册
    #    —— parity 在压缩后的会话上依旧成立
    _assert_parity(setup_test_db, sid)
    history = events_to_history(events)
    assert history == [
        {"role": "assistant", "content": "保留的尾部"},
        {"role": "assistant", "content": "[上下文已压缩] 此前对话摘要：……"},
    ]


# ---- 删除路径 parity ----


def test_parity_after_message_delete(setup_test_db):
    """delete() 落 message.deleted 事件，投影折叠后与 messages 一致。"""
    sid = "s-del-1"
    ensure_session(setup_test_db, sid)
    repo = MessageRepository()
    now = 1700000000000

    m1 = _msg(sid, 1, "user", "保留问", now + 1)
    m2 = _msg(sid, 2, "assistant", "被删答", now + 2)
    m3 = _msg(sid, 3, "user", "保留答后问", now + 3)
    for m in (m1, m2, m3):
        repo.save(m)

    assert repo.delete(m2.id) is True
    _assert_parity(setup_test_db, sid)
    history = events_to_history(SessionEventRepository().get_by_session(sid))
    assert history == [
        {"role": "user", "content": "保留问"},
        {"role": "user", "content": "保留答后问"},
    ]
    # 事件日志里被删消息的事实仍在（append-only）
    events = SessionEventRepository().get_by_session(sid)
    assert any(
        e.type == "message.deleted" and e.payload["id"] == m2.id for e in events
    )


def test_parity_after_segment_retreat(setup_test_db):
    """retreat_segment 删 separator 后，事件投影不再在原处分段。"""
    import time as _time  # 局部导入保留（其余用例用模块级 time）

    sid = "s-retreat-1"
    ensure_session(setup_test_db, sid)
    repo = MessageRepository()
    # 注意：advance_segment 内部用真实 wall clock 落 separator 的
    # created_at；messages 表按 created_at 排序而投影按 seq 排序，
    # 测试消息的时间戳必须与 separator 的实际落库时间保序。
    now = int(_time.time() * 1000)

    repo.save(_msg(sid, 1, "user", "第一段问", now + 1))
    repo.save(_msg(sid, 2, "assistant", "第一段答", now + 2))
    assert repo.advance_segment(sid) == 1
    # 取 separator 的实际 created_at，让后续消息晚于它（时钟确定性）
    separator = [
        m
        for m in repo.get_by_session(sid, limit=100000)
        if m.subtype == "topic_separator"
    ][0]
    repo.save(_msg(sid, 4, "user", "第二段问", separator.created_at + 1))
    # 切分前：投影只看第二段
    _assert_parity(setup_test_db, sid)
    assert events_to_history(SessionEventRepository().get_by_session(sid)) == [
        {"role": "user", "content": "第二段问"}
    ]

    # 撤销分段：两边都回到整段视图
    assert repo.retreat_segment(sid) is True
    _assert_parity(setup_test_db, sid)
    assert events_to_history(SessionEventRepository().get_by_session(sid)) == [
        {"role": "user", "content": "第一段问"},
        {"role": "assistant", "content": "第一段答"},
        {"role": "user", "content": "第二段问"},
    ]


# ---- fork 路径 parity（SE2：fork 钩子收口）----


def test_parity_after_fork(setup_test_db):
    """fork_session 复制的行同事务落事件，子会话投影 parity 成立。"""
    from backend.data.session_repo import SessionRepository, fork_session

    src = "s-fork-src"
    ensure_session(setup_test_db, src)
    repo = MessageRepository()
    now = int(time.time() * 1000)

    m1 = _msg(src, 1, "user", "源问一", now + 1)
    m2 = _msg(src, 2, "assistant", "源答一", now + 2)
    m3 = _msg(src, 3, "user", "源问二", now + 3)
    for m in (m1, m2, m3):
        repo.save(m)

    forked = fork_session(
        SessionRepository(), repo, src, at_message_id=m2.id, title="fork 测试"
    )

    # 子会话：events 投影 ≡ messages 表投影
    _assert_parity(setup_test_db, forked.id)
    # 事件 id 与复制行 id 一致（payload.id 与 messages.id 逐条对应）
    events = SessionEventRepository().get_by_session(forked.id)
    forked_rows = repo.get_by_session(forked.id, limit=100000)
    assert [e.payload["id"] for e in events] == [r.id for r in forked_rows]
    # fork 复制行如实记录表默认值（无 subtype / segment 0）
    assert all(e.payload["subtype"] is None for e in events)
    assert all(e.payload["segment_id"] == 0 for e in events)


# ---- 读取切换（SE2）：两条装配路径逐字节一致 ----


def test_build_request_messages_events_vs_rows_parity(setup_test_db):
    """build_request_messages_from_events ≡ build_request_messages（同数据）。"""
    from backend.chat.history_context import (
        build_request_messages,
        build_request_messages_from_events,
    )

    sid = "s-cutover-1"
    ensure_session(setup_test_db, sid)
    repo = MessageRepository()
    now = int(time.time() * 1000)
    for i, (role, content) in enumerate(
        [("user", "一问"), ("assistant", "一答"), ("user", "二问")], start=1
    ):
        repo.save(_msg(sid, i, role, content, now + i))

    history_rows = repo.get_by_session(sid, limit=100000)
    events = SessionEventRepository().get_by_session(sid)

    common = {
        "system_content": "你是测试系统提示",
        "user_text": "新问题",
        "attachment_block": None,
        "budget_tokens": 100000,
        "trailing_system": "动态上下文",
        "turn_limit": None,
    }
    via_rows = build_request_messages(history_rows=history_rows, **common)
    via_events = build_request_messages_from_events(events=events, **common)
    assert via_events == via_rows
    assert [m["role"] for m in via_events[0][-1:]] == ["user"]


# ---- 纯函数边界 ----


def test_projection_skips_non_message_events():
    events = [
        {"type": "compaction.performed", "payload": {"removed_count": 3}},
        {"type": "message.appended", "payload": {"role": "user", "content": "问"}},
        {"type": "unknown.future", "payload": {"role": "user", "content": "未来事件"}},
    ]
    assert events_to_history(events) == [{"role": "user", "content": "问"}]


def test_projection_empty_and_malformed_payload():
    assert events_to_history([]) == []
    events = [
        {"type": "message.appended", "payload": None},
        {"type": "message.appended", "payload": {"role": "user", "content": None}},
        {"type": "message.appended", "payload": {"role": "", "content": "x"}},
        {"type": "message.appended", "payload": {"role": "user", "content": "好的"}},
    ]
    assert events_to_history(events) == [{"role": "user", "content": "好的"}]


def test_projection_folds_compacted_ids():
    """压缩折叠：deleted_ids 中的消息事件不进当前视图（日志仍完整）。"""
    events = [
        {"type": "message.appended", "payload": {"id": "a", "role": "user", "content": "旧问"}},
        {
            "type": "message.appended",
            "payload": {"id": "b", "role": "assistant", "content": "旧答"},
        },
        {
            "type": "compaction.performed",
            "payload": {"deleted_ids": ["a", "b"], "continuation_id": "c"},
        },
        {
            "type": "message.appended",
            "payload": {"id": "c", "role": "assistant", "content": "续接摘要"},
        },
    ]
    assert events_to_history(events) == [{"role": "assistant", "content": "续接摘要"}]


def test_projection_separator_only_session():
    events = [
        {
            "type": "message.appended",
            "payload": {"role": "user", "content": "---", "subtype": "topic_separator"},
        }
    ]
    assert events_to_history(events) == []
