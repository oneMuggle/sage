# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Task 3: history_context 段感知切片 + apply_turn_limit 单元测试。

测试目标：
1. db_rows_to_history 必须切片到 active segment（只保留最后一条 topic_separator 之后的行）。
2. apply_turn_limit 必须按 user 轮次从最旧开始丢。
"""

from types import SimpleNamespace

from backend.chat.history_context import apply_turn_limit, db_rows_to_history


def _row(role, content, **kwargs):
    """构造伪 DbMessage（SimpleNamespace，遵循既有 test_history_context.py 的 _row 模式）。"""
    base = {
        "id": f"m-{role}-{abs(hash(content)) % 10000}",
        "session_id": "s1",
        "role": role,
        "content": content,
        "created_at": 1,
        "model": None,
        "provider": None,
        "tool_calls": None,
        "tool_call_id": None,
        "reasoning_content": None,
        "subtype": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# ---- db_rows_to_history: segment-aware slicing ----


def test_db_rows_to_history_excludes_separator():
    """最后一个 topic_separator 之前的行被丢弃（包括分隔符之前的旧 user 消息）。"""
    rows = [
        _row("user", "old q"),
        _row("system", "reset", subtype="topic_separator"),
        _row("user", "new q"),
    ]
    result = db_rows_to_history(rows)
    assert len(result) == 1
    assert result[0]["content"] == "new q"


def test_db_rows_to_history_multiple_separators_keeps_after_last():
    """多个 separator 时，只保留最后一条之后的行。"""
    rows = [
        _row("user", "seg1 q1"),
        _row("system", "r1", subtype="topic_separator"),
        _row("user", "seg2 q1"),
        _row("assistant", "seg2 a1"),
        _row("system", "r2", subtype="topic_separator"),
        _row("user", "seg3 q1"),
    ]
    result = db_rows_to_history(rows)
    assert [m["content"] for m in result] == ["seg3 q1"]


def test_db_rows_to_history_no_separator_keeps_all():
    """无 separator 时行为不变（向后兼容）。"""
    rows = [
        _row("user", "q1"),
        _row("assistant", "a1"),
        _row("user", "q2"),
    ]
    result = db_rows_to_history(rows)
    assert [m["content"] for m in result] == ["q1", "a1", "q2"]


def test_db_rows_to_history_separator_at_end_returns_empty():
    """separator 是最后一条 → 切片后空消息全有。"""
    rows = [
        _row("user", "old q"),
        _row("system", "reset", subtype="topic_separator"),
    ]
    result = db_rows_to_history(rows)
    assert result == []


# ---- apply_turn_limit ----


def test_apply_turn_limit_no_limit():
    """turn_limit=None 或 <=0 → 原样返回，omitted=0。"""
    msgs = [{"role": "user", "content": f"q{i}"} for i in range(10)]
    kept, omitted = apply_turn_limit(msgs, turn_limit=None)
    assert len(kept) == 10
    assert omitted == 0

    kept, omitted = apply_turn_limit(msgs, turn_limit=0)
    assert len(kept) == 10
    assert omitted == 0

    kept, omitted = apply_turn_limit(msgs, turn_limit=-1)
    assert len(kept) == 10
    assert omitted == 0


def test_apply_turn_limit_caps_user_turns():
    """按 user 轮次截断，保留最新的 N 轮。"""
    msgs = []
    for i in range(6):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    kept, omitted = apply_turn_limit(msgs, turn_limit=2)
    user_contents = [m["content"] for m in kept if m["role"] == "user"]
    assert user_contents == ["q4", "q5"]
    assert omitted > 0
    # 最新一轮（a5）也必须保留
    assert kept[-1] == {"role": "assistant", "content": "a5"}


def test_apply_turn_limit_caps_exact_count():
    """turn_limit == user_count → 不丢弃。"""
    msgs = [
        {"role": "user", "content": "q0"},
        {"role": "assistant", "content": "a0"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]
    kept, omitted = apply_turn_limit(msgs, turn_limit=2)
    assert omitted == 0
    assert len(kept) == 4


def test_apply_turn_limit_empty_messages():
    """空列表 → 空消息全返回。"""
    kept, omitted = apply_turn_limit([], turn_limit=3)
    assert kept == []
    assert omitted == 0


def test_apply_turn_limit_more_than_available():
    """turn_limit 大于实际 user 数 → 全部保留。"""
    msgs = [
        {"role": "user", "content": "q0"},
        {"role": "assistant", "content": "a0"},
    ]
    kept, omitted = apply_turn_limit(msgs, turn_limit=10)
    assert len(kept) == 2
    assert omitted == 0


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
