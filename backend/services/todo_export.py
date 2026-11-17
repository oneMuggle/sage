"""待办导出（JSON / Markdown）。

纯函数：输入 :class:`~backend.services.todo_service.Todo` 列表，输出
``{filename, format, content}`` envelope。IPC 通道统一走 ``res.json()``，
渲染层据此组装 Blob 触发下载。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from backend.services.todo_service import Todo


def build_export(todos: List[Todo], fmt: str) -> Dict[str, str]:
    """按 ``fmt``（json|md）生成导出 envelope。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if fmt == "md":
        return {
            "filename": f"sage-todos-{stamp}.md",
            "format": "md",
            "content": _todos_to_markdown(todos),
        }
    return {
        "filename": f"sage-todos-{stamp}.json",
        "format": "json",
        "content": json.dumps(
            [t.model_dump() for t in todos], ensure_ascii=False, indent=2
        ),
    }


def _todos_to_markdown(todos: List[Todo]) -> str:
    lines = ["# Sage 待办导出", ""]
    for todo in todos:
        box = "x" if todo.status == "completed" else " "
        meta = []
        if todo.priority and todo.priority != "medium":
            meta.append(f"优先级: {todo.priority}")
        if todo.due_at:
            meta.append(f"截止: {todo.due_at}")
        if todo.project_tag:
            meta.append(f"项目: {todo.project_tag}")
        suffix = f"（{'，'.join(meta)}）" if meta else ""
        lines.append(f"- [{box}] {todo.title}{suffix}")
        if todo.description:
            lines.append(f"  {todo.description}")
    lines.append("")
    return "\n".join(lines)
