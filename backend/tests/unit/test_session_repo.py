# =============================================================================
# Reasoning Content 持久化测试
# =============================================================================


def test_message_with_reasoning_content():
    """Message dataclass 应支持 reasoning_content 字段。"""
    from backend.data.session_repo import Message

    msg = Message(
        id="msg-1",
        session_id="sess-1",
        role="assistant",
        content="答案是 42",
        created_at=1000,
        reasoning_content="让我思考一下：6 * 7 = 42",
    )

    assert msg.reasoning_content == "让我思考一下：6 * 7 = 42"


def test_message_reasoning_content_defaults_to_none():
    """Message.reasoning_content 应默认为 None。"""
    from backend.data.session_repo import Message

    msg = Message(
        id="msg-1",
        session_id="sess-1",
        role="user",
        content="你好",
        created_at=1000,
    )

    assert msg.reasoning_content is None


def test_message_to_dict_includes_reasoning_content():
    """Message.to_dict() 应包含 reasoning_content 字段。"""
    from backend.data.session_repo import Message

    msg = Message(
        id="msg-1",
        session_id="sess-1",
        role="assistant",
        content="答案",
        created_at=1000,
        reasoning_content="思考过程...",
    )

    d = msg.to_dict()
    assert "reasoning_content" in d
    assert d["reasoning_content"] == "思考过程..."


def test_message_from_row_with_reasoning_content():
    """Message.from_row() 应正确读取 reasoning_content 列。"""
    from backend.data.session_repo import Message

    # 模拟数据库行
    row = {
        "id": "msg-1",
        "session_id": "sess-1",
        "role": "assistant",
        "content": "答案",
        "created_at": 1000,
        "model": "gpt-4",
        "provider": "openai",
        "tool_calls": None,
        "tool_call_id": None,
        "reasoning_content": "我的思考...",
    }

    msg = Message.from_row(row)
    assert msg.reasoning_content == "我的思考..."


# =============================================================================
# R38 透明度增强持久化测试 (2026-09-18)
# =============================================================================


def _row_with_r38(**overrides):
    base = {
        "id": "msg-1",
        "session_id": "sess-1",
        "role": "assistant",
        "content": "答案",
        "created_at": 1000,
        "model": "gpt-4",
        "provider": "openai",
        "tool_calls": None,
        "tool_call_id": None,
        "reasoning_content": None,
    }
    base.update(overrides)
    return base


def test_r38_fields_default_to_none():
    """三条 R38 列在 Message 上默认 None。"""
    from backend.data.session_repo import Message

    msg = Message(id="m", session_id="s", role="user", content="hi", created_at=1)
    assert msg.activated_skills is None
    assert msg.compact_info is None
    assert msg.memory_refs is None


def test_r38_from_row_without_columns_is_none():
    """老库/plain dict 缺这些键时 from_row 不抛错 (守卫式读取)。"""
    from backend.data.session_repo import Message

    msg = Message.from_row(_row_with_r38())
    assert msg.activated_skills is None
    assert msg.compact_info is None
    assert msg.memory_refs is None


def test_r38_to_dict_parses_json_columns():
    """to_dict 把 JSON-in-TEXT 解析成结构化值供前端消费。"""
    import json

    from backend.data.session_repo import Message

    msg = Message(
        id="m",
        session_id="s",
        role="user",
        content="hi",
        created_at=1,
        activated_skills=json.dumps(
            [{"name": "deploy", "triggers_matched": ["deploy"]}], ensure_ascii=False
        ),
        compact_info=json.dumps({"before": 20, "after": 8, "removed": 12}),
        memory_refs=json.dumps([{"id": "mem-1", "preview": "偏好吗"}]),
    )

    d = msg.to_dict()
    assert d["activated_skills"] == [{"name": "deploy", "triggers_matched": ["deploy"]}]
    assert d["compact_info"] == {"before": 20, "after": 8, "removed": 12}
    assert d["memory_refs"] == [{"id": "mem-1", "preview": "偏好吗"}]


def test_r38_to_dict_degrades_on_malformed_json():
    """畸形 JSON 降级为 None，不抛错（读路径不能因脏数据整批失败）。"""
    from backend.data.session_repo import Message

    msg = Message(
        id="m",
        session_id="s",
        role="user",
        content="hi",
        created_at=1,
        activated_skills="{broken",
        compact_info="[1,2,3]",  # 形状不符：期望 dict
        memory_refs='{"a":1}',  # 形状不符：期望 list
    )

    d = msg.to_dict()
    assert d["activated_skills"] is None
    assert d["compact_info"] is None
    assert d["memory_refs"] is None


def test_r38_save_roundtrips_json_columns(setup_test_db):
    """save → from_row 三条 R38 列原样往返 (JSON-in-TEXT)。"""
    import json

    from backend.data.session_repo import Message, MessageRepository, SessionRepository

    session = SessionRepository().create(title="r38")
    repo = MessageRepository()
    repo.save(
        Message(
            id="msg-r38-1",
            session_id=session.id,
            role="user",
            content="hi",
            created_at=1,
            activated_skills=json.dumps(
                [{"name": "deploy", "triggers_matched": ["deploy"]}], ensure_ascii=False
            ),
        )
    )

    rows = repo.get_by_session(session.id)
    assert len(rows) == 1
    parsed = rows[0].to_dict()
    assert parsed["activated_skills"] == [
        {"name": "deploy", "triggers_matched": ["deploy"]}
    ]


