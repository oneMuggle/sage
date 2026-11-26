"""Word template profile routes (M1a)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from backend.office.errors import OfficeFileNotFoundError
from backend.office.models import WordTemplateBlock
from backend.office.path_safety import resolve_within
from backend.office.storage import validate_workspace
from backend.office.word_template_profile import analyze_word_template_profile
from backend.office.word_template_profile_fill import fill_word_template_profile
from backend.office.word_template_refill import fill_word_template_blocks

router = APIRouter(prefix="/word/template", tags=["office"])


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


class WordTemplateRefillRequest(BaseModel):
    """Refill a .docx template by cloning block paragraphs (P0).

    适用于无占位符的模板：``blocks`` 按顺序写入，kind 对应模板中
    已排好版的 h1/h2/h3/正文/加粗段落；可选 ``anchors`` 显式指定
    块模板段落下标，或用 start/end 锚点文本截取替换区间。
    """

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str
    output_filename: str
    blocks: List[WordTemplateBlock]
    anchors: Optional[Dict[str, int]] = None
    start_anchor_text: Optional[str] = None
    end_anchor_text: Optional[str] = None
    start_paragraph: Optional[int] = None
    end_paragraph: Optional[int] = None


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


@router.post("/refill")
def refill_word_template_blocks_endpoint(req: WordTemplateRefillRequest) -> dict:
    """Clone template block paragraphs (no placeholders required) into a new .docx."""
    return fill_word_template_blocks(
        Path(req.template_path),
        req.blocks,
        req.output_filename,
        workspace_path=str(Path(req.workspace_path).resolve()),
        anchors=req.anchors,
        start_anchor_text=req.start_anchor_text,
        end_anchor_text=req.end_anchor_text,
        start_paragraph=req.start_paragraph,
        end_paragraph=req.end_paragraph,
    )


__all__ = [
    "WordTemplateProfileFillRequest",
    "WordTemplateProfileRequest",
    "WordTemplateRefillRequest",
    "analyze_word_template_profile_endpoint",
    "fill_word_template_profile_endpoint",
    "refill_word_template_blocks_endpoint",
    "router",
]
