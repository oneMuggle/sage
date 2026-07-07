"""M2 显式限制 — 工具 adapter 中心超时 + output byte 截断。

- ``InprocToolAdapter`` 接受 policy 注入；慢工具触发 timeout。
- 超时返回 ``success=False`` + ``error`` 含 "tool_timeout" + metadata 带 timeout_seconds。
- ``output`` 超 ``max_output_bytes`` 时在 metadata 标 ``truncated=True``，output 字节长度 ≤ 上限。
- 同样语义对 ``ComputeToolAdapter`` 生效。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest
from sage_core import (
    ComputeRequest,
    ComputeResult,
    ComputeSpec,
    ToolResult,
    ToolSpec,
)

from backend.adapters.out.tool.compute_tool_adapter import ComputeToolAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.domain.tool_policy import ToolPolicy
from backend.tools.base import ToolResult as BaseToolResult

pytestmark = pytest.mark.unit


# ============================================================================
# InprocToolAdapter
# ============================================================================


class _SlowSyncTool:
    """同步阻塞工具（内部 time.sleep），用于触发中心超时。"""

    name = "slow"
    description = "sleeps"
    parameters: dict = {"type": "object", "properties": {}, "required": []}

    def __init__(self, sleep_s: float = 0.5) -> None:
        self.sleep_s = sleep_s

    def execute(self, **_: Any) -> BaseToolResult:
        time.sleep(self.sleep_s)
        return BaseToolResult(success=True, content="done", error=None)


class _BigOutputTool:
    """返回超大 output 的同步工具，用于触发 byte 截断。"""

    name = "big"
    description = "big output"
    parameters: dict = {"type": "object", "properties": {}, "required": []}

    def __init__(self, content: str = "x") -> None:
        self._content = content

    def execute(self, **_: Any) -> BaseToolResult:
        # 1 MB 的 output,远超默认 256_000
        return BaseToolResult(success=True, content=self._content * (1024 * 1024), error=None)


@dataclass
class _FakeSchema:
    name: str
    description: str
    parameters: dict


class _FakeRegistry:
    def __init__(self, tools: list) -> None:
        self._tools = {t.name: t for t in tools}

    def get(self, name: str):
        return self._tools.get(name)

    def list(self):
        return [
            _FakeSchema(name=t.name, description=t.description, parameters=t.parameters)
            for t in self._tools.values()
        ]


def _make_inproc(tool, policy: Optional[ToolPolicy] = None) -> InprocToolAdapter:
    return InprocToolAdapter(
        registry=_FakeRegistry([tool]),
        policy=policy,
    )


@pytest.mark.asyncio()
async def test_inproc_default_policy_is_tool_policy():
    """缺省构造（不传 policy）时，InprocToolAdapter 内部用 ToolPolicy() 默认。"""
    big = _BigOutputTool()
    adapter = _make_inproc(big)
    # 不报错且 policy 存在（默认 30s / 256_000 bytes）
    assert adapter._policy.timeout_seconds == 30.0  # type: ignore[attr-defined]
    assert adapter._policy.max_output_bytes == 256_000  # type: ignore[attr-defined]


@pytest.mark.asyncio()
async def test_inproc_slow_tool_returns_tool_timeout():
    policy = ToolPolicy(timeout_seconds=0.05)
    adapter = _make_inproc(_SlowSyncTool(sleep_s=0.5), policy=policy)

    result = await adapter.execute("slow", {})

    assert result.success is False
    assert "tool_timeout" in (result.error or "")
    assert result.metadata is not None
    assert result.metadata.get("timeout_seconds") == 0.05


@pytest.mark.asyncio()
async def test_inproc_big_output_is_truncated_to_max_bytes():
    policy = ToolPolicy(max_output_bytes=1024)
    adapter = _make_inproc(_BigOutputTool(), policy=policy)

    result = await adapter.execute("big", {})

    assert result.success is True
    assert len(result.output.encode("utf-8")) <= policy.max_output_bytes
    assert result.metadata is not None
    assert result.metadata.get("truncated") is True
    assert result.metadata.get("original_bytes") is not None
    assert result.metadata["original_bytes"] > policy.max_output_bytes


@pytest.mark.asyncio()
async def test_inproc_small_output_is_not_truncated():
    policy = ToolPolicy(max_output_bytes=1024)
    small_tool = type("Small", (), {})()
    small_tool.name = "small"
    small_tool.description = "small"
    small_tool.parameters = {"type": "object"}
    small_tool.execute = lambda **_: BaseToolResult(success=True, content="hi", error=None)
    adapter = _make_inproc(small_tool, policy=policy)

    result = await adapter.execute("small", {})

    assert result.success is True
    assert result.output == "hi"
    meta = result.metadata or {}
    assert meta.get("truncated", False) is False


# ============================================================================
# ComputeToolAdapter
# ============================================================================


class _SlowAsyncCompute:
    """ComputePort 假实现：execute 是 async + sleep，触发中心超时。"""

    def __init__(self, sleep_s: float = 0.5) -> None:
        self._sleep_s = sleep_s

    def list_operations(self):
        return [ComputeSpec(name="slowop", description="slow", params_schema={})]

    async def execute(self, _req: ComputeRequest) -> ComputeResult:
        import asyncio

        await asyncio.sleep(self._sleep_s)
        return ComputeResult(
            success=True,
            output={"v": "ok"},
            error=None,
            duration_ms=int(self._sleep_s * 1000),
            exit_code=0,
            raw_stdout="",
        )


class _BigOutputCompute:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def list_operations(self):
        return [ComputeSpec(name="bigop", description="big", params_schema={})]

    async def execute(self, _req: ComputeRequest) -> ComputeResult:
        return ComputeResult(
            success=True,
            output=self._payload,
            error=None,
            duration_ms=1,
            exit_code=0,
            raw_stdout="",
        )


class _FakeInnerForCompute:
    """ComputeToolAdapter 的 inner ToolPort 假实现。"""

    def list_tools(self) -> List[ToolSpec]:
        return []

    async def execute(self, name: str, args: Dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="inner", error=None, metadata=None)


@pytest.mark.asyncio()
async def test_compute_slow_compute_returns_tool_timeout():
    policy = ToolPolicy(timeout_seconds=0.05)
    adapter = ComputeToolAdapter(
        compute=_SlowAsyncCompute(sleep_s=0.5),
        inner=_FakeInnerForCompute(),
        policy=policy,
    )

    result = await adapter.execute("slowop", {})

    assert result.success is False
    assert "tool_timeout" in (result.error or "")
    assert result.metadata is not None
    assert result.metadata.get("timeout_seconds") == 0.05


@pytest.mark.asyncio()
async def test_compute_big_output_is_truncated_to_max_bytes():
    policy = ToolPolicy(max_output_bytes=2048)
    # 构造会让 json.dumps 后 > 2048 bytes 的 payload
    payload = {"k": "y" * 5000}
    adapter = ComputeToolAdapter(
        compute=_BigOutputCompute(payload=payload),
        inner=_FakeInnerForCompute(),
        policy=policy,
    )

    result = await adapter.execute("bigop", {})

    assert result.success is True
    assert len(result.output.encode("utf-8")) <= policy.max_output_bytes
    assert result.metadata is not None
    assert result.metadata.get("truncated") is True
    assert result.metadata.get("original_bytes") is not None
    assert result.metadata["original_bytes"] > policy.max_output_bytes
    # 设计取舍：byte 截断可能切到 JSON 字符串中间，截断后未必合法 JSON。
    # 这是"可预测失败"的一部分（方案 §3.2），不实现"截到 JSON 边界"。
    # 当截断未发生（或发生在 string 边界）时仍应是合法 JSON——单独覆盖。
    assert result.output.startswith('{"k":')
