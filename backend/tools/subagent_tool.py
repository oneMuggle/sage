"""``dispatch_subagents`` 工具 —— conductor 并行派发子 agent 的原语。

方案 C（multi-agent orchestration spec §5.2）：conductor（主 LLM）在
multi 模式下拿到 ``task_plan`` 后，按计划调用本工具，把
``[{task_id, agent_id, goal}]`` 交给 ``ChatDispatcher`` 并行执行。

关键约束：
- 本工具是**异步**的（子 agent 需在事件循环上并发 + 直接推 entry.queue），
  因此必须经 run_loop 的 ``execute_async`` special-case 调用，不能走同步
  ``execute``。同步调用会返回明确的错误提示。
- 仅 multi 模式注册到 conductor 的 tool_registry（tool-toggle 门）。
- 默认权限：未登记 → ``classify_tool`` 回退 WRITE；``workspace_write``
  模式放行，read_only/prompt 模式按矩阵 deny/ask（M1 硬化语义不变）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

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
                    # P2-7 (2026-08-14): conductor 必须回传计划编号 task_id
                    #（task_plan 事件的 t1..tN），dispatcher 据此与权威计划对齐。
                    "task_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "goal": {"type": "string", "maxLength": 2000},
                    "output_schema": {
                        "type": "object",
                        "description": "可选 JSON Schema；子 agent 最终回复将被约束/校验为符合它的 JSON 对象",
                    },
                    "followup_of": {
                        "type": "string",
                        "description": "可选：要追问的已完成子任务 task_id（本 run 内）。设置后 goal 作为追问消息发给同一子代理上下文，而非开新任务",
                    },
                    "retry_of": {
                        "type": "string",
                        "description": "可选：要重派的已失败/被取消子任务 task_id（本 run 内）。新任务继承源任务的 scratch 工作现场与失败原因，适合修正方法后重做",
                    },
                },
                "required": ["agent_id", "goal", "task_id"],
            },
        },
        "background": {
            "type": "boolean",
            "description": "可选：true = 后台派发，立即返回（任务板照常推进），稍后用 collect_subagents 获取聚合结果",
        },
    },
    "required": ["tasks"],
}

_TOOL_DESCRIPTION = (
    "并行派发子 agent 执行任务。适用于已拆解为多个子任务的复杂目标："
    "传入 [{task_id, agent_id, goal, output_schema?}] 列表（最多 8 个），每个子 agent 独立运行并把"
    "结果聚合返回。agent_id 必须是已启用的角色（如 researcher / writer）。"
    "task_id 必须回传 task_plan 中的计划编号（t1..tN）。"
    "对已完成的子任务需要补充要求/追问时，传 followup_of=<已完成 task_id> 继续同一上下文。"
    "对失败/被取消的子任务需要修正方法后重做时，传 retry_of=<失败 task_id> 新任务会继承其工作现场与失败原因。"
    "需要在本批任务运行期间先做其他工作时，传 background=true 立即返回，"
    "之后用 collect_subagents 获取聚合结果。"
)


class CollectSubagentsTool(BaseTool):
    """等待后台派发完成并返回聚合结果（BD, round12）。

    与 ``DispatchSubagentsTool(background=true)`` 配对：collect 超时只是
    "本次没等到"，后台任务经 shield 继续运行，可再次 collect。
    """

    def __init__(self, dispatcher: Any) -> None:
        super().__init__()
        self._dispatcher = dispatcher

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="collect_subagents",
            description=(
                "等待后台派发的子 agent 全部完成，返回聚合结果。"
                "与 dispatch_subagents(background=true) 配对使用；"
                "没有进行中的后台派发时返回错误。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "timeout_secs": {
                        "type": "integer",
                        "description": "可选：本次最长等待秒数（默认 600）；超时后后台任务继续运行，可再次 collect",
                    },
                    "wait": {
                        "type": "boolean",
                        "description": "可选：false = 不等待，立即返回各子任务当前状态与结果预览快照（默认 true = 等待全部完成）",
                    },
                },
            },
        )

    async def execute_async(self, **kwargs: Any) -> ToolResult:  # noqa: PLR0911 — 三态出口语义清晰
        wait = getattr(self._dispatcher, "wait_background", None)
        if not callable(wait):
            return ToolResult(success=False, error="当前 dispatcher 不支持 collect")
        timeout_raw = kwargs.get("timeout_secs")
        timeout: Optional[float] = None
        try:
            timeout = float(timeout_raw) if timeout_raw is not None else None
        except (TypeError, ValueError):
            timeout = None
        # BD3 (round13): 非阻塞快照形态 —— 立即返回当前状态，不等待。
        if kwargs.get("wait") is False:
            snapshot = getattr(self._dispatcher, "background_snapshot", None)
            if not callable(snapshot):
                return ToolResult(success=False, error="当前 dispatcher 不支持快照")
            return ToolResult(success=True, content=snapshot())
        try:
            aggregated = await wait(timeout)
            return ToolResult(success=True, content=aggregated)
        except asyncio.TimeoutError:  # noqa: UP041 — py3.8 下 ≠ 内建 TimeoutError
            return ToolResult(
                success=False,
                error=(
                    "collect_timeout: 后台派发仍在运行（超过"
                    f"{int(timeout) if timeout else 600}s）。任务板仍在推进，可稍后再次 collect_subagents。"
                ),
            )
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — 错误回传 conductor 决策
            return ToolResult(success=False, error=f"collect_subagents 失败: {exc}")

    def execute(self, **kwargs: Any) -> ToolResult:
        """同步调用不可行（需并发事件循环）。"""
        return ToolResult(success=False, error="collect_subagents 仅支持异步调用（run_loop 内）")


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
        """异步执行 —— 子 agent 在事件循环上并发（ChatDispatcher 内 gather）。

        ``_tool_call_id``（可选）由 run_loop 的 dispatch special-case 注入
        （conductor 本工具调用的 ID），dispatcher 据此为子任务标记
        ``parent_tool_call_id``，前端把子代理实时步骤关联到聊天流的
        "Delegate <goal>" 卡片。非 run_loop 调用方不传则保持 None。
        """
        tasks: List[Dict[str, str]] = kwargs.get("tasks", [])
        tool_call_id = kwargs.get("_tool_call_id")
        if tool_call_id:
            notify = getattr(self._dispatcher, "notify_tool_call", None)
            if callable(notify):
                notify(str(tool_call_id))
        # BD (round12): 后台派发 —— 启动即返回，conductor 可先做其他工作，
        # 再用 collect_subagents 取聚合结果。
        if kwargs.get("background"):
            started = getattr(self._dispatcher, "start_background_dispatch", None)
            if not callable(started):
                return ToolResult(success=False, error="当前 dispatcher 不支持后台派发")
            bg_task = started(tasks)
            if bg_task is None:
                return ToolResult(
                    success=False,
                    error="background_dispatch_in_progress: 已有后台派发进行中，请先调用 collect_subagents",
                )
            task_ids = [
                str(t.get("task_id"))
                for t in tasks
                if isinstance(t, dict) and t.get("task_id")
            ]
            return ToolResult(
                success=True,
                content={
                    "status": "dispatched_background",
                    "run_id": getattr(self._dispatcher, "run_id", None),
                    "task_ids": task_ids,
                    "note": "子任务已在后台执行；完成前可先做其他工作，"
                    "调用 collect_subagents 获取聚合结果",
                },
            )
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
