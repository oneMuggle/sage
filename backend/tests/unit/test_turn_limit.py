# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Task 7: ``context_turn_limit`` setting → build_request_messages 流水线接入测试。

验证 ``build_request_messages`` 接受 ``turn_limit`` 参数并按 user 轮数截断历史。
"""

from types import SimpleNamespace

from backend.chat.history_context import build_request_messages


def _row(role, content, **kwargs):
    """构造伪 DbMessage（SimpleNamespace，避免依赖 DB 会话）。"""
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
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_build_request_messages_applies_turn_limit():
    """6 轮历史 + turn_limit=2 → 只保留最近 2 轮 (user + assistant 各 2 条)。"""
    rows = []
    for i in range(6):
        rows.append(_row("user", f"q{i}"))
        rows.append(_row("assistant", f"a{i}"))

    messages, omitted = build_request_messages(
        system_content="system",
        user_text="current q",
        history_rows=rows,
        turn_limit=2,
    )

    # 系统 + 历史(2 轮=4 条) + 当前 user = 6 条
    # 实际应有 1 system + 4 history (q4/a4/q5/a5) + 1 trailing user
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "current q"

    # 提取历史区 — 跳过首尾消息
    history_msgs = messages[1:-1]
    user_msgs = [m for m in history_msgs if m["role"] == "user"]
    assistant_msgs = [m for m in history_msgs if m["role"] == "assistant"]
    assert len(user_msgs) == 2
    assert len(assistant_msgs) == 2
    # 应保留最近 2 轮：q4/a4/q5/a5
    assert [m["content"] for m in history_msgs] == ["q4", "a4", "q5", "a5"]

    # omitted 应反映被砍掉的轮数(6 轮 user → 保留 2 轮 → 砍 4 轮 ×2 条/轮 = 8 条)
    assert omitted == 8


def test_build_request_messages_turn_limit_none_keeps_all():
    """turn_limit=None → 行为不变，全部保留。"""
    rows = []
    for i in range(3):
        rows.append(_row("user", f"q{i}"))
        rows.append(_row("assistant", f"a{i}"))

    messages, omitted = build_request_messages(
        system_content="system",
        user_text="current",
        history_rows=rows,
        turn_limit=None,
    )

    history_msgs = messages[1:-1]
    assert len(history_msgs) == 6
    assert omitted == 0


def test_build_request_messages_turn_limit_zero_keeps_all():
    """turn_limit=0 → 视同不限，原样返回（仅测 0，负数见 _negative 用例）。"""
    rows = [_row("user", "q0"), _row("assistant", "a0")]
    messages, omitted = build_request_messages(
        system_content="system",
        user_text="current",
        history_rows=rows,
        turn_limit=0,
    )
    history_msgs = messages[1:-1]
    assert len(history_msgs) == 2
    assert omitted == 0


def test_build_request_messages_turn_limit_negative():
    """turn_limit=-1 → 负数视同不限（apply_turn_limit 的 <=0 守门），原样返回。"""
    rows = []
    for i in range(4):
        rows.append(_row("user", f"q{i}"))
        rows.append(_row("assistant", f"a{i}"))

    messages, omitted = build_request_messages(
        system_content="system",
        user_text="current",
        history_rows=rows,
        turn_limit=-1,
    )

    history_msgs = messages[1:-1]
    # 4 轮 = 8 条，全部保留
    assert len(history_msgs) == 8
    assert omitted == 0


def test_settings_non_numeric_turn_limit():
    """SettingsRepository 返回 'abc' → int() 失败降级为 None → 不截断。

    复现 legacy_routes.py 的 settings 解析契约：非数字值走 ValueError 分支
    回退到 turn_limit=None，下游 build_request_messages 视同不限。
    """
    # 模拟 legacy_routes.py 的解析逻辑
    raw_value = "abc"
    if raw_value:
        try:
            parsed_limit = int(raw_value)
        except (ValueError, TypeError):
            parsed_limit = None
    else:
        parsed_limit = None

    assert parsed_limit is None, "非数字设置值应降级为 None"

    # 验证下游行为：turn_limit=None 时不截断
    rows = [_row("user", "q0"), _row("assistant", "a0")]
    messages, omitted = build_request_messages(
        system_content="system",
        user_text="current",
        history_rows=rows,
        turn_limit=parsed_limit,
    )
    history_msgs = messages[1:-1]
    assert len(history_msgs) == 2
    assert omitted == 0


def test_settings_missing_turn_limit_key():
    """SettingsRepository 返回 None（键不存在）→ 跳过解析 → turn_limit=None → 不截断。

    复现 legacy_routes.py 的 settings 解析契约：缺失键时 raw 为 None/falsy，
    不进 int() 分支，turn_limit 维持初始值 None。
    """
    # 模拟 legacy_routes.py 的解析逻辑
    raw_value = None
    if raw_value:
        try:
            parsed_limit = int(raw_value)  # pragma: no cover
        except (ValueError, TypeError):
            parsed_limit = None  # pragma: no cover
    else:
        parsed_limit = None

    assert parsed_limit is None, "缺失键应得到 None"

    # 验证下游行为
    rows = [_row("user", "q0"), _row("assistant", "a0")]
    messages, omitted = build_request_messages(
        system_content="system",
        user_text="current",
        history_rows=rows,
        turn_limit=parsed_limit,
    )
    history_msgs = messages[1:-1]
    assert len(history_msgs) == 2
    assert omitted == 0


def test_build_request_messages_turn_limit_larger_than_history():
    """turn_limit 大于实际轮数 → 全部保留，omitted=0。"""
    rows = [_row("user", "q0"), _row("assistant", "a0")]
    messages, omitted = build_request_messages(
        system_content="system",
        user_text="current",
        history_rows=rows,
        turn_limit=100,
    )
    history_msgs = messages[1:-1]
    assert len(history_msgs) == 2
    assert omitted == 0


def test_build_request_messages_omitted_sums_truncate_and_turn_limit():
    """token 截断 + turn_limit 双重作用时，omitted 是二者合计。"""
    rows = []
    for i in range(20):
        rows.append(_row("user", f"q{i}"))
        rows.append(_row("assistant", f"a{i}"))

    # budget 极小 → truncate_history 会砍掉很多;
    # turn_limit=1 → 在 truncate 基础上再砍到只留最后 1 轮
    messages, omitted = build_request_messages(
        system_content="system",
        user_text="current",
        history_rows=rows,
        budget_tokens=50,
        turn_limit=1,
    )

    history_msgs = messages[1:-1]
    user_msgs = [m for m in history_msgs if m["role"] == "user"]
    assert len(user_msgs) <= 1
    # omitted 一定是正数(至少有 turn-limit 砍的部分,也可能包含 truncate 部分)
    assert omitted > 0