def test_r38_compact_info_survives_prefix_replacement(setup_test_db):
    """压缩续接行落盘后, compact_info 可从 DB 读回 (重载渲染横幅的依据)。"""
    import json

    from backend.data.session_repo import Message, MessageRepository, SessionRepository

    session = SessionRepository().create(title="r38-compact")
    repo = MessageRepository()
    for i in range(3):
        repo.save(
            Message(
                id=f"old-{i}",
                session_id=session.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"旧消息 {i}",
                created_at=100 + i,
            )
        )

    repo.replace_prefix_with_continuation(
        session.id,
        ["old-0", "old-1"],
        Message(
            id="cont-1",
            session_id=session.id,
            role="assistant",
            content="这是摘要正文",
            created_at=99,
            compact_info=json.dumps({"before": 3, "after": 2, "removed": 2}),
        ),
        new_message_count=2,
    )

    rows = repo.get_by_session(session.id)
    continuation = next(r for r in rows if r.id == "cont-1")
    assert continuation.to_dict()["compact_info"] == {
        "before": 3,
        "after": 2,
        "removed": 2,
    }
    # 摘要正文本身仍在（横幅与正文并存）
    assert continuation.to_dict()["content"] == "这是摘要正文"


def test_r38_migration_adds_columns_to_legacy_db(setup_test_db):
    """init_db 对已有库补齐三列；重复调用幂等（不抛 duplicate column）。"""
    import backend.data.database as db_mod

    db = db_mod.get_database()
    conn = db.get_connection()
    cursor = conn.cursor()
    cols = [r["name"] for r in cursor.execute("PRAGMA table_info(messages)").fetchall()]
    for col in ("activated_skills", "compact_info", "memory_refs"):
        assert col in cols

    # 幂等: 再跑一次迁移不抛错（TOCTOU 兜底）
    db.init_db()
    cols_again = [
        r["name"] for r in cursor.execute("PRAGMA table_info(messages)").fetchall()
    ]
    assert cols_again.count("activated_skills") == 1


# =============================================================================
# 会话列表排序测试 (2026-09-21)
# =============================================================================


def test_list_sort_order_pinned_first_then_active_then_by_time(setup_test_db):
    """list() 排序: 置顶 > 活跃(running/suspended) > updated_at DESC。

    验证三层排序优先级:
    1. is_pinned DESC — 置顶会话永远在最前
    2. run_status IN ('running','suspended') DESC — 活跃流次之
    3. updated_at DESC — 同优先级内按时间降序
    """
    import time

    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()

    # 创建 5 个会话，间隔 1ms 保证 updated_at 不同
    sessions = []
    for i in range(5):
        s = repo.create(title=f"session-{i}")
        sessions.append(s)
        time.sleep(0.001)

    # session-4 最新，session-0 最旧
    s0, s1, s2, s3, s4 = sessions

    # 设置不同状态，各会话角色如下：
    # - s0 是 idle，即最旧、默认
    # - s1 是 running，即活跃
    # - s2 是 completed 终态，等同 idle
    # - s3 是 suspended，即活跃
    # - s4 是 pinned 置顶、最新
    repo.update_run_status(s1.id, "running")
    repo.update_run_status(s2.id, "completed")
    repo.update_run_status(s3.id, "suspended")
    repo.pin(s4.id, True)

    result = repo.list()
    ids = [s.id for s in result]

    # s4 pinned 排第一
    assert ids[0] == s4.id, "置顶会话应排第一"

    # s3 suspended 和 s1 running 是活跃会话，排在非活跃之前
    # s3 updated_at > s1 updated_at，所以 s3 在 s1 前
    active_ids = [i for i in ids if i in (s1.id, s3.id)]
    assert active_ids == [s3.id, s1.id], "活跃会话按 updated_at DESC，s3 比 s1 新"

    # 非活跃会话 s2 completed 和 s0 idle 按 updated_at DESC
    # s2 updated_at > s0 updated_at
    inactive_ids = [i for i in ids if i in (s0.id, s2.id)]
    assert inactive_ids == [s2.id, s0.id], "非活跃会话按 updated_at DESC"

    # 最终排序验证：pinned > suspended > running > completed > idle
    # s4 pinned > s3 suspended > s1 running > s2 completed > s0 idle
    assert ids == [s4.id, s3.id, s1.id, s2.id, s0.id]


def test_list_sort_order_excludes_failed_from_active(setup_test_db):
    """failed 状态不算活跃，排在 idle 同层（按 updated_at DESC）。"""
    import time

    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()

    s1 = repo.create(title="idle-session")
    time.sleep(0.001)
    s2 = repo.create(title="failed-session")
    repo.update_run_status(s2.id, "failed")
    time.sleep(0.001)
    s3 = repo.create(title="running-session")
    repo.update_run_status(s3.id, "running")

    result = repo.list()
    ids = [s.id for s in result]

    # running 在最前，然后 s2 (failed, newer)，最后 s1 (idle, older)
    assert ids == [s3.id, s2.id, s1.id]
