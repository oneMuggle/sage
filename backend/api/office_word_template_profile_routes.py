"""Word template profile routes (M1a)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from backend.office.errors import OfficeFileNotFoundError
from backend.office.path_safety import resolve_within
from backend.office.storage import validate_workspace
from backend.office.word_template_profile import analyze_word_template_profile
from backend.office.word_template_profile_fill import fill_word_template_profile

router = APIRouter(prefix="/office/word/template", tags=["office"])


class WordTemplateProfileRequest(BaseModel):
    """Analyze a .docx template into M1a slots."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class WordTemplateProfileFillRequest(BaseModel):
    """Fill a .docx template profile into a new file."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str
    output_filename: str
    data: Dict[str, Any]
    images: Optional[Dict[str, str]] = None


def _resolve_template(workspace_path: str, file_path: str) -> Path:
    workspace = validate_workspace(workspace_path)
    target = resolve_within(workspace, Path(file_path))
    if not target.is_file():
        raise OfficeFileNotFoundError(target)
    return target


@router.post("/profile")
def analyze_word_template_profile_endpoint(req: WordTemplateProfileRequest) -> dict:
    """Analyze content controls, bookmarks, placeholders and simple Jinja."""
    target = _resolve_template(req.workspace_path, req.file_path)
    return analyze_word_template_profile(
        target, workspace_path=str(Path(req.workspace_path).resolve())
    )


@router.post("/profile/fill")
def fill_word_template_profile_endpoint(req: WordTemplateProfileFillRequest) -> dict:
    """Fill M1a template slots into a new .docx (never overwrites the template)."""
    return fill_word_template_profile(
        Path(req.template_path),
        req.data,
        req.output_filename,
        workspace_path=str(Path(req.workspace_path).resolve()),
        images=req.images,
    )


__all__ = [
    "WordTemplateProfileFillRequest",
    "WordTemplateProfileRequest",
    "analyze_word_template_profile_endpoint",
    "fill_word_template_profile_endpoint",
    "router",
]
