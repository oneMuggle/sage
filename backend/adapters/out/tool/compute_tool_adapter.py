"""``ComputeToolAdapter`` — 把 ``ComputePort`` 桥接为 ``ToolPort``。

把 ghm 等外部计算项目的 operations 包装成 LLM tool,合并到 sage 内置工具
列表中。``ChatService.run_turn`` 通过 ``ToolPort.execute(name, args)``
触发,本 adapter 按工具名路由:

- ``name`` 命中 ``ComputePort.list_operations()`` 中的 spec → 走计算路径
- 否则 → 委托给 ``inner: ToolPort``(通常是 ``InprocToolAdapter``)

设计要点
--------

- ``list_tools`` 合并 inner + 计算工具,顺序为 inner-first(保证内置工具优先)
- ``ComputeSpec.params_schema`` 透传为 ``ToolSpec.parameters``(JSON Schema)
- ``ComputeResult`` → ``ToolResult``:
    - ``success=True``  → ``output`` 用 ``json.dumps(result.output)`` 序列化
    - ``success=False`` → ``error`` 取 ``ComputeError.message``
    - ``metadata`` 携带 ``duration_ms`` / ``exit_code`` / 错误分类
- 失败永不抛异常,与 ``ToolPort`` 契约一致(``InprocToolAdapter`` 同模式)。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from sage_core import ComputeRequest, ComputeResult, ToolResult, ToolSpec
from sage_core.repositories import (
    ComputePort,
    ToolPort,  # noqa: F401  (structural typing target)
)

logger = logging.getLogger(__name__)


class ComputeToolAdapter:
    """``ToolPort`` 的组合实现 — 桥接 ``ComputePort`` 与 inner ``ToolPort``。

    Args:
        compute: ``ComputePort`` 实现(如 ``SubprocessComputeAdapter``)。
        inner:   现有 ``ToolPort`` 实现(如 ``InprocToolAdapter``)。
    """

    def __init__(self, compute: ComputePort, inner: ToolPort) -> None:
        self._compute = compute
        self._inner = inner
        # 缓存计算工具名集合,避免每次 execute 都调 list_operations
        self._compute_names = {spec.name for spec in compute.list_operations()}

    def list_tools(self) -> List[ToolSpec]:
        """合并 inner 工具 + 计算工具(inner 在前)。"""
        compute_specs = [
            ToolSpec(
                name=op.name,
                description=op.description,
                parameters=dict(op.params_schema),
            )
            for op in self._compute.list_operations()
        ]
        return list(self._inner.list_tools()) + compute_specs

    async def execute(self, name: str, args: Dict[str, Any]) -> ToolResult:
        """路由:计算工具走 ComputePort,其他委托给 inner。"""
        if name in self._compute_names:
            return await self._execute_compute(name, args)
        return await self._inner.execute(name, args)

    # ---- 私有 ----

    async def _execute_compute(self, name: str, args: Dict[str, Any]) -> ToolResult:
        """调 ComputePort,把 ComputeResult 翻译为 ToolResult。"""
        req = ComputeRequest(operation=name, params=dict(args))
        try:
            result = await self._compute.execute(req)
        except Exception as exc:  # noqa: BLE001  — ToolPort 契约要求不抛
            logger.exception("compute.execute unexpected error tool=%s", name)
            return ToolResult(
                success=False,
                output="",
                error=f"{type(exc).__name__}: {exc}",
                metadata=None,
            )
        return _compute_result_to_tool_result(result)


def _compute_result_to_tool_result(result: ComputeResult) -> ToolResult:
    """``ComputeResult`` → ``ToolResult`` 适配。

    成功时把 ``output`` (dict) 序列化为 JSON 字符串放入 ``ToolResult.output``;
    失败时 ``error`` 取 ``ComputeError.message``。无论成败,``metadata`` 携带
    ``duration_ms`` / ``exit_code`` / 错误分类供上层日志/指标使用。
    """
    metadata: Dict[str, Any] = {}
    if result.duration_ms is not None:
        metadata["duration_ms"] = result.duration_ms
    if result.exit_code is not None:
        metadata["exit_code"] = result.exit_code

    if result.success:
        try:
            output_str = json.dumps(
                result.output if result.output is not None else {},
                ensure_ascii=False,
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"compute output not JSON-serializable: {exc}",
                metadata=metadata or None,
            )
        return ToolResult(
            success=True,
            output=output_str,
            error=None,
            metadata=metadata or None,
        )

    # 失败路径
    if result.error is not None:
        metadata["error_type"] = result.error.type.value
        message = result.error.message
    else:
        message = "compute failed without error detail"
    return ToolResult(
        success=False,
        output=result.raw_stdout or "",
        error=message,
        metadata=metadata or None,
    )
