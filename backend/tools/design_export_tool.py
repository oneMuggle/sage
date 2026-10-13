"""Design export tool for the LLM tool loop."""
from __future__ import annotations

from typing import Any

from backend.design import get_design_studio
from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class DesignExportTool(BaseTool):
    """Export a design artifact."""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="design_export",
            description=(
                "Export a design artifact. Returns the latest artifact's HTML content "
                "and file path for the given project. Use this to retrieve the generated "
                "design for preview or further processing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID (from design_generate)",
                    },
                },
                "required": ["project_id"],
            },
        )

    def execute(
        self,
        project_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not project_id:
            return ToolResult(
                success=False,
                error="missing_required_parameters",
            )

        studio = get_design_studio()
        if studio is None:
            return ToolResult(success=False, error="design_studio_not_initialized")

        try:
            # Get the latest artifact for the project
            latest = studio.get_latest_artifact(project_id)
            if latest is None:
                return ToolResult(
                    success=False,
                    error="no_artifacts_found",
                )

            return ToolResult(
                success=True,
                content={
                    "project_id": project_id,
                    "artifact_id": latest.id,
                    "artifact_version": latest.version,
                    "artifact_title": latest.title,
                    "file_path": latest.file_path,
                    "html_content": latest.html_content,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"export_failed: {str(e)}")


__all__ = ["DesignExportTool"]
