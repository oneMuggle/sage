"""plan_write 工具 —— 会话内结构化执行计划（对标增强 Phase-2 G3）。

对标 Qoder Quest Mode / ZCode 计划模式：复杂任务先产出「目标 → 分步
计划 → 每步验收」的结构化计划，再逐步执行。与 ``todo_write`` 的区别：
todo 是执行过程中的进度清单（短平快的任务项），plan 是执行前的整体
方案（步骤 + 依据 + 验收标准），面向"先想清楚再动手"。

存储复用 ``todo_state`` 的会话隔离模式（纯内存、LRU、全量替换语义）。
前端 Orchestration/TodoListSection 已订阅 todo 变更 —— plan 独立存储，
UI 接入属前端里程碑（后端先给 LLM 提供能力面）。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema
from .todo_state import SessionStateStore, resolve_session_id

_PLAN_STATUS_VALUES = ("pending", "in_progress", "done", "blocked")

#: 计划步骤数上限（防失控长计划）
MAX_PLAN_STEPS = 20

_plan_store: Optional[SessionStateStore] = None
_plan_lock = threading.Lock()


def get_plan_store() -> SessionStateStore:
    """进程级 plan 存储单例（与 todo 同实现，独立命名空间）。"""
    global _plan_store
    if _plan_store is None:
        with _plan_lock:
            if _plan_store is None:
                _plan_store = SessionStateStore()
    return _plan_store


def _validate_plan(goal: str, steps: List[Any]) -> Optional[str]:
    """校验计划结构；返回错误文案或 None。"""
    if not isinstance(goal, str) or not goal.strip():
        return "goal 不能为空"
    if not isinstance(steps, list) or not steps or len(steps) > MAX_PLAN_STEPS:
        return (
            "steps 必须是非空列表"
            if not isinstance(steps, list) or not steps
            else f"steps 数量 {len(steps)} 超过上限 {MAX_PLAN_STEPS}"
        )
    for index, step in enumerate(steps):
        error = _validate_step(index, step)
        if error is not None:
            return error
    return None


def _validate_step(index: int, step: Any) -> Optional[str]:
    if not isinstance(step, dict):
        return f"steps[{index}] 必须是对象"
    if not isinstance(step.get("title"), str) or not step["title"].strip():
        return f"steps[{index}].title 不能为空"
    if "status" in step and step["status"] not in _PLAN_STATUS_VALUES:
        return (
            f"steps[{index}].status 非法: {step['status']!r}"
            f"（合法值: {', '.join(_PLAN_STATUS_VALUES)}）"
        )
    return None


class PlanWriteTool(BaseTool):
    """写入/更新会话的结构化执行计划（全量替换语义）。"""

    risk = RiskClass.READ  # 会话内存状态，无文件副作用（与 todo_write 一致）

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="plan_write",
            description=(
                "为复杂任务写入/更新结构化执行计划：goal（目标）+ steps"
                "（[{title, detail?, status?}]，status ∈ pending/in_progress/"
                "done/blocked）。先规划后执行；执行中用 plan_write 更新各步"
                "状态。计划整体替换 —— 每次传入完整列表。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "任务目标（一句话）"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "步骤标题"},
                                "detail": {"type": "string", "description": "实施要点/依据（可选）"},
                                "status": {
                                    "type": "string",
                                    "description": "pending | in_progress | done | blocked（默认 pending）",
                                },
                            },
                            "required": ["title"],
                        },
                        "description": f"步骤列表（上限 {MAX_PLAN_STEPS}），全量替换",
                    },
                },
                "required": ["goal", "steps"],
            },
        )

    def execute(self, goal: str = "", steps: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}（合法参数: goal, steps）",
            )
        error = _validate_plan(goal, steps)
        if error is not None:
            return ToolResult(success=False, error=error)

        normalized: List[Dict[str, Any]] = []
        for step in steps or []:
            normalized.append(
                {
                    "title": step["title"].strip(),
                    "detail": (step.get("detail") or "").strip(),
                    "status": step.get("status") or "pending",
                }
            )
        plan = {"goal": goal.strip(), "steps": normalized}
        get_plan_store().replace(resolve_session_id(), plan)
        done = sum(1 for s in normalized if s["status"] == "done")
        return ToolResult(
            success=True,
            content={
                "goal": plan["goal"],
                "steps_total": len(normalized),
                "steps_done": done,
                "note": "计划已写入（全量替换）。执行中请随时更新各步 status。",
            },
        )


__all__ = ["PlanWriteTool", "get_plan_store", "MAX_PLAN_STEPS"]
