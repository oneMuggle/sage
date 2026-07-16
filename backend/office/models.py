"""Office document Pydantic models.

Defines request/response models for the office API. All models are Pydantic v2
to match FastAPI 0.109 + pydantic 2.5 already pinned in requirements.txt.

Frontend IPC contracts (in src/shared/api/types.ts) MUST stay in sync with
the response shapes defined here.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class OfficeDocType(str, Enum):
    """Document type discriminator."""

    PPT = "ppt"
    WORD = "word"
    EXCEL = "excel"


class OfficeDocStatus(str, Enum):
    """Lifecycle status of an office document in the workspace."""

    PARSED = "parsed"  # read from an uploaded user file
    GENERATED = "generated"  # created from scratch via the generator
    EDITED = "edited"  # read + modified + saved as new file


# ──────────────────────────────────────────────────────────────────────
# Metadata
# ──────────────────────────────────────────────────────────────────────


class OfficeDocumentMetadata(BaseModel):
    """Per-document metadata captured at read/generate time."""

    model_config = ConfigDict(extra="forbid")

    page_count: Optional[int] = Field(
        default=None, description="Slide count (PPT) or page count (Word)"
    )
    sheet_count: Optional[int] = Field(default=None, description="Sheet count (Excel)")
    paragraph_count: Optional[int] = Field(default=None, description="Paragraph count (Word)")
    table_count: Optional[int] = Field(default=None, description="Table count (Word/PPT)")
    file_size_bytes: int = Field(ge=0, description="Output file size in bytes")


class OfficeDocumentSummary(BaseModel):
    """Compact document record — used in list API and as a sub-field in read results."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="UUIDv4 assigned by storage layer")
    workspace_path: str = Field(description="Absolute path to the user's workspace dir")
    doc_type: OfficeDocType
    original_filename: Optional[str] = Field(
        default=None, description="User's uploaded filename (None when generated from scratch)"
    )
    generated_filename: str = Field(description="On-disk filename in workspace/office/<id>/")
    status: OfficeDocStatus
    created_at: int = Field(description="Unix timestamp in milliseconds")
    updated_at: int = Field(description="Unix timestamp in milliseconds")
    metadata: OfficeDocumentMetadata


# ──────────────────────────────────────────────────────────────────────
# Read results — content extracted from a file
# ──────────────────────────────────────────────────────────────────────


class PptSlideContent(BaseModel):
    """One PPT slide's extracted content."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    title: Optional[str] = None
    text_blocks: List[str] = Field(default_factory=list)
    table_count: int = Field(ge=0, default=0)
    image_count: int = Field(ge=0, default=0)
    notes: Optional[str] = None


class OfficePptReadResult(BaseModel):
    """Result of POST /api/v1/office/ppt/read."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    slides: List[PptSlideContent]


class WordParagraphContent(BaseModel):
    """One Word paragraph."""

    model_config = ConfigDict(extra="forbid")

    style: str = Field(description="Paragraph style name, e.g. 'Normal', 'Heading 1'")
    text: str
    level: int = Field(ge=0, description="Heading level (0 for body text)")


class WordTableContent(BaseModel):
    """One Word table."""

    model_config = ConfigDict(extra="forbid")

    rows: List[List[str]]


class OfficeWordReadResult(BaseModel):
    """Result of POST /api/v1/office/word/read."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    paragraphs: List[WordParagraphContent]
    tables: List[WordTableContent]
    images: int = Field(ge=0, default=0)


class ExcelSheetContent(BaseModel):
    """One Excel sheet."""

    model_config = ConfigDict(extra="forbid")

    name: str
    rows: List[List[str]]
    max_row: int = Field(ge=0)
    max_col: int = Field(ge=0)


class OfficeExcelReadResult(BaseModel):
    """Result of POST /api/v1/office/excel/read."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    sheets: List[ExcelSheetContent]


# ──────────────────────────────────────────────────────────────────────
# Read requests
# ──────────────────────────────────────────────────────────────────────


class OfficeReadRequest(BaseModel):
    """Common shape for all three read endpoints."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(description="Absolute path to the workspace dir")
    file_path: str = Field(description="Absolute path to the .pptx/.docx/.xlsx file to read")
    # Optional size limit for early rejection. Default 50MB per plan §6 R1.
    max_size_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1024, description="Reject files larger than this"
    )


# ──────────────────────────────────────────────────────────────────────
# Generate requests
# ──────────────────────────────────────────────────────────────────────


class PptSlideSpec(BaseModel):
    """One slide to generate in a PPT."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    bullets: List[str] = Field(default_factory=list, max_length=20)
    notes: Optional[str] = Field(default=None, max_length=2000)


class OfficePptGenerateRequest(BaseModel):
    """POST /api/v1/office/ppt/generate."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str = Field(
        min_length=1,
        max_length=200,
        description="Output filename (without .pptx extension is OK; we'll add it)",
    )
    slides: List[PptSlideSpec] = Field(min_length=1, max_length=100)
    template: Optional[str] = Field(default=None, description="'default' | 'minimal'")


class WordParagraphSpec(BaseModel):
    """One paragraph in a generated Word document."""

    model_config = ConfigDict(extra="forbid")

    heading: Optional[str] = Field(default=None, description="'h1' | 'h2' | 'h3' or None")
    text: str = Field(min_length=1, max_length=10000)


class WordTableSpec(BaseModel):
    """One table in a generated Word document."""

    model_config = ConfigDict(extra="forbid")

    headers: List[str] = Field(min_length=1, max_length=50)
    rows: List[List[str]] = Field(default_factory=list, max_length=1000)


class OfficeWordGenerateRequest(BaseModel):
    """POST /api/v1/office/word/generate."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    paragraphs: List[WordParagraphSpec] = Field(default_factory=list, max_length=5000)
    tables: List[WordTableSpec] = Field(default_factory=list, max_length=100)


class ExcelSheetSpec(BaseModel):
    """One sheet in a generated Excel workbook."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=31, description="Excel sheet name max length")
    headers: List[str] = Field(default_factory=list, max_length=100)
    rows: List[List[str]] = Field(default_factory=list, max_length=10000)


class OfficeExcelGenerateRequest(BaseModel):
    """POST /api/v1/office/excel/generate."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str = Field(min_length=1, max_length=200)
    sheets: List[ExcelSheetSpec] = Field(min_length=1, max_length=50)


# ──────────────────────────────────────────────────────────────────────
# List / delete endpoints
# ──────────────────────────────────────────────────────────────────────


class OfficeDocumentListResponse(BaseModel):
    """GET /api/v1/office/documents."""

    model_config = ConfigDict(extra="forbid")

    documents: List[OfficeDocumentSummary]
    total: int = Field(ge=0)


class OfficeDeleteResponse(BaseModel):
    """DELETE /api/v1/office/documents/{id}."""

    model_config = ConfigDict(extra="forbid")

    id: str
    deleted: bool
