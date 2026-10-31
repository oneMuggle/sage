"""REST endpoints for read-only LaTeX preview."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from backend.office.latex.service import (
    analyze_latex_template_file,
    fill_latex_template_file,
    read_latex_file,
)

router = APIRouter(prefix="/latex", tags=["latex"])


class LatexReadRequest(BaseModel):
    """Read a workspace .tex file and return structured preview blocks."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


@router.post("/read")
def read_latex_endpoint(req: LatexReadRequest) -> dict:
    """Parse a .tex file inside the workspace and return a preview payload."""
    return read_latex_file(
        Path(req.file_path),
        workspace=Path(req.workspace_path),
    )


class LatexTemplateAnalyzeRequest(BaseModel):
    """Analyze a LaTeX template and return its slots/style/macros."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class LatexTemplateFillRequest(BaseModel):
    """Fill a LaTeX template's slots into a new .tex file."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str
    output_filename: str
    data: Dict[str, Any]


@router.post("/template/analyze")
def analyze_latex_template_endpoint(req: LatexTemplateAnalyzeRequest) -> dict:
    """Extract a LaTeX template profile (slots/style/macros)."""
    return analyze_latex_template_file(
        Path(req.file_path),
        workspace=Path(req.workspace_path),
    )


@router.post("/template/fill")
def fill_latex_template_endpoint(req: LatexTemplateFillRequest) -> dict:
    """Fill a LaTeX template into a new .tex file (never overwrites template)."""
    return fill_latex_template_file(
        Path(req.template_path),
        req.data,
        req.output_filename,
        workspace=Path(req.workspace_path),
    )


__all__ = [
    "LatexReadRequest",
    "LatexTemplateAnalyzeRequest",
    "LatexTemplateFillRequest",
    "analyze_latex_template_endpoint",
    "fill_latex_template_endpoint",
    "read_latex_endpoint",
    "router",
]
