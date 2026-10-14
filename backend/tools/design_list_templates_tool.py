"""Design template listing tool for the LLM tool loop."""
from __future__ import annotations

from typing import Any

from backend.design import get_design_studio
from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class DesignListTemplatesTool(BaseTool):
    """List available design templates."""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="design_list_templates",
            description=(
                "List all available design templates. Returns template IDs, names, "
                "kinds (prototype/deck), and descriptions. Use this to discover which "
                "templates are available before creating a design project."
            ),
            parameters={
                "type": "object",
                "properties": {},
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        studio = get_design_studio()
        if studio is None:
            return ToolResult(success=False, error="design_studio_not_initialized")

        templates = studio.list_templates()
        result = []
        for template in templates:
            result.append({
                "id": template.id,
                "name": template.name,
                "kind": template.kind,
                "description": template.description,
            })

        return ToolResult(success=True, content={"templates": result})


__all__ = ["DesignListTemplatesTool"]
