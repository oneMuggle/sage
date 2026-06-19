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
