"""``project_decompose_tasks`` 工具 — AI 任务分解（M1）。

LLM 在对话中可直接调用此工具将用户需求拆解为里程碑树。
内部委托 ProjectTaskDecomposer，通过 asyncio.run 桥接同步 execute()。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

TOOL_NAME = "project_decompose_tasks"


class ProjectDecomposeTasksTool(BaseTool):
    """AI 任务分解工具——将需求拆解为里程碑树。"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=TOOL_NAME,
            description=(
                "将用户的自然语言需求分解为结构化的里程碑树。"
                "每个里程碑可以有子任务，并附带估算工时。"
                "需要当前有活跃的项目上下文（workspace）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "requirement": {
                        "type": "string",
                        "description": "需要分解的自然语言需求描述",
                    },
                    "project_id": {
                        "type": "string",
                        "description": (
                            "项目 ID；不传则使用当前 workspace 关联的项目"
                        ),
                    },
                    "context": {
                        "type": "string",
                        "description": "可选的补充上下文信息",
                    },
                },
                "required": ["requirement"],
            },
        )

    def execute(  # type: ignore[override]
        self,
        *,
        requirement: str,
        project_id: Optional[str] = None,
        context: Optional[str] = None,
        **_kwargs: Any,
    ) -> ToolResult:
        if not requirement or not requirement.strip():
            return ToolResult(
                success=False,
                output="requirement 不能为空",
            )

        # 如果没有 project_id，尝试从 workspace 上下文获取
        if not project_id:
            workspace = _kwargs.get("workspace") or _kwargs.get("cwd")
            if workspace:
                project_id = _resolve_project_for_workspace(str(workspace))
            if not project_id:
                return ToolResult(
                    success=False,
                    output=(
                        "未找到关联项目。请先注册项目（侧栏拖入目录），"
                        "或提供 project_id 参数。"
                    ),
                )

        try:
            result = asyncio.run(
                self._decompose(project_id, requirement, context)
            )
        except RuntimeError as exc:
            return ToolResult(
                success=False,
                output=f"任务分解失败: {exc}",
            )
        except ValueError as exc:
            return ToolResult(
                success=False,
                output=str(exc),
            )

        # 格式化为可读输出
        preview = result.to_preview()
        formatted = json.dumps(
            {
                "reasoning": result.reasoning,
                "milestones": preview,
                "total_milestones": sum(
                    1 + len(m.get("children", [])) for m in preview
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

        return ToolResult(
            success=True,
            output=f"AI 任务分解完成:\n{formatted}",
        )

    async def _decompose(self, project_id, requirement, context):
        from backend.services.project_task_decomposer import (
            ProjectTaskDecomposer,
        )

        decomposer = ProjectTaskDecomposer()
        return await decomposer.decompose(
            project_id=project_id,
            requirement=requirement,
            context=context,
        )


def _resolve_project_for_workspace(workspace: str) -> Optional[str]:
    """从 workspace 路径查找关联的 project_id。"""
    try:
        from backend.data.project_repo import ProjectRepository

        repo = ProjectRepository()
        project = repo.get_project_for_workspace(workspace)
        if project:
            return project.id
    except Exception:
        pass
    return None


__all__ = ["ProjectDecomposeTasksTool", "TOOL_NAME"]
