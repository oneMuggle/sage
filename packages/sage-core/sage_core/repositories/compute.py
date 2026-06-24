"""外部计算能力端口。

定义 sage 调用外部计算项目（如 ghm）的抽象接口。实现侧可选：

- ``SubprocessComputeAdapter`` — 通过 ``ExecutableResolver`` 解析可执行文件后
  spawn 子进程调用 CLI（本期实现）
- ``HttpComputeAdapter``       — 通过 httpx 调用远程 HTTP 服务（本期预留空壳）
- ``MockComputeAdapter``       — 测试用内存实现

参见 ``backend.domain.compute`` 中的数据模型。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sage_core import ComputeRequest, ComputeResult, ComputeSpec


@runtime_checkable
class ComputePort(Protocol):
    """外部计算能力的端口抽象。"""

    def list_operations(self) -> list[ComputeSpec]:
        """列出当前可用的计算操作。

        Returns:
            ``ComputeSpec`` 列表（用于注册到 LLM tool 列表）。
            若 adapter 未配置/配置错误，可返回空列表（工具不会暴露给 LLM）。
        """
        ...

    async def execute(self, req: ComputeRequest) -> ComputeResult:
        """执行一次计算。

        Args:
            req: 包含 ``operation`` 和 ``params`` 的请求对象。

        Returns:
            ``ComputeResult``；**永不抛异常**，失败时 ``success=False`` 并携带
            ``error``。请求未知操作返回 ``ComputeErrorType.OPERATION_NOT_FOUND``。
        """
        ...
