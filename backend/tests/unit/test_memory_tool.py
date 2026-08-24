"""memory_tool 单元测试：MemorySearchTool / MemorySaveTool

Win7 parity 修复（Task 2）后：
- MemorySaveTool 直接调 ``MemoryManager.memorize``，不包 event loop。
- MemorySearchTool 调 ``MemoryManager.search_memories``，把 ``'all'`` 映射成
  ``None``，并 clamp ``limit`` 到 ``[1, 100]``。

旧的 ``_FakeMemoryManager.remember`` 已废弃，本测试改用 ``_FakeMemoryManager``
exposing ``memorize`` / ``search_memories`` 两个 sync 方法。``remember`` 仍
存在（向后兼容 back-compat）但工具不应再调用它。
"""

from __future__ import annotations

from typing import List, Optional

import pytest

import backend.tools.memory_tool as memory_tool_module
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.memory_tool import MemorySaveTool, MemorySearchTool

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _trusted_context():
    token = set_tool_context(
        ToolExecutionContext(
            session_id="sess-test",
            stream_id="stream-test",
            binding_generation=0,
            office_doc_scope=frozenset(),
        )
    )
    try:
        yield
    finally:
        reset_tool_context(token)


class _FakeMemoryManager:
    """同步 fake 记忆管理器：记录 memorize / search_memories 调用。

    提供 ``raise_exc`` 让测试触发 manager 异常路径（替代旧的 async remember
    注入）。``remember`` 保留只是为防止未来 regression 把工具切回去。
    """

    def __init__(
        self,
        memorize_return: Optional[str] = "mem-1",
        search_return: Optional[List[dict]] = None,
        raise_exc: Optional[Exception] = None,
    ) -> None:
        self.memorize_calls: List[tuple] = []
        self.search_memories_calls: List[tuple] = []
        self._memorize_return = memorize_return
        self._search_return = search_return if search_return is not None else []
        self._raise = raise_exc

    def memorize(self, *args, **kwargs):
        if self._raise:
            raise self._raise
        self.memorize_calls.append((args, kwargs))
        return self._memorize_return

    def search_memories(self, *args, **kwargs):
        if self._raise:
            raise self._raise
        self.search_memories_calls.append((args, kwargs))
        return list(self._search_return)


# ---------- MemorySearchTool ----------


def test_memory_search_schema():
    tool = MemorySearchTool()
    schema = tool.schema
    assert schema.name == "memory_search"
    assert "query" in schema.parameters["properties"]
    assert schema.parameters["required"] == ["query"]


def test_memory_search_without_manager_fails():
    """memory_manager 未设置 → 返回错误"""
    tool = MemorySearchTool()
    result = tool.execute(query="anything")
    assert result.success is False
    assert "未初始化" in result.error


def test_memory_search_success_with_results():
    """正常调用 ``search_memories`` 并返回结果。"""
    fake = _FakeMemoryManager(search_return=[{"id": 1}, {"id": 2}, {"id": 3}])
    tool = MemorySearchTool(memory_manager=fake)

    result = tool.execute(query="hello", memory_type="semantic", limit=2)

    assert result.success is True
    assert result.content["query"] == "hello"
    assert result.content["memory_type"] == "semantic"
    assert result.content["results"] == [{"id": 1}, {"id": 2}]
    # 默认 limit=20 时 tools 内部把 limit=2 直接转发
    assert len(fake.search_memories_calls) == 1
    args, _ = fake.search_memories_calls[0]
    assert args[0] == "hello"
    # 'semantic' 不是 'all', 原样转发
    assert args[1] == "semantic"
    assert args[2] == 2


def test_memory_search_empty_results_returns_empty_list():
    """``search_memories`` 返回空列表时 ``results`` 为 ``[]``。"""
    fake = _FakeMemoryManager(search_return=[])
    tool = MemorySearchTool(memory_manager=fake)
    result = tool.execute(query="empty")
    assert result.success is True
    assert result.content["results"] == []


def test_memory_search_manager_exception_returns_failure():
    """manager 抛异常时工具捕获并返回失败"""
    fake = _FakeMemoryManager(raise_exc=RuntimeError("boom"))
    tool = MemorySearchTool(memory_manager=fake)
    result = tool.execute(query="oops")
    assert result.success is False
    assert "搜索记忆失败" in result.error
    assert "boom" in result.error


def test_memory_search_set_manager_late():
    """可以延迟设置 manager"""
    tool = MemorySearchTool()
    fake = _FakeMemoryManager(search_return=[{"x": 1}])
    tool.set_memory_manager(fake)
    result = tool.execute(query="late")
    assert result.success is True
    assert result.content["results"] == [{"x": 1}]


# ---------- MemorySaveTool ----------


