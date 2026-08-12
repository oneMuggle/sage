"""``dispatch_subagents`` 工具 —— conductor 并行派发子 agent 的原语。

方案 C（multi-agent orchestration spec §5.2）：conductor（主 LLM）在
multi 模式下拿到 ``task_plan`` 后，按计划调用本工具，把
``[{agent_id, goal}]`` 交给 ``ChatDispatcher`` 并行执行。

关键约束：
- 本工具是**异步**的（子 agent 需在事件循环上并发 + 直接推 entry.queue），
  因此必须经 run_loop 的 ``execute_async`` special-case 调用，不能走同步
  ``execute``。同步调用会返回明确的错误提示。
- 仅 multi 模式注册到 conductor 的 tool_registry（tool-toggle 门）。
- 默认权限：未登记 → ``classify_tool`` 回退 WRITE；``workspace_write``
  模式放行，read_only/prompt 模式按矩阵 deny/ask（M1 硬化语义不变）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.tools.base import BaseTool, ToolResult, ToolSchema

#: 工具参数 schema —— 单次调用最多 8 个任务（= MAX_PLAN_TASKS）。maxItems 管
#: "单次调用任务数"，与 ChatDispatcher 的并发上限（信号量 4）解耦：并发由
#: 调度器独立兜底，8 个任务即使全并发也只同时跑 4 个，其余排队。
INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "goal": {"type": "string", "maxLength": 2000},
                },
                "required": ["agent_id", "goal"],
            },
        }
    },
    "required": ["tasks"],
}

_TOOL_DESCRIPTION = (
    "并行派发子 agent 执行任务。适用于已拆解为多个子任务的复杂目标："
    "传入 [{agent_id, goal}] 列表（最多 8 个），每个子 agent 独立运行并把"
    "结果聚合返回。agent_id 必须是已启用的角色（如 researcher / writer）。"
)


class DispatchSubagentsTool(BaseTool):
    """把子任务派发给 ChatDispatcher 的异步工具。"""

    def __init__(self, dispatcher: Any) -> None:
        """Args:
            dispatcher: 实现了 ``async dispatch(tasks) -> str`` 的 ChatDispatcher。
        """
        super().__init__()
        self._dispatcher = dispatcher

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="dispatch_subagents",
            description=_TOOL_DESCRIPTION,
            parameters=INPUT_SCHEMA,
        )

    async def execute_async(self, **kwargs: Any) -> ToolResult:
        """异步执行 —— 子 agent 在事件循环上并发（ChatDispatcher 内 gather）。"""
        tasks: List[Dict[str, str]] = kwargs.get("tasks", [])
        try:
            aggregated = await self._dispatcher.dispatch(tasks)
            return ToolResult(success=True, content=aggregated)
        except Exception as exc:  # noqa: BLE001 — 错误回传 conductor 决策
            return ToolResult(success=False, error=f"dispatch_subagents 失败: {exc}")

    def execute(self, **kwargs: Any) -> ToolResult:
        """同步调用不可行（子 agent 需并发）—— 返回明确错误。"""
        return ToolResult(
            success=False,
            error="dispatch_subagents 是异步工具，必须经 run_loop 的 "
            "execute_async special-case 调用",
        )
