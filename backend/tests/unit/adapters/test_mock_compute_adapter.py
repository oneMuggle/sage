"""R135 — MockComputeAdapter（ComputePort 内存实现）单元测试。

覆盖：list_operations 副本语义、execute 按 operation 命中/未配置回退
default、calls 记录顺序、reset、ComputePort 结构一致。
"""

from __future__ import annotations

import pytest
from sage_core import ComputeError, ComputeErrorType, ComputeRequest, ComputeResult, ComputeSpec

from backend.adapters.out.compute.mock_adapter import MockComputeAdapter

pytestmark = pytest.mark.unit


def _spec(name):
    return ComputeSpec(name=name, description=f"{name} op")


def _ok(value):
    return ComputeResult(success=True, output={"v": value})


def _not_found():
    return ComputeResult(
        success=False,
        error=ComputeError(type=ComputeErrorType.OPERATION_NOT_FOUND, message="nope"),
    )


def test_list_operations_returns_specs_copy():
    specs = [_spec("a"), _spec("b")]
    adapter = MockComputeAdapter(specs=specs)
    listed = adapter.list_operations()
    assert [s.name for s in listed] == ["a", "b"]
    listed.append(_spec("c"))
    assert len(adapter.list_operations()) == 2  # 外部修改不影响内部


@pytest.mark.asyncio()
async def test_execute_hits_configured_operation():
    adapter = MockComputeAdapter(
        specs=[_spec("op1")],
        responses={"op1": _ok(42)},
    )
    result = await adapter.execute(ComputeRequest(operation="op1"))
    assert result.success is True
    assert result.output == {"v": 42}


@pytest.mark.asyncio()
async def test_execute_unknown_operation_falls_back_to_default_not_found():
    adapter = MockComputeAdapter(specs=[_spec("op1")])
    result = await adapter.execute(ComputeRequest(operation="ghost"))
    assert result.success is False
    assert result.error.type == ComputeErrorType.OPERATION_NOT_FOUND


@pytest.mark.asyncio()
async def test_explicit_default_result_used():
    default = _ok("fallback")
    adapter = MockComputeAdapter(default_result=default)
    result = await adapter.execute(ComputeRequest(operation="anything"))
    assert result.success is True
    assert result.output == {"v": "fallback"}


@pytest.mark.asyncio()
async def test_calls_record_request_order():
    adapter = MockComputeAdapter()
    r1 = ComputeRequest(operation="a")
    r2 = ComputeRequest(operation="b")
    await adapter.execute(r1)
    await adapter.execute(r2)
    assert adapter.calls == [r1, r2]


def test_reset_clears_calls():
    adapter = MockComputeAdapter()

    import asyncio

    asyncio.run(adapter.execute(ComputeRequest(operation="a")))
    adapter.reset()
    assert adapter.calls == []


def test_empty_construction_usable():
    adapter = MockComputeAdapter()
    assert adapter.list_operations() == []


def test_multiple_operations_each_hit_own_response():
    adapter = MockComputeAdapter(
        specs=[_spec("x"), _spec("y")],
        responses={"x": _ok(1), "y": _ok(2)},
    )

    import asyncio

    async def _run():
        return await adapter.execute(ComputeRequest(operation="x")), await adapter.execute(
            ComputeRequest(operation="y")
        )

    rx, ry = asyncio.run(_run())
    assert rx.output == {"v": 1}
    assert ry.output == {"v": 2}
