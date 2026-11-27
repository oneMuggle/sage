"""Word 格式转换路由（P0）：.doc ↔ .docx。

挂载于 ``backend/api/office_routes.py``（前缀 ``/api/v1``），
路径为 ``POST /api/v1/office/word/convert``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.office.path_safety import resolve_within
from backend.office.storage import validate_workspace
from backend.office.word_convert import convert_word

router = APIRouter(prefix="/word", tags=["office"])


class WordConvertRequest(BaseModel):
    """格式转换请求：源文件必须在工作区内，输出落在源文件同目录。"""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    target_format: Literal["docx", "doc"] = "docx"
    output_filename: Optional[str] = None
    overwrite: bool = False
    timeout_seconds: int = Field(default=120, ge=1, le=1800)


@router.post("/convert")
def convert_word_endpoint(req: WordConvertRequest) -> dict:
    """把 .doc 转为 .docx（或反向），返回 ok/method/output_path/error。"""
    workspace = validate_workspace(Path(req.workspace_path))
    source = resolve_within(workspace, Path(req.file_path))
    result = convert_word(
        source,
        workspace,
        target_format=req.target_format,
        output_filename=req.output_filename,
        overwrite=req.overwrite,
        timeout_seconds=req.timeout_seconds,
    )
    return result.model_dump(mode="json")


__all__ = ["WordConvertRequest", "convert_word_endpoint", "router"]
