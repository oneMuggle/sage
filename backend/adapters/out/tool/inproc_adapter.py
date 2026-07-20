"""进程内 tool registry adapter。

包装 ``backend/tools/registry.py`` 的 ``ToolRegistry``，实现
``backend.ports.tool.ToolPort`` 协议。

设计要点
--------

- 接受外部注入的 ``ToolRegistry``（便于测试用 mock 替换）；缺省情况下
  使用新建的 ``ToolRegistry()``，调用方可自行 ``register_all_tools``。
- ``list_tools`` 把 ``ToolSchema``（带 ``parameters`` JSON Schema）转成
  端口侧的纯 ``ToolSpec``。
- ``execute`` 内部用 ``asyncio.to_thread`` 把同步工具调用放到线程池，
  并用 ``asyncio.wait_for`` 施加 ``policy.timeout_seconds`` 中心超时；
  超时返回 ``success=False, error="tool_timeout: ..."``。然后把
  ``backend.tools.base.ToolResult(success, content, error)`` 转成端口侧
  的 ``domain.tool.ToolResult(success, output, error, metadata)``。
  ``content`` 会被 ``str()`` 序列化进 ``output``，``metadata`` 携带
  截断标记 ``truncated`` 与 ``original_bytes``（若发生 byte 截断）。
- 工具未注册时返回 ``success=False, error=...``，**不抛异常**，与端口
  契约"失败时 success=False 并携带 error"一致。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from sage_core import ToolResult, ToolSpec
from sage_core.repositories import ToolPort  # noqa: F401  (structural typing target)

from backend.domain.tool_policy import ToolPolicy
from backend.tools.registry import ToolRegistry as _ToolRegistry


class InprocToolAdapter:
    """``ToolPort`` 的 in-process 实现。"""

    def __init__(
        self,
        registry: Optional[_ToolRegistry] = None,
        policy: Optional[ToolPolicy] = None,
    ) -> None:
        # 接受外部注入（用于测试）或使用新建 registry
        self._registry = registry if registry is not None else _ToolRegistry()
        # M2: 中心超时 + byte 截断策略（缺省即 ToolPolicy() 默认）
        self._policy = policy or ToolPolicy()
        # 注册所有内置工具（含 MCP 工具）；M2 把 policy 透传给每个内置工具
        if registry is None:
            from backend.tools import register_all_tools

            register_all_tools(self._registry, policy=self._policy)

    def list_tools(self) -> List[ToolSpec]:
        """返回所有已注册工具的 spec（按注册顺序）。"""
        specs: List[ToolSpec] = []
        for schema in self._registry.list():
            specs.append(
                ToolSpec(
                    name=schema.name,
                    description=schema.description,
                    parameters=dict(schema.parameters),
                )
            )
        return specs

    async def execute(self, name: str, args: Dict[str, Any]) -> ToolResult:
        """按名称执行工具并返回端口侧的 ``ToolResult``。

        M2 增强：
        - 中心超时（``policy.timeout_seconds``）—— 同步工具经线程池异步包装
          后用 ``asyncio.wait_for`` 包裹，超时返回 ``success=False, error="tool_timeout"``。
        - output byte 截断 —— 超 ``policy.max_output_bytes`` 时截断并在 metadata
          标 ``truncated=True, original_bytes=N``。

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
            raw = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, lambda: tool.execute(**args)),
                timeout=self._policy.timeout_seconds,
            )
        except (asyncio.TimeoutError, TimeoutError):  # noqa: UP041
            # Python 3.10: asyncio.exceptions.TimeoutError ≠ builtin TimeoutError；
            # 3.11+ 两者为同一类。兼容两个名称。
            return ToolResult(
                success=False,
                output="",
                error=f"tool_timeout: exceeded {self._policy.timeout_seconds}s",
                metadata={
                    "timeout_seconds": self._policy.timeout_seconds,
                    "truncated": False,
                },
            )
        except Exception as exc:  # noqa: BLE001  (按契约收敛所有错误)
            return ToolResult(
                success=False,
                output="",
                error=f"{type(exc).__name__}: {exc}",
                metadata=None,
            )

        output_str = "" if raw.content is None else str(raw.content)
        truncated_output, truncation_meta = _truncate_output(output_str, self._policy)

        metadata: Optional[Dict[str, Any]] = None
        if truncation_meta:
            metadata = dict(truncation_meta)

        # backend.tools.base.ToolResult -> domain.tool.ToolResult
        return ToolResult(
            success=bool(raw.success),
            output=truncated_output,
            error=raw.error,
            metadata=metadata,
        )


def _truncate_output(output: str, policy: ToolPolicy) -> Tuple[str, Dict[str, Any]]:
    """按 ``policy.max_output_bytes``（utf-8 字节）截断 output。

    Returns:
        (截断后字符串, metadata dict)。未截断时返回 ``("", {})`` 之外的
        (原字符串, {})，调用方可据此判定是否需要在 metadata 标 truncated。
    """
    raw_bytes = output.encode("utf-8")
    if len(raw_bytes) <= policy.max_output_bytes:
        return output, {}
    truncated = raw_bytes[: policy.max_output_bytes].decode("utf-8", errors="replace")
    return truncated, {
        "truncated": True,
        "original_bytes": len(raw_bytes),
        "max_output_bytes": policy.max_output_bytes,
    }
