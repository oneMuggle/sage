# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Pydantic models for the M2 Word style template library (样式模板库).

A style template is a saved generation-side style profile: a snapshot of a
``WordFormatSpec`` (JSON) plus provenance (``source_kind`` / ``source_ref``).
The snapshot is intentional — later edits to the rule pack or preset it was
derived from must not silently rewrite templates the user already saved.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

STYLE_TEMPLATE_SOURCE_KINDS = ("preset", "rulepack", "manual")


class OfficeStyleTemplate(BaseModel):
    """One row from ``office_style_templates``."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    workspace_path: str = ""
    name: str = Field(min_length=1, max_length=200)
    format_spec: Dict[str, Any] = Field(default_factory=dict)
    source_kind: Literal["preset", "rulepack", "manual"] = "manual"
    source_ref: Optional[str] = Field(default=None, max_length=2000)
    is_default: bool = False
    created_at: int = 0
    updated_at: int = 0


class OfficeStyleTemplateListResult(BaseModel):
    """GET /office/word/style-templates result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    workspace_path: str = ""
    templates: List[OfficeStyleTemplate] = Field(default_factory=list)


class OfficeStyleTemplateDetailResult(BaseModel):
    """POST/GET single style template result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    template: OfficeStyleTemplate
