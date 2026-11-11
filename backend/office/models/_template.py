from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ._shared import OfficeDocType, OfficeDocumentSummary


class TemplatePlaceholderType(str, Enum):
    """Type of placeholder in a Word template."""

    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    DATE = "date"
    RICH_TEXT = "rich_text"


class PlaceholderLocation(str, Enum):
    """Location of placeholder in the document."""

    BODY = "body"
    TABLE = "table"
    HEADER = "header"
    FOOTER = "footer"
    TEXT_BOX = "text_box"


class TemplatePlaceholder(BaseModel):
    """One placeholder found in a Word template."""

    model_config = ConfigDict(extra="forbid")

    name: str
    raw_tag: str
    type: TemplatePlaceholderType
    location: PlaceholderLocation
    paragraph_index: Optional[int] = None
    table_index: Optional[int] = None
    row_index: Optional[int] = None
    col_index: Optional[int] = None
    format_hint: Optional[str] = None


class WordTemplateAnalysis(BaseModel):
    """Result of analyzing a Word template."""

    model_config = ConfigDict(extra="forbid")

    file_path: str
    placeholders: List[TemplatePlaceholder]
    summary: OfficeDocumentSummary
    has_jinja_control: bool = False


class WordTemplateAnalyzeRequest(BaseModel):
    """Request to analyze a Word template."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str


class WordTemplateFillRequest(BaseModel):
    """Request to fill a Word template with data."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str
    output_filename: str
    data: Dict[str, Any]
    images: Optional[Dict[str, str]] = None


class WordTemplateFillResult(BaseModel):
    """Result of filling a Word template."""

    model_config = ConfigDict(extra="forbid")

    output_path: str
    filename: str
    file_size_bytes: int
    filled_count: int
    unfilled_placeholders: List[str]


# ──────────────────────────────────────────────────────────────────────
# Template library models (Office parity batch 3 — Item 3.2)
# ──────────────────────────────────────────────────────────────────────


class TemplateLibraryPlaceholder(BaseModel):
    """One placeholder advertised by a template-library entry."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: TemplatePlaceholderType
    description: str = Field(default="", description="占位符用途说明（中文，展示给用户）")


class TemplateLibraryEntry(BaseModel):
    """One template in the library: builtin 中文办公模板 or workspace user template."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description=(
            "builtin: stable id matching ^[a-z0-9_]{1,64}$; "
            "workspace: 'ws_'-prefixed sanitized filename stem"
        )
    )
    name: str = Field(description="展示名称（中文）")
    description: str = ""
    doc_type: OfficeDocType = OfficeDocType.WORD
    placeholders: List[TemplateLibraryPlaceholder] = Field(default_factory=list)
    source: Literal["builtin", "workspace"]
    filename: Optional[str] = Field(
        default=None,
        description=(
            "workspace 模板专用：office/templates/ 下的文件名；"
            "builtin 模板为 None（按 id 实例化）"
        ),
    )


class TemplateLibraryResponse(BaseModel):
    """GET /api/v1/office/templates."""

    model_config = ConfigDict(extra="forbid")

    templates: List[TemplateLibraryEntry]


class OfficeTemplateInstantiateRequest(BaseModel):
    """POST /api/v1/office/templates/instantiate.

    ``template_id``（builtin）与 ``workspace_template``（office/templates/ 下的
    文件名）二选一；同时给出报 400。round 3 N2 起 builtin 模板覆盖 word /
    excel / ppt 三种 doc_type，输出文件名扩展名须与模板类型一致。
    """

    model_config = ConfigDict(extra="forbid")

    # P7 (2026-09-14): 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询）
    task_id: Optional[str] = Field(default=None, max_length=100)

    workspace_path: str
    template_id: Optional[str] = Field(
        default=None, description="builtin 模板 id，如 'weekly_report'（word）、'budget_sheet'（excel）、'kickoff_deck'（ppt）"
    )
    workspace_template: Optional[str] = Field(
        default=None,
        description=(
            "workspace 模板文件名（office/templates/ 内，支持 .docx/.xlsx/.pptx；"
            "省略扩展名时按 docx→xlsx→pptx 顺序匹配）"
        ),
    )
    filename: str = Field(
        min_length=1,
        max_length=200,
        description="输出文件名（缺扩展名时自动补全，须与模板 doc_type 一致：.docx/.xlsx/.pptx）",
    )
    data: Dict[str, Any] = Field(default_factory=dict)
    images: Optional[Dict[str, str]] = Field(
        default=None,
        description="占位符名 → 图片路径或 data:image URI（与 /word/fill-template 一致，≤10MB）",
    )


