"""``project_advise`` 工具 -- AI 项目进度顾问（M3）。

LLM 在对话中可直接调用此工具获取项目健康评分和改进建议。
内部委托 ProjectAdvisor，通过 asyncio.run 桥接同步 execute()。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

TOOL_NAME = "project_advise"


class ProjectAdviseTool(BaseTool):
    """AI 项目进度顾问工具 -- 分析项目状态并给出建议。"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=TOOL_NAME,
            description=(
                "分析当前项目的进度、风险和改进行动。"
                "返回健康评分（0-100）、风险列表和改进建议。"
                "结果会缓存 30 分钟，可通过 force_refresh 强制刷新。"
                "需要当前有活跃的项目上下文（workspace）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "项目 ID；不传则从 workspace 自动推断",
                    },
                    "force_refresh": {
                        "type": "boolean",
                        "description": "是否强制刷新（忽略 30 分钟缓存）",
                    },
                },
                "required": [],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        project_id: Optional[str] = kwargs.get("project_id")
        force_refresh: bool = bool(kwargs.get("force_refresh", False))

        if not project_id:
            project_id = self._resolve_project_id_from_workspace()

        if not project_id:
            return ToolResult.error(
                "无法确定项目 ID。请确保当前会话已绑定项目，"
                "或显式传入 project_id 参数。"
            )

        try:
            result = asyncio.run(
                self._analyze(project_id, force_refresh=force_refresh)
            )
        except ValueError as exc:
            return ToolResult.error(str(exc))
        except RuntimeError as exc:
            return ToolResult.error(f"顾问分析失败: {exc}")

        return ToolResult.success(
            json.dumps(result, ensure_ascii=False, indent=2),
            metadata={"project_id": project_id, "health_score": result["health_score"]},
        )

    async def _analyze(self, project_id: str, *, force_refresh: bool) -> dict:
        from backend.services.project_advisor import ProjectAdvisor

        advisor = ProjectAdvisor()
        if not advisor.available:
            raise RuntimeError("LLM 客户端不可用，请在设置中配置 AI 端点")

        advice = await advisor.analyze(
            project_id=project_id,
            force_refresh=force_refresh,
        )
        return advice.to_dict()

    def _resolve_project_id_from_workspace(self) -> Optional[str]:
        """从当前 workspace 推断项目 ID。"""
        workspace = getattr(self.runtime, "workspace_path", None) if self.runtime else None
        if not workspace:
            return None
        try:
            from backend.data.project_repo import ProjectRepository

            project = ProjectRepository().find_by_path(workspace)
            return project.id if project else None
        except Exception:
            logger.debug("Failed to resolve project from workspace", exc_info=True)
            return None


__all__ = ["ProjectAdviseTool", "TOOL_NAME"]
