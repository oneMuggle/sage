"""Design generation tool for the LLM tool loop."""
from __future__ import annotations

from typing import Any

from backend.design import get_design_studio
from backend.design.async_bridge import DEFAULT_TIMEOUT, run_sync
from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class DesignGenerateTool(BaseTool):
    """Generate an HTML design artifact."""

    risk = RiskClass.WRITE_LOCAL
    # LLM 生成是长耗时阻塞调用 —— 声明 is_blocking 让 run_loop 卸载到
    # executor 线程，避免堵住事件循环。
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="design_generate",
            description=(
                "Generate an HTML design artifact. Creates a new design project and "
                "generates the first artifact version. Returns the project ID and "
                "artifact details. Use design_iterate to refine the artifact with feedback."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Project name (e.g., 'Annual Report 2026')",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["prototype", "deck"],
                        "description": "Artifact kind: 'prototype' (HTML/CSS) or 'deck' (presentation)",
                    },
                    "system_id": {
                        "type": "string",
                        "description": "Design system ID (from design_list_systems)",
                    },
                    "template_id": {
                        "type": "string",
                        "description": "Template ID (from design_list_templates)",
                    },
                    "brief": {
                        "type": "string",
                        "description": "Design brief describing what to generate",
                    },
                },
                "required": ["name", "kind", "system_id", "template_id", "brief"],
            },
        )

    def execute(
        self,
        name: str = "",
        kind: str = "",
        system_id: str = "",
        template_id: str = "",
        brief: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        """Synchronous entry point (tool dispatch contract).

        ``DesignStudio.generate`` is a coroutine, so it is driven to
        completion on the shared design loop via ``run_sync``.
        """
        if not name or not kind or not system_id or not template_id or not brief:
            return ToolResult(
                success=False,
                error="missing_required_parameters",
            )

        studio = get_design_studio()
        if studio is None:
            return ToolResult(success=False, error="design_studio_not_initialized")

        try:
            # Create project
            project = studio.create_project(
                name=name,
                kind=kind,
                system_id=system_id,
                template_id=template_id,
                brief=brief,
            )

            # Generate artifact (coroutine → run to completion on shared loop)
            artifact = run_sync(
                studio.generate(project.id), timeout=DEFAULT_TIMEOUT,
            )

            return ToolResult(
                success=True,
                content={
                    "project_id": project.id,
                    "project_name": project.name,
                    "artifact_id": artifact.id,
                    "artifact_version": artifact.version,
                    "artifact_title": artifact.title,
                    "file_path": artifact.file_path,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"generation_failed: {str(e)}")


__all__ = ["DesignGenerateTool"]
