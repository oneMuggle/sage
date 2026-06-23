"""memory_tool 单元测试：MemorySearchTool / MemorySaveTool

使用一个 fake memory manager 替代真实记忆系统。
"""

import pytest

from backend.tools.memory_tool import MemorySaveTool, MemorySearchTool

pytestmark = pytest.mark.unit


class _FakeMemoryManager:
    """简化的记忆管理器：记录每次 remember 调用并按需返回结果。"""

    def __init__(self, remember_return=None, raise_exc: Exception | None = None):
        self._return = remember_return if remember_return is not None else []
        self._raise = raise_exc
        self.calls: list[tuple] = []

    def remember(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._raise:
            raise self._raise
        return self._return


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
    """正常调用 memory_manager.remember 并返回限制后的结果"""
    fake = _FakeMemoryManager(remember_return=[{"id": 1}, {"id": 2}, {"id": 3}])
    tool = MemorySearchTool(memory_manager=fake)

    result = tool.execute(query="hello", memory_type="semantic", limit=2)

    assert result.success is True
    assert result.content["query"] == "hello"
    assert result.content["memory_type"] == "semantic"
    assert result.content["results"] == [{"id": 1}, {"id": 2}]

    # 验证 manager.remember 被调用且参数被正确转发
    assert len(fake.calls) == 1
    _, kwargs = fake.calls[0]
    assert kwargs["query"] == "hello"
    assert kwargs["context"]["memory_type_filter"] == "semantic"


def test_memory_search_empty_results_returns_empty_list():
    """remember 返回 None 时 results 为 []"""
    fake = _FakeMemoryManager(remember_return=None)
    tool = MemorySearchTool(memory_manager=fake)
    result = tool.execute(query="empty")
    assert result.success is True
    assert result.content["results"] == []


def test_memory_search_manager_exception_returns_failure():
    """remember 抛异常时工具捕获并返回失败"""
    fake = _FakeMemoryManager(raise_exc=RuntimeError("boom"))
    tool = MemorySearchTool(memory_manager=fake)
    result = tool.execute(query="oops")
    assert result.success is False
    assert "搜索记忆失败" in result.error
    assert "boom" in result.error


def test_memory_search_set_manager_late():
    """可以延迟设置 manager"""
    tool = MemorySearchTool()
    fake = _FakeMemoryManager(remember_return=[{"x": 1}])
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
    """正常保存：转发 content 与 importance/memory_type"""
    fake = _FakeMemoryManager(remember_return=None)
    tool = MemorySaveTool(memory_manager=fake)

    result = tool.execute(content="重要信息", importance=8, memory_type="semantic")

    assert result.success is True
    assert result.content["content_length"] == len("重要信息")
    assert result.content["importance"] == 8
    assert result.content["memory_type"] == "semantic"

    assert len(fake.calls) == 1
    args, _ = fake.calls[0]
    assert args[0] == "重要信息"
    assert args[1]["importance"] == 8
    assert args[1]["memory_type"] == "semantic"


def test_memory_save_default_importance_and_type():
    """默认 importance=5, memory_type=episodic"""
    fake = _FakeMemoryManager()
    tool = MemorySaveTool(memory_manager=fake)
    result = tool.execute(content="hi")
    assert result.success is True
    assert result.content["importance"] == 5
    assert result.content["memory_type"] == "episodic"


def test_memory_save_manager_exception_returns_failure():
    """remember 抛异常时返回失败"""
    fake = _FakeMemoryManager(raise_exc=ValueError("db down"))
    tool = MemorySaveTool(memory_manager=fake)
    result = tool.execute(content="payload")
    assert result.success is False
    assert "保存记忆失败" in result.error
    assert "db down" in result.error


def test_memory_save_set_manager_late():
    tool = MemorySaveTool()
    fake = _FakeMemoryManager()
    tool.set_memory_manager(fake)
    result = tool.execute(content="after set")
    assert result.success is True
