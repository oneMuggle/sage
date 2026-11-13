"""Design export tool for the LLM tool loop."""
from __future__ import annotations

from typing import Any

from backend.design import get_design_studio
from backend.design.export import DesignExporter
from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class DesignExportTool(BaseTool):
    """Export a design artifact to PDF, ZIP, or HTML."""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="design_export",
            description=(
                "Export a design artifact to PDF, ZIP, or HTML format. "
                "Returns the file path (for PDF/ZIP) or HTML content (for HTML format). "
                "Use format='pdf' to generate a PDF file, format='zip' for a self-contained "
                "ZIP archive, or format='html' (default) to retrieve the raw HTML content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID (from design_generate)",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["pdf", "zip", "html"],
                        "description": (
                            "Output format: 'pdf' (PDF file), 'zip' (ZIP archive), "
                            "or 'html' (HTML content, default)"
                        ),
                    },
                },
                "required": ["project_id"],
            },
        )

    def execute(
        self,
        project_id: str = "",
        format: str = "html",
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

            if format == "html":
                # Backward-compatible: return HTML content as before
                return ToolResult(
                    success=True,
                    content={
                        "project_id": project_id,
                        "artifact_id": latest.id,
                        "artifact_version": latest.version,
                        "artifact_title": latest.title,
                        "file_path": latest.file_path,
                        "html_content": latest.html_content,
                        "format": "html",
                    },
                )

            # Export to PDF or ZIP
            workspace = studio._workspace
            output_dir = workspace / "design" / project_id
            output_dir.mkdir(parents=True, exist_ok=True)

            exporter = DesignExporter()
            result = exporter.export(
                html=latest.html_content,
                output_dir=output_dir,
                format=format,
                filename=f"v{latest.version}",
            )

            if not result.ok:
                return ToolResult(
                    success=False,
                    error=f"export_failed: {result.error}",
                )

            return ToolResult(
                success=True,
                content={
                    "project_id": project_id,
                    "artifact_id": latest.id,
                    "artifact_version": latest.version,
                    "artifact_title": latest.title,
                    "file_path": result.file_path,
                    "format": format,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"export_failed: {str(e)}")


__all__ = ["DesignExportTool"]
