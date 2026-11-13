"""Design chart embedding tool for the LLM tool loop (M5a).

Renders a chart spec with matplotlib and injects the resulting data URL
into the latest artifact's HTML, appending a new artifact version. This
lets the model add data visuals to a deck without regenerating the whole
document through the LLM.
"""
from __future__ import annotations

from typing import Any

from backend.design import get_design_studio
from backend.design.chart_embedder import DEFAULT_SLOT, ChartEmbedder
from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class DesignEmbedChartTool(BaseTool):
    """Render a chart and inject it into the latest design artifact."""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="design_embed_chart",
            description=(
                "Render a chart (bar/line/hbar/pie) into the latest artifact of a "
                "design project. The PNG is embedded inline as a data URL at the "
                "{{CHART}} placeholder when present, otherwise appended before "
                "</body>. Creates a new artifact version; no LLM call is made. "
                "Use this to add data visuals to a deck or prototype."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID (from design_generate)",
                    },
                    "chart": {
                        "type": "object",
                        "description": (
                            "Chart spec: type (line|bar|hbar|pie), optional title "
                            "and labels, and 1-10 series each with name and y values."
                        ),
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["line", "bar", "hbar", "pie"],
                            },
                            "title": {"type": "string"},
                            "labels": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "series": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "x": {
                                            "type": "array",
                                            "items": {
                                                "type": ["string", "number"],
                                            },
                                        },
                                        "y": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                        },
                                    },
                                    "required": ["name", "y"],
                                },
                            },
                        },
                        "required": ["type", "series"],
                    },
                    "slot": {
                        "type": "string",
                        "description": (
                            "Placeholder to replace. Defaults to '{{CHART}}'; "
                            "custom slots can be any unique HTML marker."
                        ),
                    },
                },
                "required": ["project_id", "chart"],
            },
        )

    def execute(
        self,
        project_id: str = "",
        chart: Any = None,
        slot: str = DEFAULT_SLOT,
        **kwargs: Any,
    ) -> ToolResult:
        if not project_id or not chart:
            return ToolResult(
                success=False,
                error="missing_required_parameters",
            )

        studio = get_design_studio()
        if studio is None:
            return ToolResult(success=False, error="design_studio_not_initialized")

        try:
            from backend.office.models import ChartSpec

            spec = ChartSpec(**chart)
            latest = studio.get_latest_artifact(project_id)
            if latest is None:
                return ToolResult(success=False, error="no_artifacts_found")

            embedder = ChartEmbedder()
            data_url = embedder.spec_to_data_url(spec)
            embedded = embedder.embed(
                latest.html_content, data_url, slot=slot or DEFAULT_SLOT,
            )
            artifact = studio.add_artifact(
                project_id,
                embedded.html,
                title=latest.title,
            )

            return ToolResult(
                success=True,
                content={
                    "project_id": project_id,
                    "artifact_id": artifact.id,
                    "artifact_version": artifact.version,
                    "artifact_title": artifact.title,
                    "injected_at_slot": embedded.injected_at_slot,
                    "chart_type": spec.type,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"chart_embed_failed: {e}")


__all__ = ["DesignEmbedChartTool"]
