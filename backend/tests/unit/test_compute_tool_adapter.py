"""``backend.adapters.out.tool.compute_tool_adapter`` 单测。

覆盖:

- list_tools 合并 inner + compute(顺序 inner-first)
- execute 路由分发(compute 工具 → ComputePort,其他 → inner)
- ComputeResult → ToolResult 翻译(success / failure / metadata)
- ComputePort 抛异常时降级为 ToolResult.success=False(不冒泡)
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sage_core import (
    ComputeError,
    ComputeErrorType,
    ComputeResult,
    ComputeSpec,
    ToolResult,
    ToolSpec,
)

from backend.adapters.out.compute.mock_adapter import MockComputeAdapter
from backend.adapters.out.tool.compute_tool_adapter import (
    ComputeToolAdapter,
    _compute_result_to_tool_result,
)
from backend.domain.tool_policy import ToolPolicy

# ---------- inner ToolPort 假实现(仅满足结构化协议) ----------


class _FakeInnerTool:
    """模拟 InprocToolAdapter,记录 execute 调用便于断言。"""

    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._specs = list(specs or [])
        self.execute_calls: list[tuple[str, dict[str, Any]]] = []
        self.preset_result = ToolResult(
            success=True, output="inner result", error=None, metadata=None
        )

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs)

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        self.execute_calls.append((name, args))
        return self.preset_result


# ---------- list_tools 合并 ----------


def test_list_tools_merges_inner_and_compute() -> None:
    """合并 inner + compute,inner 在前。"""
    inner = _FakeInnerTool(specs=[ToolSpec(name="terminal", description="run shell")])
    compute = MockComputeAdapter(
        specs=[
            ComputeSpec(
                name="compute_shock",
                description="正激波计算",
                params_schema={"type": "object"},
            ),
            ComputeSpec(
                name="compute_equilibrium",
                description="平衡气体",
                params_schema={"type": "object"},
            ),
        ],
    )

    adapter = ComputeToolAdapter(compute=compute, inner=inner)
    tools = adapter.list_tools()

    assert [t.name for t in tools] == [
        "terminal",
        "compute_shock",
        "compute_equilibrium",
    ]


def test_list_tools_empty_compute() -> None:
    """compute 为空时,仅返回 inner 工具。"""
    inner = _FakeInnerTool(specs=[ToolSpec(name="x", description="x")])
    compute = MockComputeAdapter()

    adapter = ComputeToolAdapter(compute=compute, inner=inner)

    assert [t.name for t in adapter.list_tools()] == ["x"]


def test_tool_spec_carries_params_schema() -> None:
    """ComputeSpec.params_schema 应透传为 ToolSpec.parameters。"""
    schema = {"type": "object", "required": ["mach"]}
    compute = MockComputeAdapter(
        specs=[
            ComputeSpec(
                name="compute_shock",
                description="d",
                params_schema=schema,
            )
        ]
    )

    adapter = ComputeToolAdapter(compute=compute, inner=_FakeInnerTool())
    spec = adapter.list_tools()[0]

    assert spec.parameters == schema


# ---------- execute 路由分发 ----------


@pytest.mark.asyncio()
async def test_execute_routes_compute_tool() -> None:
    """compute 工具应走 ComputePort.execute。"""
    compute = MockComputeAdapter(
        specs=[ComputeSpec(name="compute_shock", description="d")],
        responses={
            "compute_shock": ComputeResult(
                success=True,
                output={"p2": 51000},
                duration_ms=600,
                exit_code=0,
            )
        },
    )
    inner = _FakeInnerTool()
    adapter = ComputeToolAdapter(compute=compute, inner=inner)

    result = await adapter.execute("compute_shock", {"mach": 6.5})

    assert result.success is True
    assert json.loads(result.output) == {"p2": 51000}
    assert inner.execute_calls == []  # inner 不应被调用
    assert len(compute.calls) == 1
    assert compute.calls[0].operation == "compute_shock"
    assert compute.calls[0].params == {"mach": 6.5}


@pytest.mark.asyncio()
async def test_execute_routes_inner_tool() -> None:
    """非 compute 工具应委托给 inner.execute。"""
    compute = MockComputeAdapter(specs=[ComputeSpec(name="compute_shock", description="d")])
    inner = _FakeInnerTool(specs=[ToolSpec(name="terminal", description="d")])
    adapter = ComputeToolAdapter(compute=compute, inner=inner)

    result = await adapter.execute("terminal", {"cmd": "ls"})

    assert result.success is True
    assert result.output == "inner result"
    assert inner.execute_calls == [("terminal", {"cmd": "ls"})]
    assert compute.calls == []


# ---------- ComputeResult → ToolResult 翻译 ----------


@pytest.mark.asyncio()
async def test_success_result_serializes_output_as_json() -> None:
    """success → output 应是 JSON 序列化字符串。"""
    compute = MockComputeAdapter(
        specs=[ComputeSpec(name="x", description="x")],
        responses={
            "x": ComputeResult(
                success=True,
                output={"a": 1, "b": [2, 3]},
                duration_ms=42,
                exit_code=0,
            )
        },
    )
    adapter = ComputeToolAdapter(compute=compute, inner=_FakeInnerTool())

    result = await adapter.execute("x", {})

    assert result.success is True
    parsed = json.loads(result.output)
    assert parsed == {"a": 1, "b": [2, 3]}
    assert result.error is None


@pytest.mark.asyncio()
async def test_failure_result_carries_error_message() -> None:
    """failure → error 应为 ComputeError.message。"""
    compute = MockComputeAdapter(
        specs=[ComputeSpec(name="x", description="x")],
        responses={
            "x": ComputeResult(
                success=False,
                exit_code=2,
                raw_stdout="partial output",
                error=ComputeError(
                    type=ComputeErrorType.INVALID_PARAMS,
                    message="bad mach value",
                ),
            )
        },
    )
    adapter = ComputeToolAdapter(compute=compute, inner=_FakeInnerTool())

    result = await adapter.execute("x", {})

    assert result.success is False
    assert result.error == "bad mach value"
    assert result.output == "partial output"
    assert result.metadata is not None
    assert result.metadata["error_type"] == "invalid_params"
    assert result.metadata["exit_code"] == 2


@pytest.mark.asyncio()
async def test_metadata_includes_duration() -> None:
    """metadata 必须包含 duration_ms。"""
    compute = MockComputeAdapter(
        specs=[ComputeSpec(name="x", description="x")],
        responses={
            "x": ComputeResult(success=True, output={}, duration_ms=123, exit_code=0),
        },
    )
    adapter = ComputeToolAdapter(compute=compute, inner=_FakeInnerTool())

    result = await adapter.execute("x", {})

    assert result.metadata is not None
    assert result.metadata["duration_ms"] == 123


# ---------- 异常降级 ----------


class _RaisingComputeAdapter:
    """ComputePort 实现:execute 抛非预期异常。"""

    def list_operations(self) -> list[ComputeSpec]:
        return [ComputeSpec(name="boom", description="raises")]

    async def execute(self, req: Any) -> ComputeResult:
        raise RuntimeError("internal explosion")


@pytest.mark.asyncio()
async def test_compute_exception_is_swallowed() -> None:
    """ComputePort 抛异常 → ToolResult.success=False,不冒泡。"""
    compute = _RaisingComputeAdapter()
    adapter = ComputeToolAdapter(compute=compute, inner=_FakeInnerTool())

    result = await adapter.execute("boom", {})

    assert result.success is False
    assert result.error is not None
    assert "RuntimeError" in result.error
    assert "internal explosion" in result.error


# ---------- _compute_result_to_tool_result 单元 ----------


def test_translator_handles_failure_without_error_obj() -> None:
    """失败但 error=None → 仍能产出可用的 ToolResult。"""
    result = ComputeResult(success=False, raw_stdout="x")

    tool_result = _compute_result_to_tool_result(result, ToolPolicy())

    assert tool_result.success is False
    assert tool_result.error == "compute failed without error detail"
    assert tool_result.output == "x"


def test_translator_handles_non_json_serializable_output() -> None:
    """output 中含不可 JSON 序列化对象 → ToolResult.success=False。"""

    class _NotSerializable:
        pass

    result = ComputeResult(success=True, output={"obj": _NotSerializable()})

    tool_result = _compute_result_to_tool_result(result, ToolPolicy())

    assert tool_result.success is False
    assert tool_result.error is not None
    assert "not JSON-serializable" in tool_result.error


def test_translator_empty_output_success() -> None:
    """success 且 output=None → ToolResult.output='{}'."""
    result = ComputeResult(success=True, output=None, duration_ms=10)

    tool_result = _compute_result_to_tool_result(result, ToolPolicy())

    assert tool_result.success is True
    assert json.loads(tool_result.output) == {}
