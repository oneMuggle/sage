"""
Todo 工具 - agent 内部任务清单（移植 claw-code execute_todo_write）

与 claw-code / Claude Code 的 TodoWrite 一致：**全量替换语义**——每次
调用用传入的 todos 列表整体替换当前会话的清单。状态保存在内存
（``todo_state`` 模块，按 session_id 隔离），不触碰用户数据，故能力
分级为 READ（见 permissions.py 注释）。

渲染输出为 markdown checklist + 计数，供前端直接展示进度。
"""

import logging
from typing import Any, Dict, List

from .base import BaseTool, ToolResult, ToolSchema
from .todo_state import get_todo_store, resolve_session_id

logger = logging.getLogger(__name__)

#: claw-code 无条目数上限；sage 加 50 条守卫防止 LLM 灌爆上下文
MAX_TODO_ITEMS = 50

#: 合法状态枚举（与 Claude TodoWrite 一致）
VALID_TODO_STATUSES = ("pending", "in_progress", "completed")

#: 状态 → markdown checklist 前缀 / 后缀
_STATUS_PREFIX = {
    "pending": "- [ ] ",
    "in_progress": "- [ ] ",
    "completed": "- [x] ",
}


def validate_todos(todos: Any) -> List[str]:
    """校验 todos 参数，返回错误消息列表（空列表 = 通过）。"""
    if not isinstance(todos, list):
        return ["todos 必须是数组"]
    if not todos:
        return ["todos 不能为空"]
    if len(todos) > MAX_TODO_ITEMS:
        return [f"todos 条目数 {len(todos)} 超过上限 {MAX_TODO_ITEMS}"]

    errors: List[str] = []
    for index, item in enumerate(todos):
        label = f"todos[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} 必须是对象")
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"{label}.content 必须是非空字符串")
        status = item.get("status")
        if status not in VALID_TODO_STATUSES:
            errors.append(f"{label}.status 必须是 {'/'.join(VALID_TODO_STATUSES)} 之一")
        active_form = item.get("activeForm")
        if active_form is not None and not isinstance(active_form, str):
            errors.append(f"{label}.activeForm 必须是字符串（可选字段）")
    return errors


def render_checklist(todos: List[Dict[str, Any]]) -> str:
    """把 todos 渲染成 markdown checklist（in_progress 加进行中标记）。"""
    lines = []
    for item in todos:
        status = item.get("status", "pending")
        line = _STATUS_PREFIX.get(status, "- [ ] ") + str(item.get("content", ""))
        if status == "in_progress":
            line += "（进行中）"
        lines.append(line)
    return "\n".join(lines)


def count_statuses(todos: List[Dict[str, Any]]) -> Dict[str, int]:
    """统计各状态条目数。"""
    counts = {"pending": 0, "in_progress": 0, "completed": 0, "total": len(todos)}
    for item in todos:
        status = item.get("status")
        if status in counts:
            counts[status] += 1
    return counts


class TodoWriteTool(BaseTool):
    """Todo 清单工具 - 全量替换会话内任务列表"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="todo_write",
            description=(
                "写入/更新当前会话的任务清单（全量替换：每次调用传入完整列表）。"
                "用于跟踪多步骤任务进度。status: pending / in_progress / completed。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": f"完整任务列表（最多 {MAX_TODO_ITEMS} 条）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string", "description": "任务内容"},
                                "status": {
                                    "type": "string",
                                    "enum": list(VALID_TODO_STATUSES),
                                    "description": "任务状态",
                                },
                                "activeForm": {
                                    "type": "string",
                                    "description": "进行时态描述 (可选，如 '正在分析代码')",
                                },
                            },
                            "required": ["content", "status"],
                        },
                    }
                },
                "required": ["todos"],
            },
        )

    def execute(self, todos: Any = None, **kwargs) -> ToolResult:
        """
        全量替换当前会话的 todo 列表

        Args:
            todos: [{content, status, activeForm?}, ...]

        Returns:
            ToolResult；content 含 checklist（markdown）/ counts /
            session_id / replaced_count（被替换的旧条目数）。
        """
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(
                success=False,
                error=f"未知参数: {names}（合法参数: todos）",
            )

        errors = validate_todos(todos)
        if errors:
            return ToolResult(success=False, error="；".join(errors))

        try:
            session_id = resolve_session_id()
            store = get_todo_store()
            previous = store.get(session_id) or []
            store.replace(session_id, todos)

            return ToolResult(
                success=True,
                content={
                    "checklist": render_checklist(todos),
                    "counts": count_statuses(todos),
                    "session_id": session_id,
                    "replaced_count": len(previous),
                },
            )
        except Exception as e:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
            logger.error("todo_write 执行失败: %s", e)
            return ToolResult(success=False, error=f"todo 写入失败: {e}")