def test_memory_save_schema():
    tool = MemorySaveTool()
    schema = tool.schema
    assert schema.name == "memory_save"
    assert "content" in schema.parameters["properties"]
    assert schema.parameters["required"] == ["content"]


def test_memory_save_without_manager_fails():
    tool = MemorySaveTool()
    result = tool.execute(content="some fact")
    assert result.success is False
    assert "未初始化" in result.error


def test_memory_save_success_calls_manager_with_meta():
    """正常保存：``memorize`` 被调用且参数正确转发。"""
    fake = _FakeMemoryManager(memorize_return="mem-x")
    tool = MemorySaveTool(memory_manager=fake)

    result = tool.execute(content="重要信息", importance=8, memory_type="semantic")

    assert result.success is True
    assert result.output == "mem-x"
    assert result.content["content_length"] == len("重要信息")
    assert result.content["importance"] == 8
    assert result.content["memory_type"] == "semantic"

    assert len(fake.memorize_calls) == 1
    args, kwargs = fake.memorize_calls[0]
    assert args[0] == "重要信息"
    assert args[1] == "semantic"
    assert args[2] == 8
    assert args[3] is None  # 默认 tags=None
    assert kwargs["session_id"] == "sess-test"


def test_memory_save_default_importance_and_type():
    """默认 importance=5, memory_type=episodic"""
    fake = _FakeMemoryManager()
    tool = MemorySaveTool(memory_manager=fake)
    result = tool.execute(content="hi")
    assert result.success is True
    assert result.output == "mem-1"
    assert result.content["importance"] == 5
    assert result.content["memory_type"] == "episodic"


def test_memory_save_manager_exception_returns_failure():
    """manager 抛异常时返回失败"""
    fake = _FakeMemoryManager(raise_exc=ValueError("db down"))
    tool = MemorySaveTool(memory_manager=fake)
    result = tool.execute(content="payload")
    assert result.success is False
    assert "保存记忆失败" in result.error
    assert "db down" in result.error


def test_memory_save_set_manager_late():
    tool = MemorySaveTool()
    fake = _FakeMemoryManager(memorize_return="mem-late")
    tool.set_memory_manager(fake)
    result = tool.execute(content="after set")
    assert result.success is True
    assert result.output == "mem-late"


# ---------- Task 2: New contract — memorize / search_memories ----------
#
# The Win7 packaged backend logs proved the old implementation is broken:
#  - ``MemorySaveTool.execute`` ran ``new_event_loop().run_until_complete()``
#    against a non-coroutine return value → "cannot run the event loop while
#    another loop is running".
#  - ``MemorySearchTool.execute`` called ``self.memory.remember(query=...)``
#    → TypeError (no such kwarg on ``remember``).
#
# New contract: tools speak the synchronous ``memorize()`` /
# ``search_memories()`` API exposed by ``MemoryManager``.


def test_memory_save_tool_uses_memorize_without_event_loop(real_memory_manager):
    """MemorySaveTool must call ``memorize(...)`` synchronously.

    The brief pins: ``self.memory.memorize(content, memory_type, importance,
    tags, session_id=session_id)``. The tool must NOT spin a private event
    loop (which was the source of the Win7 RuntimeError).
    """
    result = MemorySaveTool(memory=real_memory_manager).execute(
        content="user prefers UTC+8",
        memory_type="episodic",
        importance=5,
        tags=[],
        session_id="sess-test",
    )
    assert result.success is True
    # output is the actual memory ID — surfaced for the LLM tool loop.
    assert result.output
    real_memory_manager.memorize.assert_called_once_with(
        "user prefers UTC+8",
        "episodic",
        5,
        [],
        session_id="sess-test",
    )


def test_memory_search_tool_calls_search_memories_not_remember(memory_manager_spy):
    """MemorySearchTool must call ``search_memories`` (not ``remember``).

    The brief pins: ``MemoryManager.search_memories(query, memory_type=None,
    limit=20)``. ``memory_type='all'`` must be normalised to ``None``.
    """
    MemorySearchTool(memory=memory_manager_spy).execute(
        query="UTC", memory_type="all", limit=5
    )
    memory_manager_spy.search_memories.assert_called_once_with(
        "UTC", None, 5, session_id="sess-test"
    )


def test_memory_search_tool_maps_all_to_none_and_clamps_limit(memory_manager_spy):
    """Out-of-range ``limit`` must be clamped to ``[1, 100]``.

    ``memory_type='all'`` and empty strings must also normalise to ``None``.
    """
    MemorySearchTool(memory=memory_manager_spy).execute(
        query="x", memory_type="all", limit=999
    )
    memory_manager_spy.search_memories.assert_called_once_with(
        "x", None, 100, session_id="sess-test"
    )


