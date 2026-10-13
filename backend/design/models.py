"""Pydantic models for the design studio module."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DesignSystem(BaseModel):
    """A design system definition (DESIGN.md + tokens)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: str
    description: str
    design_md: str
    tokens_css: str
    design_tokens: dict
    tags: list[str]


class DesignTemplate(BaseModel):
    """A generation template (SKILL.md + assets)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: Literal["prototype", "deck"]
    description: str
    skill_md: str
    example_html: str | None = None
    assets: dict[str, str]
    design_system_required: bool


class DesignProject(BaseModel):
    """A design project (user session)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: Literal["prototype", "deck"]
    system_id: str
    template_id: str
    brief: str
    status: Literal["draft", "generating", "complete", "error"]
    created_at: datetime
    updated_at: datetime


class DesignArtifact(BaseModel):
    """A generated design artifact (one version of a project's output)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    version: int
    html_content: str
    css_injected: str
    title: str
    file_path: str
    kind: Literal["html", "deck", "standalone"]
    export_formats: list[str]
    source_prompt: str
    created_at: datetime


class DesignGenerateRequest(BaseModel):
    """Request to generate a new design artifact."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    brief: str
    system_id: str
    template_id: str
    model_id: str | None = None


class DesignIterateRequest(BaseModel):
    """Request to iterate on an existing design artifact."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    feedback: str
    model_id: str | None = None


class DesignExportRequest(BaseModel):
    """Request to export a design artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    format: Literal["html", "pdf", "pptx", "zip"]
