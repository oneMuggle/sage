"""进程内 tool registry adapter。

包装 ``backend/tools/registry.py`` 的 ``ToolRegistry``，实现
``backend.ports.tool.ToolPort`` 协议。

设计要点
--------

- 接受外部注入的 ``ToolRegistry``（便于测试用 mock 替换）；缺省情况下
  使用新建的 ``ToolRegistry()``，调用方可自行 ``register_all_tools``。
- ``list_tools`` 把 ``ToolSchema``（带 ``parameters`` JSON Schema）转成
  端口侧的纯 ``ToolSpec``。
- ``execute`` 内部直接调用 ``tool.execute(**args)``（同步），然后把
  ``backend.tools.base.ToolResult(success, content, error)`` 转成端口侧
  的 ``domain.tool.ToolResult(success, output, error, metadata)``。
  ``content`` 会被 ``str()`` 序列化进 ``output``，``metadata`` 始终为
  ``None``（现有 ``BaseTool`` 不产出元数据）。
- 工具未注册时返回 ``success=False, error=...``，**不抛异常**，与端口
  契约"失败时 success=False 并携带 error"一致。
"""

from __future__ import annotations

from typing import Any

from sage_core import ToolResult, ToolSpec
from sage_core.repositories import ToolPort  # noqa: F401  (structural typing target)

from backend.tools.registry import ToolRegistry as _ToolRegistry


class InprocToolAdapter:
    """``ToolPort`` 的 in-process 实现。"""

    def __init__(self, registry: _ToolRegistry | None = None) -> None:
        # 接受外部注入（用于测试）或使用新建 registry
        self._registry = registry if registry is not None else _ToolRegistry()
        # 注册所有内置工具（含 MCP 工具）
        if registry is None:
            from backend.tools import register_all_tools

            register_all_tools(self._registry)

    def list_tools(self) -> list[ToolSpec]:
        """返回所有已注册工具的 spec（按注册顺序）。"""
        specs: list[ToolSpec] = []
        for schema in self._registry.list():
            specs.append(
                ToolSpec(
                    name=schema.name,
                    description=schema.description,
                    parameters=dict(schema.parameters),
                )
            )
        return specs

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """按名称执行工具并返回端口侧的 ``ToolResult``。

        工具未注册时返回 ``success=False``；工具执行抛异常时同样捕获并
        转成 ``success=False`` 的结果，不向调用方冒泡。
        """
        tool = self._registry.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=f"tool not registered: {name}",
                metadata=None,
            )

        try:
            raw = tool.execute(**args)
        except Exception as exc:  # noqa: BLE001  (按契约收敛所有错误)
            return ToolResult(
                success=False,
                output="",
                error=f"{type(exc).__name__}: {exc}",
                metadata=None,
            )

        # backend.tools.base.ToolResult -> domain.tool.ToolResult
        return ToolResult(
            success=bool(raw.success),
            output="" if raw.content is None else str(raw.content),
            error=raw.error,
            metadata=None,
        )
