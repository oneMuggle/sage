"""Design iteration tool for the LLM tool loop."""
from __future__ import annotations

from typing import Any

from backend.design import get_design_studio
from backend.design.async_bridge import run_sync
from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class DesignIterateTool(BaseTool):
    """Iterate on a design artifact with user feedback."""

    risk = RiskClass.WRITE_LOCAL
    # 同 design_generate：LLM 再生成是长耗时阻塞调用。
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="design_iterate",
            description=(
                "Iterate on an existing design artifact with user feedback. "
                "Generates a new version of the artifact incorporating the feedback. "
                "Returns the updated artifact details with an incremented version number."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID (from design_generate)",
                    },
                    "feedback": {
                        "type": "string",
                        "description": "User feedback describing what to change",
                    },
                },
                "required": ["project_id", "feedback"],
            },
        )

    def execute(
        self,
        project_id: str = "",
        feedback: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        """Synchronous entry point (tool dispatch contract).

        ``DesignStudio.iterate`` is a coroutine, so it is driven to
        completion on the shared design loop via ``run_sync``.
        """
        if not project_id or not feedback:
            return ToolResult(
                success=False,
                error="missing_required_parameters",
            )

        studio = get_design_studio()
        if studio is None:
            return ToolResult(success=False, error="design_studio_not_initialized")

        try:
            artifact = run_sync(studio.iterate(project_id, feedback))

            return ToolResult(
                success=True,
                content={
                    "project_id": project_id,
                    "artifact_id": artifact.id,
                    "artifact_version": artifact.version,
                    "artifact_title": artifact.title,
                    "file_path": artifact.file_path,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"iteration_failed: {str(e)}")


__all__ = ["DesignIterateTool"]
