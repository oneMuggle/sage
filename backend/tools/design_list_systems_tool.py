"""Design system listing tool for the LLM tool loop."""
from __future__ import annotations

from typing import Any

from backend.design import get_design_studio
from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class DesignListSystemsTool(BaseTool):
    """List available design systems."""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="design_list_systems",
            description=(
                "List all available design systems. Returns system IDs, names, "
                "descriptions, and categories. Use this to discover which design "
                "systems are available before creating a design project."
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

        systems = studio.list_systems()
        result = []
        for system in systems:
            result.append({
                "id": system.id,
                "name": system.name,
                "description": system.description,
                "category": system.category,
            })

        return ToolResult(success=True, content={"systems": result})


__all__ = ["DesignListSystemsTool"]