def test_memory_search_tool_normalises_empty_string_type(memory_manager_spy):
    """Empty-string ``memory_type`` (e.g. from optional IPC field) → ``None``."""
    MemorySearchTool(memory=memory_manager_spy).execute(
        query="x", memory_type="", limit=3
    )
    memory_manager_spy.search_memories.assert_called_once_with(
        "x", None, 3, session_id="sess-test"
    )


def test_memory_search_tool_clamps_limit_to_min_one(memory_manager_spy):
    """``limit < 1`` must be clamped up to 1 (avoid ``LIMIT 0`` silent)."""
    MemorySearchTool(memory=memory_manager_spy).execute(
        query="x", memory_type="all", limit=0
    )
    memory_manager_spy.search_memories.assert_called_once_with(
        "x", None, 1, session_id="sess-test"
    )


def test_memory_search_tool_passes_through_specific_type(memory_manager_spy):
    """Non-``all`` ``memory_type`` (e.g. ``episodic``) is forwarded unchanged."""
    MemorySearchTool(memory=memory_manager_spy).execute(
        query="x", memory_type="episodic", limit=2
    )
    memory_manager_spy.search_memories.assert_called_once_with(
        "x", "episodic", 2, session_id="sess-test"
    )


def test_memory_search_rejects_without_trusted_context(memory_manager_spy, monkeypatch):
    monkeypatch.setattr(memory_tool_module, "current_tool_context", lambda: None)

    result = MemorySearchTool(memory=memory_manager_spy).execute(query="x")

    assert result.success is False
    assert "可信会话上下文" in result.error
    memory_manager_spy.search_memories.assert_not_called()


def test_memory_save_rejects_explicit_session_without_trusted_context(
    real_memory_manager, monkeypatch
):
    monkeypatch.setattr(memory_tool_module, "current_tool_context", lambda: None)

    result = MemorySaveTool(memory=real_memory_manager).execute(
        content="x", session_id="sess-explicit"
    )

    assert result.success is False
    assert "可信会话上下文" in result.error
    real_memory_manager.memorize.assert_not_called()


def test_memory_save_rejects_session_mismatch(real_memory_manager):
    result = MemorySaveTool(memory=real_memory_manager).execute(
        content="x", session_id="sess-other"
    )

    assert result.success is False
    assert "不一致" in result.error
    real_memory_manager.memorize.assert_not_called()


def test_memory_tools_reject_unsupported_types(memory_manager_spy, real_memory_manager):
    search_result = MemorySearchTool(memory=memory_manager_spy).execute(
        query="x", memory_type="unknown"
    )
    save_result = MemorySaveTool(memory=real_memory_manager).execute(
        content="x", memory_type="unknown"
    )

    assert search_result.success is False
    assert "不支持" in search_result.error
    assert save_result.success is False
    assert "不支持" in save_result.error
    memory_manager_spy.search_memories.assert_not_called()
    real_memory_manager.memorize.assert_not_called()


def test_memory_save_returns_failure_when_manager_returns_no_id(real_memory_manager):
    real_memory_manager.memorize.return_value = None

    result = MemorySaveTool(memory=real_memory_manager).execute(content="x")

    assert result.success is False
    assert "未返回记忆 ID" in result.error
    assert result.output is None


def test_memory_search_filters_results_from_other_sessions(memory_manager_spy):
    memory_manager_spy.search_memories.return_value = [
        {"id": "same", "session_id": "sess-test"},
        {"id": "legacy-no-session"},
        {"id": "other", "session_id": "sess-other"},
    ]

    result = MemorySearchTool(memory=memory_manager_spy).execute(query="x")

    assert result.success is True
    assert result.output == [
        {"id": "same", "session_id": "sess-test"},
        {"id": "legacy-no-session"},
    ]


# ---------- pytest fixtures used by the contract tests ----------


@pytest.fixture()
def real_memory_manager(monkeypatch):
    """Spy whose ``memorize`` returns a stable memory ID and records calls.

    The brief's test pins ``real_memory_manager.memorize.assert_called_once_with(...)``,
    so this fixture exposes a real ``MagicMock``-style spy rather than a hand-
    written recorder.
    """
    from unittest.mock import MagicMock

    spy = MagicMock()
    spy.memorize.return_value = "mem-real"
    return spy


@pytest.fixture()
def memory_manager_spy():
    """``MagicMock`` whose ``search_memories`` returns ``[]`` by default.

    Using ``MagicMock`` (not hand-rolled recorder) so tests can call
    ``assert_called_once_with`` / ``assert_not_called`` directly.
    """
    from unittest.mock import MagicMock

    spy = MagicMock()
    spy.search_memories.return_value = []
    spy.memorize.return_value = "mem-1"
    return spy
