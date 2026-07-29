"""M2 todo_write 工具单元测试（含 todo_state 会话存储）。

全量替换语义、状态枚举校验、50 条上限、会话隔离（ContextVar）、
匿名桶兜底。
"""

from __future__ import annotations

import pytest

from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.todo_state import (
    ANONYMOUS_SESSION_ID,
    MAX_SESSION_BUCKETS,
    SessionStateStore,
    get_todo_store,
)
from backend.tools.todo_tool import MAX_TODO_ITEMS, TodoWriteTool

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_store():
    """每个测试前后清空全局 todo 存储，防跨测试泄漏。"""
    get_todo_store().clear()
    yield
    get_todo_store().clear()


def _ctx(session_id: str) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id="s1",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )


# ---------------------------------------------------------------------------
# 全量替换语义 + 渲染
# ---------------------------------------------------------------------------


def test_todo_write_stores_list_and_renders_markdown_checklist():
    """写入后返回 markdown checklist + 计数。"""
    # Arrange
    tool = TodoWriteTool()
    todos = [
        {"content": "调研方案", "status": "completed"},
        {"content": "写实现", "status": "in_progress", "activeForm": "正在写实现"},
        {"content": "补测试", "status": "pending"},
    ]

    # Act
    result = tool.execute(todos=todos)

    # Assert
    assert result.success is True
    checklist = result.content["checklist"]
    assert "- [x] 调研方案" in checklist
    assert "- [ ] 写实现（进行中）" in checklist
    assert "- [ ] 补测试" in checklist
    assert result.content["counts"] == {
        "pending": 1,
        "in_progress": 1,
        "completed": 1,
        "total": 3,
    }
    assert result.content["replaced_count"] == 0


def test_todo_write_uses_full_replace_semantics():
    """第二次调用整体替换列表（而非合并）。"""
    # Arrange
    tool = TodoWriteTool()
    tool.execute(todos=[{"content": "旧任务", "status": "pending"}])

    # Act
    result = tool.execute(todos=[{"content": "新任务", "status": "in_progress"}])

    # Assert
    assert result.content["replaced_count"] == 1
    stored = get_todo_store().get(ANONYMOUS_SESSION_ID)
    assert stored == [{"content": "新任务", "status": "in_progress"}]


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_status", ["done", "PENDING", "", "in-progress"])
def test_todo_write_rejects_invalid_status(bad_status):
    """status 必须严格在 pending/in_progress/completed 枚举内。"""
    # Act
    result = TodoWriteTool().execute(todos=[{"content": "x", "status": bad_status}])

    # Assert
    assert result.success is False
    assert "status" in result.error


@pytest.mark.parametrize("bad_content", ["", "   ", 123, None])
def test_todo_write_rejects_empty_or_nonstring_content(bad_content):
    """content 必须是非空字符串。"""
    # Act
    result = TodoWriteTool().execute(todos=[{"content": bad_content, "status": "pending"}])

    # Assert
    assert result.success is False
    assert "content" in result.error


def test_todo_write_enforces_max_50_items():
    """51 条 → 拒绝；恰好 50 条 → 通过。"""
    # Arrange
    tool = TodoWriteTool()
    make = lambda n: [{"content": f"t{i}", "status": "pending"} for i in range(n)]  # noqa: E731

    # Act / Assert
    over = tool.execute(todos=make(MAX_TODO_ITEMS + 1))
    assert over.success is False
    assert "超过上限" in over.error

    exact = tool.execute(todos=make(MAX_TODO_ITEMS))
    assert exact.success is True
    assert exact.content["counts"]["total"] == MAX_TODO_ITEMS


def test_todo_write_rejects_non_list_todos():
    """todos 非数组 → 干净错误。"""
    # Act / Assert
    for bad in (None, {"content": "x"}, "todo"):
        result = TodoWriteTool().execute(todos=bad)
        assert result.success is False
        assert "todos 必须是数组" in result.error


def test_todo_write_rejects_empty_list():
    """空列表 → 拒绝（与 claw-code validate_todos 一致）。"""
    # Act
    result = TodoWriteTool().execute(todos=[])

    # Assert
    assert result.success is False
    assert "不能为空" in result.error


def test_todo_write_rejects_non_dict_item():
    """条目非对象 → 报错含下标定位。"""
    # Act
    result = TodoWriteTool().execute(todos=["just a string"])

    # Assert
    assert result.success is False
    assert "todos[0]" in result.error


def test_todo_write_rejects_non_string_active_form():
    """activeForm 提供时必须是字符串（可选字段）。"""
    # Act
    result = TodoWriteTool().execute(
        todos=[{"content": "x", "status": "pending", "activeForm": 42}]
    )

    # Assert
    assert result.success is False
    assert "activeForm" in result.error


def test_todo_write_multiple_validation_errors_joined():
    """多个条目同时非法 → 错误消息分号拼接。"""
    # Act
    result = TodoWriteTool().execute(
        todos=[
            {"content": "", "status": "pending"},
            {"content": "ok", "status": "bogus"},
        ]
    )

    # Assert
    assert result.success is False
    assert "todos[0]" in result.error
    assert "todos[1]" in result.error


