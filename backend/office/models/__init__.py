"""Office document Pydantic models — package facade.

Re-exports all public symbols from domain-clustered sub-modules for backward
compatibility. External consumers should continue to import from
``backend.office.models`` without changes.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Excel models ───────────────────────────────────────────────────────
from ._excel import (
    ChartSeriesSpec,
    ChartSpec,
    ExcelCellRange,
    ExcelChartSpec,
    ExcelConditionalFormatSpec,
    ExcelDataValidationSpec,
    ExcelMetadataSpec,
    ExcelPrintMarginsSpec,
    ExcelPrintSetupSpec,
    ExcelSheetContent,
    ExcelSheetSpec,
    OfficeExcelGenerateRequest,
    OfficeExcelReadResult,
)

# ── PDF models ─────────────────────────────────────────────────────────
from ._pdf import (
    PdfDataRequest,
    PdfDataResult,
    PdfFormField,
    PdfFormFillRequest,
    PdfFormFillResult,
    PdfFormReadRequest,
    PdfFormReadResult,
    PdfGenerateRequest,
    PdfGenerateResult,
    PdfPageContent,
    PdfPageSpec,
    PdfReadRequest,
    PdfReadResult,
)

# ── PPT generation models ──────────────────────────────────────────────
from ._ppt import (
    OfficePptGenerateRequest,
    PptLayoutName,
    PptMetadataSpec,
    PptSlideSpec,
)

# ── Shared types, helpers, and core models ─────────────────────────────
from ._shared import (
    ImageSourceSpec,
    OfficeDeleteResponse,
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentActionResponse,
    OfficeDocumentListResponse,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    OfficePptReadResult,
    OfficeReadRequest,
    OfficeSnapshotInfo,
    OfficeSnapshotListResponse,
    PptSlideContent,
    WordMetadataSpec,
    _constrained_list,
    field_validator,
)

# ── Template models ────────────────────────────────────────────────────
from ._template import (
    OfficeTemplateInstantiateRequest,
    PlaceholderLocation,
    TemplateLibraryEntry,
    TemplateLibraryPlaceholder,
    TemplateLibraryResponse,
    TemplatePlaceholder,
    TemplatePlaceholderType,
    WordTemplateAnalysis,
    WordTemplateAnalyzeRequest,
    WordTemplateFillRequest,
    WordTemplateFillResult,
)

# ── Word generation models ─────────────────────────────────────────────
from ._word_gen import (
    BibliographySpec,
    BibTeXParseRequest,
    BibTeXParseResponse,
    OfficeWordGenerateRequest,
    ReferenceSpec,
    ReferenceType,
    WordBodyStyleSpec,
    WordCellMergeSpec,
    WordFormatSpec,
    WordHeaderFooterSpec,
    WordHeadingStyleSpec,
    WordImageSpec,
    WordIndexSpec,
    WordLintIssue,
    WordLintRequest,
    WordLintResult,
    WordPageMarginsSpec,
    WordPageSetupSpec,
    WordParagraphSpec,
    WordRepairRequest,
    WordRepairResult,
    WordSectionBreakSpec,
    WordTableSpec,
    WordTocSpec,
)

# ── Word read models ───────────────────────────────────────────────────
from ._word_read import (
    OfficeWordReadResult,
    WordCommentContent,
    WordCommentsResult,
    WordHeaderFooterContent,
    WordImagePreview,
    WordParagraphContent,
    WordTableContent,
)

__all__ = [
    # Shared
    "OfficeDocType",
    "OfficeDocStatus",
    "OfficeDocumentMetadata",
    "OfficeDocumentSummary",
    "OfficeReadRequest",
    "OfficeDocumentListResponse",
    "OfficeDeleteResponse",
    "OfficeSnapshotInfo",
    "OfficeSnapshotListResponse",
    "OfficeDocumentActionResponse",
    "WordMetadataSpec",
    "ImageSourceSpec",
    "PptSlideContent",
    "OfficePptReadResult",
    "_constrained_list",
    "field_validator",
    # Word read
    "WordParagraphContent",
    "WordTableContent",
    "WordCommentContent",
    "WordCommentsResult",
    "WordHeaderFooterContent",
    "WordImagePreview",
    "OfficeWordReadResult",
    # Word gen
    "WordParagraphSpec",
    "ReferenceType",
    "ReferenceSpec",
    "BibliographySpec",
    "WordTocSpec",
    "BibTeXParseRequest",
    "BibTeXParseResponse",
    "WordCellMergeSpec",
    "WordTableSpec",
    "WordPageMarginsSpec",
    "WordPageSetupSpec",
    "WordBodyStyleSpec",
    "WordHeadingStyleSpec",
    "WordHeaderFooterSpec",
    "WordSectionBreakSpec",
    "WordFormatSpec",
    "WordImageSpec",
    "WordIndexSpec",
    "OfficeWordGenerateRequest",
    "WordLintIssue",
    "WordLintResult",
    "WordLintRequest",
    "WordRepairResult",
    "WordRepairRequest",
    # Excel
    "ExcelSheetContent",
    "OfficeExcelReadResult",
    "ExcelSheetSpec",
    "ExcelDataValidationSpec",
    "ExcelConditionalFormatSpec",
    "ExcelPrintSetupSpec",
    "ExcelPrintMarginsSpec",
    "ExcelCellRange",
    "ExcelChartSpec",
    "ExcelMetadataSpec",
    "OfficeExcelGenerateRequest",
    "ChartSeriesSpec",
    "ChartSpec",
    # PPT gen
    "PptLayoutName",
    "PptSlideSpec",
    "PptMetadataSpec",
    "OfficePptGenerateRequest",
    # PDF
    "PdfPageContent",
    "PdfReadResult",
    "PdfReadRequest",
    "PdfDataRequest",
    "PdfDataResult",
    "PdfFormField",
    "PdfFormReadResult",
    "PdfFormReadRequest",
    "PdfPageSpec",
    "PdfGenerateRequest",
    "PdfGenerateResult",
    "PdfFormFillRequest",
    "PdfFormFillResult",
    # Template
    "TemplatePlaceholderType",
    "PlaceholderLocation",
    "TemplatePlaceholder",
    "WordTemplateAnalysis",
    "WordTemplateAnalyzeRequest",
    "WordTemplateFillRequest",
    "WordTemplateFillResult",
    "TemplateLibraryPlaceholder",
    "TemplateLibraryEntry",
    "TemplateLibraryResponse",
    "OfficeTemplateInstantiateRequest",
]
