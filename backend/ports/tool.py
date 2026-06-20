"""工具调用端口。

定义工具发现与执行的抽象接口。实现侧可能直接桥接进程内
``backend.tools.registry.ToolRegistry``（in-process adapter），
也可能桥接远程 MCP 工具服务（后续可扩展）。
"""

from typing import Any, Protocol

from sage_core import ToolResult, ToolSpec


class ToolPort(Protocol):
    """工具注册与执行端口。"""

    def list_tools(self) -> list[ToolSpec]:
        """列出当前可用的所有工具规格。"""
        ...

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """按名称执行工具。

        Args:
            name: 工具名（需事先 ``register`` 过）。
            args: 工具参数（已解析为 dict）。

        Returns:
            ``ToolResult``；失败时 ``success=False`` 并携带 ``error``。
        """
        ...