# ---------------------------------------------------------------------------
# 会话隔离
# ---------------------------------------------------------------------------


def test_todo_sessions_isolated_by_context_session_id():
    """不同 session_id 的 ToolExecutionContext → 独立 todo 桶。"""
    # Arrange
    tool = TodoWriteTool()
    token_a = set_tool_context(_ctx("session-a"))
    try:
        tool.execute(todos=[{"content": "A 的任务", "status": "pending"}])
    finally:
        reset_tool_context(token_a)

    token_b = set_tool_context(_ctx("session-b"))
    try:
        result_b = tool.execute(todos=[{"content": "B 的任务", "status": "in_progress"}])
        stored_b = get_todo_store().get("session-b")
    finally:
        reset_tool_context(token_b)

    # Assert
    assert result_b.content["session_id"] == "session-b"
    assert stored_b == [{"content": "B 的任务", "status": "in_progress"}]
    # A 的桶未被 B 的写入污染
    assert get_todo_store().get("session-a") == [{"content": "A 的任务", "status": "pending"}]


def test_todo_falls_back_to_anonymous_bucket_without_context():
    """无上下文 → 单一匿名桶。"""
    # Arrange / Act
    result = TodoWriteTool().execute(todos=[{"content": "匿名", "status": "pending"}])

    # Assert
    assert result.content["session_id"] == ANONYMOUS_SESSION_ID
    assert get_todo_store().get(ANONYMOUS_SESSION_ID)[0]["content"] == "匿名"


# ---------------------------------------------------------------------------
# todo_state 存储行为
# ---------------------------------------------------------------------------


def test_todo_store_returns_defensive_copies():
    """get 返回副本：调用方修改不影响存储内部。"""
    # Arrange
    store = get_todo_store()
    store.replace("s", [{"content": "x", "status": "pending"}])

    # Act
    fetched = store.get("s")
    fetched[0]["content"] = "tampered"

    # Assert
    assert store.get("s")[0]["content"] == "x"


def test_todo_store_clear_single_bucket():
    """clear(session_id) 只清指定桶。"""
    # Arrange
    store = get_todo_store()
    store.replace("keep", [{"content": "k", "status": "pending"}])
    store.replace("drop", [{"content": "d", "status": "pending"}])

    # Act
    store.clear("drop")

    # Assert
    assert store.get("drop") is None
    assert store.get("keep") is not None


# ---------------------------------------------------------------------------
# FIX-7: LRU 淘汰上限
# ---------------------------------------------------------------------------


def test_todo_store_lru_evicts_oldest_beyond_cap():
    """300 个会话只留 256：最旧淘汰，近期访问过的幸存者保留。"""
    # Arrange: 写满上限（256）个桶
    store = SessionStateStore()
    make = lambda i: [{"content": f"t{i}", "status": "pending"}]  # noqa: E731
    for i in range(MAX_SESSION_BUCKETS):
        store.replace(f"s{i}", make(i))

    # Act: 刷新 s0（get 计为 LRU 访问），再写入 44 个新会话触发溢出淘汰
    assert store.get("s0") is not None
    for i in range(MAX_SESSION_BUCKETS, MAX_SESSION_BUCKETS + 44):
        store.replace(f"s{i}", make(i))

    # Assert —— 总数恒在上限
    remaining = sum(
        1 for i in range(MAX_SESSION_BUCKETS + 44) if store.get(f"s{i}") is not None
    )
    assert remaining == MAX_SESSION_BUCKETS
    # s0 未刷新时会是最旧桶（第一个被淘汰）；刷新后幸存
    assert store.get("s0") is not None
    # s1 成为实际最旧桶，被淘汰
    assert store.get("s1") is None


def test_todo_store_replace_existing_key_does_not_grow():
    """重复替换同一会话不增加桶数（move_to_end 而非新增）。"""
    # Arrange
    store = SessionStateStore(max_buckets=4)
    for i in range(4):
        store.replace(f"s{i}", [{"content": f"t{i}", "status": "pending"}])

    # Act: 对已有键再替换 10 次
    for _ in range(10):
        store.replace("s0", [{"content": "refreshed", "status": "completed"}])

    # Assert: 桶数不变，其他会话未被误淘汰
    for i in range(4):
        assert store.get(f"s{i}") is not None


# ---------------------------------------------------------------------------
# FIX-2: 未知参数拒绝
# ---------------------------------------------------------------------------


def test_todo_write_rejects_unknown_kwargs():
    """FIX-2 回归：拼错的参数名 → 干净错误。"""
    # Act —— 模拟 LLM 把 todos 拼成 todo
    result = TodoWriteTool().execute(todo=[{"content": "x", "status": "pending"}])

    # Assert
    assert result.success is False
    assert "未知参数" in result.error
    assert "todo" in result.error
