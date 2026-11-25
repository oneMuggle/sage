"""Unified document extraction models and registry (M6b).

The light backend wraps the existing python-docx/openpyxl/python-pptx/
PyMuPDF readers. Optional backends (markitdown/docling) are discovered at
runtime — they are never required dependencies and unavailability simply
falls back to light.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

BlockType = Literal["heading", "paragraph", "table", "page", "slide", "sheet", "figure"]


class ExtractedBlock(BaseModel):
    """One structured block with an optional source anchor."""

    model_config = ConfigDict(extra="forbid")

    type: BlockType
    text: str
    anchor: Dict[str, Any] = Field(
        default_factory=dict,
        description="例如 {page: 3} / {paragraph_index: 7} / {sheet: '数据', row: 4} / {slide: 2}",
    )


class StructuredDocument(BaseModel):
    """Normalized extraction result shared by all backends."""

    model_config = ConfigDict(extra="forbid")

    source_path: str
    format: str
    extractor: str
    markdown: str
    blocks: List[ExtractedBlock] = Field(default_factory=list)
    warnings: List[Dict[str, str]] = Field(default_factory=list)
    # M6b: 表格形状诊断（各后端可选填充）。键位见
    # ``backend.office.extractors.tables.assess_table_complexity``。
    # 空 dict 表示"没有表格"或"后端未提供诊断"，两种情况都不算复杂。
    table_diagnostics: Dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class DocumentExtractor(Protocol):
    """Backend contract: name + suffix support + extraction."""

    name: str

    def supports(self, suffix: str) -> bool:
        ...

    def extract(self, path: Path) -> StructuredDocument:
        ...


ExtractorFactory = Callable[[], DocumentExtractor]

_EXTRACTORS: Dict[str, ExtractorFactory] = {}


def register_extractor(name: str, factory: ExtractorFactory) -> None:
    """Register (or replace) a backend factory by name."""
    _EXTRACTORS[name] = factory


def list_extractors() -> List[str]:
    return list(_EXTRACTORS)


def get_extractor(name: str) -> DocumentExtractor:
    """Instantiate a backend; raises KeyError for unknown names."""
    return _EXTRACTORS[name]()


def extractor_available(name: str) -> bool:
    """Instantiate the backend to probe optional imports (never raises)."""
    factory = _EXTRACTORS.get(name)
    if factory is None:
        return False
    try:
        factory()
    except Exception:  # noqa: BLE001 — 能力探测按不可用处理
        return False
    return True
