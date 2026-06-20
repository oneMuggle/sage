"""Mock Compute adapter(测试用)。

行为:

- ``list_operations`` 返回构造时传入的 ``specs`` 副本
- ``execute`` 按 operation 名查 ``responses`` 字典;未配置时回退 ``default_result``
- 所有调用都记录到 ``calls`` 列表,便于断言

类似 ``backend.adapters.out.llm.mock_adapter.MockLLMAdapter`` 的模式。
"""

from __future__ import annotations

from sage_core import (
    ComputeError,
    ComputeErrorType,
    ComputeRequest,
    ComputeResult,
    ComputeSpec,
)
from sage_core.repositories import ComputePort  # noqa: F401  (structural typing target)


class MockComputeAdapter:
    """``ComputePort`` 的内存实现,供单元测试使用。"""

    def __init__(
        self,
        specs: list[ComputeSpec] | None = None,
        responses: dict[str, ComputeResult] | None = None,
        default_result: ComputeResult | None = None,
    ) -> None:
        self._specs: list[ComputeSpec] = list(specs or [])
        self._responses: dict[str, ComputeResult] = dict(responses or {})
        self._default = default_result or ComputeResult(
            success=False,
            error=ComputeError(
                type=ComputeErrorType.OPERATION_NOT_FOUND,
                message="no mock response configured",
            ),
        )
        self.calls: list[ComputeRequest] = []

    # ---- ComputePort 实现 ----

    def list_operations(self) -> list[ComputeSpec]:
        return list(self._specs)

    async def execute(self, req: ComputeRequest) -> ComputeResult:
        self.calls.append(req)
        return self._responses.get(req.operation, self._default)

    # ---- 测试辅助 ----

    def reset(self) -> None:
        """清空调用记录。"""
        self.calls.clear()


# 静态协议一致性声明（mypy / 文档）
_: ComputePort = MockComputeAdapter(specs=[])  # type: ignore[assignment]
