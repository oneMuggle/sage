"""验证 ``InprocToolAdapter`` 行为。

覆盖：
- ``list_tools`` 把 ``ToolSchema`` 转成 ``ToolSpec``，parameters 透传
- ``execute`` 委派到 ``tool.execute(**args)`` 并做 ``ToolResult`` 转换
- 工具未注册时返回 ``success=False``，不抛异常
- 工具执行抛异常时同样被收敛为 ``success=False``
- ``InprocToolAdapter`` 满足 ``ToolPort`` 协议（结构化子类型）
- 缺省构造（无 registry）也能跑
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.domain.tool import ToolResult, ToolSpec
from backend.ports.tool import ToolPort

pytestmark = pytest.mark.unit


# ============================================================================
# 1) list_tools —— Schema -> Spec 转换
# ============================================================================


def test_list_tools_returns_specs_from_mock_registry() -> None:
    """list_tools 把 ToolSchema 转成 ToolSpec 列表，参数原样透传。"""
    # Arrange: 构造一个 mock tool 暴露 name/description/parameters
    mock_tool = type("FakeTool", (), {})()
    mock_tool.name = "calculator"
    mock_tool.description = "Math operations"
    mock_tool.parameters = {
        "type": "object",
        "properties": {"expression": {"type": "string"}},
    }

    mock_registry = type("FakeRegistry", (), {})()
    mock_registry.list = lambda: [  # type: ignore[method-assign]
        type(
            "FakeSchema",
            (),
            {
                "name": "calculator",
                "description": "Math operations",
                "parameters": mock_tool.parameters,
            },
        )()
    ]

    adapter = InprocToolAdapter(registry=mock_registry)  # type: ignore[arg-type]

    # Act
    tools = adapter.list_tools()

    # Assert
    assert len(tools) == 1
    spec = tools[0]
    assert isinstance(spec, ToolSpec)
    assert spec.name == "calculator"
    assert spec.description == "Math operations"
    assert spec.parameters == {
        "type": "object",
        "properties": {"expression": {"type": "string"}},
    }


def test_list_tools_empty_registry_returns_empty_list() -> None:
    """空 registry 返回空列表。"""
    mock_registry = type("FakeRegistry", (), {})()
    mock_registry.list = lambda: []  # type: ignore[method-assign]

    adapter = InprocToolAdapter(registry=mock_registry)  # type: ignore[arg-type]
    assert adapter.list_tools() == []


# ============================================================================
# 2) execute —— 委派与 ToolResult 转换
# ============================================================================


class _FakeRawResult:
    """模拟 backend.tools.base.ToolResult。"""

    def __init__(
        self,
        success: bool,
        content: Any = None,
        error: str | None = None,
    ) -> None:
        self.success = success
        self.content = content
        self.error = error


class _FakeTool:
    """模拟 BaseTool。"""

    def __init__(
        self,
        name: str,
        raw: _FakeRawResult | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._name = name
        self._raw = raw
        self._raise = raise_exc
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    def execute(self, **kwargs: Any) -> _FakeRawResult:
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        assert self._raw is not None
        return self._raw


def _make_registry(tools: dict[str, _FakeTool]) -> Any:
    """构造一个最简 registry：暴露 ``get``/``list``，兼容 adapter 期望。"""

    class _Reg:
        def get(self, name: str) -> _FakeTool | None:
            return tools.get(name)

        def list(self):  # type: ignore[no-untyped-def]
            return []

    return _Reg()


async def test_execute_delegates_to_tool_and_converts_result() -> None:
    """成功路径：execute(**args) 委派，content -> output，error=None。"""
    fake_tool = _FakeTool(
        "calculator",
        raw=_FakeRawResult(success=True, content=42, error=None),
    )
    registry = _make_registry({"calculator": fake_tool})
    adapter = InprocToolAdapter(registry=registry)  # type: ignore[arg-type]

    result = await adapter.execute("calculator", {"expression": "2+2"})

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.output == "42"  # content 走 str()
    assert result.error is None
    assert result.metadata is None
    # 委派语义
    assert fake_tool.calls == [{"expression": "2+2"}]


async def test_execute_failure_passes_error_through() -> None:
    """失败路径：error 透传，output 为空。"""
    fake_tool = _FakeTool(
        "calculator",
        raw=_FakeRawResult(success=False, content=None, error="Invalid input"),
    )
    registry = _make_registry({"calculator": fake_tool})
    adapter = InprocToolAdapter(registry=registry)  # type: ignore[arg-type]

    result = await adapter.execute("calculator", {})

    assert result.success is False
    assert result.output == ""
    assert result.error == "Invalid input"
    assert result.metadata is None


async def test_execute_unknown_tool_returns_success_false() -> None:
    """工具未注册：返回 success=False 而不抛异常。"""
    registry = _make_registry({})  # 空 registry
    adapter = InprocToolAdapter(registry=registry)  # type: ignore[arg-type]

    result = await adapter.execute("nope", {"x": 1})

    assert result.success is False
    assert result.output == ""
    assert result.error is not None
    assert "nope" in result.error
    assert result.metadata is None


async def test_execute_tool_exception_is_caught() -> None:
    """工具内部抛异常时被收敛为 success=False。"""
    fake_tool = _FakeTool("boom", raise_exc=RuntimeError("kaboom"))
    registry = _make_registry({"boom": fake_tool})
    adapter = InprocToolAdapter(registry=registry)  # type: ignore[arg-type]

    result = await adapter.execute("boom", {})

    assert result.success is False
    assert result.output == ""
    assert result.error is not None
    assert "kaboom" in result.error
    assert "RuntimeError" in result.error


# ============================================================================
# 3) 结构化子类型 —— 满足 ToolPort 协议
# ============================================================================


def test_satisfies_tool_port_protocol() -> None:
    """``InprocToolAdapter`` 满足 ``ToolPort``（结构化子类型）。"""
    registry = _make_registry({})
    adapter = InprocToolAdapter(registry=registry)  # type: ignore[arg-type]
    # 静态类型断言：把 adapter 赋值给 ToolPort 标注的变量
    port: ToolPort = adapter
    assert port is adapter


# ============================================================================
# 4) 缺省构造
# ============================================================================


def test_default_registry_is_used_when_none_provided() -> None:
    """不传 registry 时使用新建的 ``ToolRegistry()`` 并自动注册内置工具 (含 MCP)。

    drawio MCP 集成后 ``InprocToolAdapter.__init__`` 会在 ``registry is None``
    分支自动调用 ``register_all_tools()``, 因此 list_tools 不为空。
    本测试只断言: (a) 不传 registry 也不抛异常, (b) 至少有 builtin 工具被注册。
    """
    adapter = InprocToolAdapter()
    names = {t.name for t in adapter.list_tools()}
    # 至少包含 builtin 工具 (calculator 永远在, 不依赖 MCP)
    assert "calculator" in names
    # web_search 也是 builtin
    assert "web_search" in names


async def test_default_registry_execute_unknown_tool() -> None:
    """缺省 registry 调未注册工具也按契约返回失败结果。"""
    adapter = InprocToolAdapter()
    result = await adapter.execute("nope", {})
    assert result.success is False
    assert "nope" in (result.error or "")
