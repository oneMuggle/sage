"""Office document Pydantic models.

Defines request/response models for the office API. All models are Pydantic v2
to match FastAPI 0.109 + pydantic 2.5 already pinned in requirements.txt.

Frontend IPC contracts (in src/shared/api/types.ts) MUST stay in sync with
the response shapes defined here.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, conlist

logger = logging.getLogger(__name__)


def _constrained_list(item_type, *, min_length=None, max_length=None):
    """Build a list constraint compatible with Pydantic v1 and v2."""
    kwargs = {}
    if min_length is not None:
        kwargs["min_length"] = min_length
    if max_length is not None:
        kwargs["max_length"] = max_length
    try:
        return conlist(item_type, **kwargs)
    except TypeError:
        if "min_length" in kwargs:
            kwargs["min_items"] = kwargs.pop("min_length")
        if "max_length" in kwargs:
            kwargs["max_items"] = kwargs.pop("max_length")
        return conlist(item_type, **kwargs)


class OfficeDocType(str, Enum):
    """Document type discriminator."""

    PPT = "ppt"
    WORD = "word"
    EXCEL = "excel"
    PDF = "pdf"  # Phase 2: PDF support


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
    # M0 Task 3: nullable lineage + soft-delete columns. Both default to
    # ``None`` so Phase 1.2 callers (which only know status + paths) keep
    # working without supplying the extra fields.
    derived_from: Optional[str] = Field(
        default=None,
        description=(
            "Source document id for edited/copied documents. NULL when this row "
            "is a fresh read or generation with no upstream parent."
        ),
    )
    archived_at: Optional[int] = Field(
        default=None,
        description=(
            "Unix timestamp (ms) when the document was soft-deleted. When set, "
            "list_documents(include_archived=False) hides the row."
        ),
    )


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
    # M0 Task 3: optional original (uploaded) filename. When the caller has
    # already imported an external file into the managed directory this is
    # the user-visible name; ``None`` keeps the Phase 1.2 contract for
    # back-compat with tests and existing IPC callers that don't track it.
    original_filename: Optional[str] = Field(
        default=None,
        description=(
            "User's original filename (before managed import). When None the "
            "summary's original_filename column stays NULL."
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# Generate requests
# ──────────────────────────────────────────────────────────────────────


class PptSlideSpec(BaseModel):
    """One slide to generate in a PPT."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    bullets: _constrained_list(str, max_length=20) = Field(default_factory=list)
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
    slides: _constrained_list(PptSlideSpec, min_length=1, max_length=100)
    template: Optional[str] = Field(default=None, description="'default' | 'minimal'")


class WordParagraphSpec(BaseModel):
    """One paragraph in a generated Word document."""

    model_config = ConfigDict(extra="forbid")

    heading: Optional[str] = Field(default=None, description="'h1' | 'h2' | 'h3' or None")
    text: str = Field(min_length=1, max_length=10000)


class WordTableSpec(BaseModel):
    """One table in a generated Word document."""

    model_config = ConfigDict(extra="forbid")

    headers: _constrained_list(str, min_length=1, max_length=50)
    rows: _constrained_list(_constrained_list(str), max_length=1000) = Field(default_factory=list)


class OfficeWordGenerateRequest(BaseModel):
    """POST /api/v1/office/word/generate."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    paragraphs: _constrained_list(WordParagraphSpec, max_length=5000) = Field(default_factory=list)
    tables: _constrained_list(WordTableSpec, max_length=100) = Field(default_factory=list)


class ExcelSheetSpec(BaseModel):
    """One sheet in a generated Excel workbook."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=31, description="Excel sheet name max length")
    headers: _constrained_list(str, max_length=100) = Field(default_factory=list)
    rows: _constrained_list(_constrained_list(str), max_length=10000) = Field(default_factory=list)


class OfficeExcelGenerateRequest(BaseModel):
    """POST /api/v1/office/excel/generate."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str = Field(min_length=1, max_length=200)
    sheets: _constrained_list(ExcelSheetSpec, min_length=1, max_length=50)


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


# ──────────────────────────────────────────────────────────────────────
# Word Template models (Phase 2)
# ──────────────────────────────────────────────────────────────────────


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
# PDF models (Phase 2)
# ──────────────────────────────────────────────────────────────────────


class PdfPageContent(BaseModel):
    """Content of one PDF page."""

    model_config = ConfigDict(extra="forbid")

    page_number: int
    text: str
    tables: List[List[List[str]]] = Field(default_factory=list)
    images: List[Dict[str, Any]] = Field(default_factory=list)


class PdfReadResult(BaseModel):
    """Result of reading a PDF file."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    pages: List[PdfPageContent]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PdfReadRequest(BaseModel):
    """Request to read a PDF file."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class PdfPageSpec(BaseModel):
    """One page in a generated PDF."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    paragraphs: List[str] = Field(default_factory=list)
    tables: List[List[List[str]]] = Field(default_factory=list)


class PdfGenerateRequest(BaseModel):
    """Request to generate a PDF."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str
    pages: List[PdfPageSpec]
    page_size: str = "A4"
    orientation: str = "portrait"


class PdfGenerateResult(BaseModel):
    """Result of generating a PDF."""

    model_config = ConfigDict(extra="forbid")

    output_path: str
    filename: str
    file_size_bytes: int
    page_count: int


class PdfFormField(BaseModel):
    """One PDF form field."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    value: Optional[Any] = None
    options: Optional[List[str]] = None
    required: bool = False
    read_only: bool = False


class PdfFormReadResult(BaseModel):
    """Result of reading PDF form fields."""

    model_config = ConfigDict(extra="forbid")

    file_path: str
    fields: List[PdfFormField]
    has_xfa: bool = False


class PdfFormReadRequest(BaseModel):
    """Request to read PDF form fields."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class PdfFormFillRequest(BaseModel):
    """Request to fill a PDF form."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str
    output_filename: str
    data: Dict[str, Any]
    flatten: bool = False


class PdfFormFillResult(BaseModel):
    """Result of filling a PDF form."""

    model_config = ConfigDict(extra="forbid")

    output_path: str
    filename: str
    file_size_bytes: int
    filled_count: int
