"""``project_extract_knowledge`` 工具 -- AI 对话知识提取（M2）。

LLM 在对话中可直接调用此工具从当前会话历史中提取项目知识。
内部委托 ProjectKnowledgeExtractor，通过 asyncio.run 桥接同步 execute()。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

TOOL_NAME = "project_extract_knowledge"


class ProjectExtractKnowledgeTool(BaseTool):
    """AI 对话知识提取工具 -- 从会话历史中提取项目知识建议。"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=TOOL_NAME,
            description=(
                "从当前会话的对话历史中提取值得持久化保存的项目知识。"
                "提取结果以建议列表返回，用户可通过前端界面确认后写入"
                "项目画像。需要当前有活跃的项目上下文（workspace）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "要分析的会话 ID；不传则使用当前会话",
                    },
                    "project_id": {
                        "type": "string",
                        "description": (
                            "项目 ID；不传则使用当前 workspace 关联的项目"
                        ),
                    },
                    "max_messages": {
                        "type": "integer",
                        "description": "最多分析最近多少条消息（默认 50）",
                    },
                },
                "required": ["session_id"],
            },
        )

    def execute(  # type: ignore[override]
        self,
        *,
        session_id: str,
        project_id: Optional[str] = None,
        max_messages: int = 50,
        **_kwargs: Any,
    ) -> ToolResult:
        if not session_id or not session_id.strip():
            return ToolResult(
                success=False,
                output="session_id 不能为空",
            )

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
                self._extract(project_id, session_id, max_messages)
            )
        except RuntimeError as exc:
            return ToolResult(
                success=False,
                output=f"知识提取失败: {exc}",
            )
        except ValueError as exc:
            return ToolResult(
                success=False,
                output=str(exc),
            )

        preview = result.to_preview()
        formatted = json.dumps(
            {
                "reasoning": result.reasoning,
                "entries_count": len(preview),
                "entries": preview,
            },
            ensure_ascii=False,
            indent=2,
        )

        return ToolResult(
            success=True,
            output=(
                f"AI 知识提取完成，发现 {len(preview)} 条建议:\n{formatted}"
            ),
        )

    async def _extract(self, project_id, session_id, max_messages):
        from backend.services.project_knowledge_extractor import (
            ProjectKnowledgeExtractor,
        )

        extractor = ProjectKnowledgeExtractor()
        return await extractor.extract(
            project_id=project_id,
            session_id=session_id,
            max_messages=max_messages,
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


__all__ = ["ProjectExtractKnowledgeTool", "TOOL_NAME"]
