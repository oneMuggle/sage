"""ToolRegistry 单元测试

覆盖工具注册/取消注册/查询/列举/LLM schema 导出等。
"""

import pytest

from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.registry import ToolRegistry

pytestmark = pytest.mark.unit


class _DummyTool(BaseTool):
    """测试用最小工具"""

    def __init__(self, name: str = "dummy", description: str = "dummy tool"):
        super().__init__()
        self._n = name
        self._d = description

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._n,
            description=self._d,
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, content={"ok": True})


# ---------- 注册 / 获取 ----------


def test_registry_register_and_get():
    reg = ToolRegistry()
    tool = _DummyTool(name="alpha")
    reg.register(tool)

    assert reg.get("alpha") is tool
    assert reg.exists("alpha") is True


def test_registry_get_missing_returns_none():
    reg = ToolRegistry()
    assert reg.get("ghost") is None
    assert reg.exists("ghost") is False


def test_registry_duplicate_registration_overwrites_and_warns(caplog):
    reg = ToolRegistry()
    t1 = _DummyTool(name="dup", description="first")
    t2 = _DummyTool(name="dup", description="second")

    reg.register(t1)
    with caplog.at_level("WARNING", logger="backend.tools.registry"):
        reg.register(t2)

    assert reg.get("dup") is t2
    # 警告日志被发出
    assert any("已存在" in rec.message for rec in caplog.records)


def test_registry_unregister_existing():
    reg = ToolRegistry()
    reg.register(_DummyTool(name="temp"))
    assert reg.unregister("temp") is True
    assert reg.get("temp") is None


def test_registry_unregister_missing():
    reg = ToolRegistry()
    assert reg.unregister("nope") is False


# ---------- list / list_names / clear ----------


def test_registry_list_returns_schemas():
    reg = ToolRegistry()
    reg.register(_DummyTool(name="a"))
    reg.register(_DummyTool(name="b"))

    schemas = reg.list()
    assert len(schemas) == 2
    names = {s.name for s in schemas}
    assert names == {"a", "b"}
    assert all(isinstance(s, ToolSchema) for s in schemas)


def test_registry_list_names():
    reg = ToolRegistry()
    reg.register(_DummyTool(name="x"))
    reg.register(_DummyTool(name="y"))

    names = reg.list_names()
    assert set(names) == {"x", "y"}


def test_registry_clear_removes_all():
    reg = ToolRegistry()
    reg.register(_DummyTool(name="a"))
    reg.register(_DummyTool(name="b"))
    reg.clear()

    assert reg.list_names() == []
    assert reg.get("a") is None


# ---------- LLM schema 导出 ----------


def test_registry_get_schemas_for_llm():
    reg = ToolRegistry()
    reg.register(_DummyTool(name="llm_tool", description="for LLM"))

    schemas = reg.get_schemas_for_llm()
    assert len(schemas) == 1
    s = schemas[0]
    assert s["name"] == "llm_tool"
    assert s["description"] == "for LLM"
    assert "parameters" in s
    assert s["parameters"]["type"] == "object"


def test_registry_get_schemas_for_llm_empty():
    reg = ToolRegistry()
    assert reg.get_schemas_for_llm() == []


# ---------- register_all_tools 集成 ----------


def test_register_all_tools_registers_builtin_set():
    """register_all_tools 注册所有内置工具"""
    from backend.tools import register_all_tools

    reg = ToolRegistry()
    register_all_tools(reg)

    expected = {
        "terminal",
        "read_file",
        "write_file",
        "list_dir",
        "web_search",
        "web_fetch",
        "calculator",
        "memory_search",
        "memory_save",
    }
    assert expected.issubset(set(reg.list_names()))


# ---------- base.py 覆盖：ToolResult.to_dict / BaseTool.__repr__ ----------


def test_tool_result_to_dict_success_only():
    """ToolResult(success=True) 的 to_dict 仅含 success"""
    r = ToolResult(success=True)
    assert r.to_dict() == {"success": True}


def test_tool_result_to_dict_with_content():
    """to_dict 携带 content 字段"""
    r = ToolResult(success=True, content={"k": "v"})
    d = r.to_dict()
    assert d["success"] is True
    assert d["content"] == {"k": "v"}
    assert "error" not in d


def test_tool_result_to_dict_with_error():
    """to_dict 携带 error 字段"""
    r = ToolResult(success=False, error="bad")
    d = r.to_dict()
    assert d == {"success": False, "error": "bad"}


def test_tool_result_to_dict_with_content_and_error():
    """同时携带 content + error"""
    r = ToolResult(success=False, content="partial", error="warn")
    d = r.to_dict()
    assert d["success"] is False
    assert d["content"] == "partial"
    assert d["error"] == "warn"


def test_base_tool_repr_includes_name():
    """BaseTool.__repr__ 包含类名与工具名"""
    tool = _DummyTool(name="reprtool")
    text = repr(tool)
    assert "_DummyTool" in text
    assert "reprtool" in text
