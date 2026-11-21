"""Unified document extraction backends (M6b)."""

from .base import (
    DocumentExtractor,
    ExtractedBlock,
    StructuredDocument,
    extractor_available,
    get_extractor,
    list_extractors,
    register_extractor,
)
from .light import LightExtractor
from .optional import DoclingExtractor, MarkItDownExtractor
from .service import ExtractRequest, ExtractResult, extract_document

register_extractor("light", LightExtractor)
register_extractor("markitdown", MarkItDownExtractor)
register_extractor("docling", DoclingExtractor)

__all__ = [
    "DocumentExtractor",
    "DoclingExtractor",
    "ExtractRequest",
    "ExtractResult",
    "ExtractedBlock",
    "LightExtractor",
    "MarkItDownExtractor",
    "StructuredDocument",
    "extract_document",
    "extractor_available",
    "get_extractor",
    "list_extractors",
    "register_extractor",
]
