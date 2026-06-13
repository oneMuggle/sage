"""``backend.adapters.out.compute.http_adapter`` 空壳单测。

确保:

- ``list_operations`` 与 yaml 行为一致(便于未来透明切换 adapter)
- ``execute`` 抛 ``NotImplementedError`` 并指向 plan 文档
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.adapters.out.compute.http_adapter import HttpComputeAdapter
from backend.domain.compute import ComputeRequest


def _make_config() -> dict[str, Any]:
    return {
        "adapter": "http",
        "http": {"base_url": "http://localhost:8000", "timeout_seconds": 30},
        "operations": [
            {
                "name": "compute_shock",
                "description": "正激波计算",
                "http_endpoint": "/api/shock/calculate",
                "params_schema": {"type": "object"},
            },
            {
                "name": "compute_equilibrium",
                "description": "平衡气体",
                "http_endpoint": "/api/equilibrium/calculate",
                "params_schema": {"type": "object"},
            },
        ],
    }


def test_list_operations_matches_yaml() -> None:
    """list_operations 应与 yaml 中 operations 一一对应。"""
    adapter = HttpComputeAdapter(_make_config())
    specs = adapter.list_operations()

    names = [s.name for s in specs]
    assert names == ["compute_shock", "compute_equilibrium"]
    assert specs[0].description == "正激波计算"


def test_list_operations_with_empty_yaml() -> None:
    """yaml 中无 operations → 返回空列表。"""
    adapter = HttpComputeAdapter({})
    assert adapter.list_operations() == []


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_execute_raises_not_implemented() -> None:
    """execute 必须抛 NotImplementedError 并指向 plan 文档。"""
    adapter = HttpComputeAdapter(_make_config())

    with pytest.raises(NotImplementedError) as exc_info:
        await adapter.execute(ComputeRequest(operation="compute_shock", params={"mach": 6.5}))

    msg = str(exc_info.value)
    assert "adapter=subprocess" in msg
    assert "docs/technical/19-ghm-integration.md" in msg
