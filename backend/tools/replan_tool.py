"""re-plan 工具族 —— conductor 在 run 中动态调整计划（RP1, round34）。

背景：dispatch 的"计划权威"逻辑决定 task_id 命中计划时以计划为准、忽略
工具传入的 goal（见 ``ChatDispatcher.dispatch``）。因此 conductor 想让任务
改目标，改 dispatch 参数无效，必须改计划本身 —— 本模块三个工具即该能力的
对外暴露面：

- ``update_pending_task``  改未启动任务的 goal / agent
- ``cancel_pending_task``  取消不需要的任务（计划层 or 已派发 queued/running）
- ``add_task_to_plan``     添加新任务并声明依赖（含悬空依赖与环校验）

三个工具均同步执行（只改内存计划 + 一次 plan_json 回写，无需事件循环），
且仅 multi 模式注册到 conductor 的 tool_registry（与 ``dispatch_subagents``
同一 tool-toggle 门）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.tools.base import BaseTool, ToolResult, ToolSchema

_UPDATE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "要修改的计划任务编号（task_plan 中的 t1..tN）",
        },
        "goal": {
            "type": "string",
            "maxLength": 2000,
            "description": "可选：新的任务目标描述（省略则不改）",
        },
        "agent_id": {
            "type": "string",
            "description": "可选：新的执行角色（省略则不改）",
        },
    },
    "required": ["task_id"],
}

_CANCEL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "要取消的计划任务编号（task_plan 中的 t1..tN）",
        },
        "reason": {
            "type": "string",
            "maxLength": 500,
            "description": "可选：取消原因（记录进计划，供最终汇总说明）",
        },
    },
    "required": ["task_id"],
}

_ADD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "新任务编号（必须未被占用，约定从 t9 起续编）",
        },
        "goal": {"type": "string", "maxLength": 2000, "description": "任务目标"},
        "agent_id": {
            "type": "string",
            "description": "执行角色（如 researcher / writer）",
        },
        "depends_on": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选：依赖的已有任务编号列表（只能引用已存在的 task_id）",
        },
    },
    "required": ["task_id", "goal", "agent_id"],
}


class _ReplanToolBase(BaseTool):
    """re-plan 工具公共基类 —— 统一 dispatcher 缺失的降级与结果封装。"""

    def __init__(self, dispatcher: Any) -> None:
        super().__init__()
        self._dispatcher = dispatcher

    def _call(self, method: str, **kwargs: Any) -> ToolResult:
        """调用 dispatcher 方法并把 dict 结果封装为 ToolResult。"""
        if not callable(getattr(self._dispatcher, method, None)):
            return ToolResult(
                success=False,
                error=f"当前 dispatcher 不支持 {method}（计划不可变）",
            )
        try:
            result = getattr(self._dispatcher, method)(**kwargs)
        except Exception as exc:  # noqa: BLE001 — 错误回传 conductor 决策
            return ToolResult(success=False, error=f"{method} 失败: {exc}")
        if not isinstance(result, dict):
            return ToolResult(success=True, content=result)
        if result.get("success"):
            return ToolResult(success=True, content=result)
        return ToolResult(success=False, error=str(result.get("error", "未知错误")))


class UpdatePendingTaskTool(_ReplanToolBase):
    """修改未启动任务的 goal / agent。"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="update_pending_task",
            description=(
                "修改计划中尚未派发任务的 goal 或 agent 角色。适用于发现原目标描述不当、"
                "或更合适的执行角色时的主动调整。只能改还没有派发的任务；已派发的任务"
                "请用 cancel_pending_task + add_task_to_plan 重建。"
            ),
            parameters=_UPDATE_SCHEMA,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        return self._call(
            "update_pending_task",
            task_id=str(kwargs.get("task_id", "")),
            goal=kwargs.get("goal"),
            agent_id=kwargs.get("agent_id"),
        )


class CancelPendingTaskTool(_ReplanToolBase):
    """取消不需要的任务。"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="cancel_pending_task",
            description=(
                "取消一个不再需要执行的任务。未派发的任务直接从计划移除；已派发但仍在"
                "排队（queued）的任务会被跳过；正在运行（running）的任务会被软中断。"
                "取消后该任务不会出现在后续聚合结果中，请勿重派。"
            ),
            parameters=_CANCEL_SCHEMA,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        return self._call(
            "cancel_pending_task",
            task_id=str(kwargs.get("task_id", "")),
            reason=kwargs.get("reason"),
        )


class AddTaskToPlanTool(_ReplanToolBase):
    """添加新任务到计划（可声明依赖）。"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="add_task_to_plan",
            description=(
                "在执行过程中发现新的必要工作时，把它加入计划。可传 depends_on 声明依赖"
                "（只能引用已存在的 task_id），下游任务会等依赖完成后才启动。"
                "添加后调用 dispatch_subagents 派发即可执行。"
            ),
            parameters=_ADD_SCHEMA,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        raw_deps = kwargs.get("depends_on")
        deps: List[str] = (
            [str(d) for d in raw_deps] if isinstance(raw_deps, list) else []
        )
        return self._call(
            "add_task_to_plan",
            task_id=str(kwargs.get("task_id", "")),
            goal=str(kwargs.get("goal", "")),
            agent_id=str(kwargs.get("agent_id", "")),
            depends_on=deps,
        )
