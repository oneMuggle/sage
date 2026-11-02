"""Pydantic response models for the Word document profile (M0)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WordTextAnchor(BaseModel):
    """Stable-ish location inside a DOCX part."""

    model_config = ConfigDict(extra="forbid")

    part: str = "word/document.xml"
    paragraph_index: Optional[int] = None
    run_index: Optional[int] = None
    char_start: int = 0
    char_end: int = 0
    text_hash: str = ""
    table_index: Optional[int] = None
    row: Optional[int] = None
    col: Optional[int] = None


class WordRunProfile(BaseModel):
    """One run with effective font/size/style formatting."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    text: str
    style: Optional[str] = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    font_ascii: Optional[str] = None
    font_east_asia: Optional[str] = None
    size_pt: Optional[float] = None
    color: Optional[str] = None
    anchor: WordTextAnchor


class WordNumberingProfile(BaseModel):
    """Numbering reference attached to a paragraph."""

    model_config = ConfigDict(extra="forbid")

    num_id: str
    level: int = Field(ge=0)
    format: Optional[str] = None
    text: Optional[str] = None


class WordParagraphProfile(BaseModel):
    """Paragraph text plus formatting and run details."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    style: str
    text: str
    level: int = Field(ge=0)
    alignment: Optional[str] = None
    indent_left_pt: Optional[float] = None
    indent_right_pt: Optional[float] = None
    first_line_indent_pt: Optional[float] = None
    space_before_pt: Optional[float] = None
    space_after_pt: Optional[float] = None
    line_spacing: Optional[float] = None
    line_spacing_rule: Optional[str] = None
    keep_with_next: bool = False
    page_break_before: bool = False
    numbering: Optional[WordNumberingProfile] = None
    runs: List[WordRunProfile] = Field(default_factory=list)
    anchor: WordTextAnchor


class WordTableCellProfile(BaseModel):
    """One raw table cell (merge metadata preserved)."""

    model_config = ConfigDict(extra="forbid")

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    v_merge: Optional[str] = None
    text: str
    anchor: WordTextAnchor


class WordTableProfile(BaseModel):
    """One body table."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    rows: int = Field(ge=0)
    cols: int = Field(ge=0)
    cells: List[WordTableCellProfile] = Field(default_factory=list)
    anchor: WordTextAnchor


class WordSectionProfile(BaseModel):
    """Page setup and header/footer text for one section."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    start_type: Optional[str] = None
    page_width_pt: Optional[float] = None
    page_height_pt: Optional[float] = None
    orientation: Optional[str] = None
    margin_top_pt: Optional[float] = None
    margin_bottom_pt: Optional[float] = None
    margin_left_pt: Optional[float] = None
    margin_right_pt: Optional[float] = None
    header_distance_pt: Optional[float] = None
    footer_distance_pt: Optional[float] = None
    header_text: str = ""
    footer_text: str = ""
    has_page_number_field: bool = False


class WordBookmarkProfile(BaseModel):
    """Bookmark name and start/end anchors."""

    model_config = ConfigDict(extra="forbid")

    name: str
    anchor: WordTextAnchor
    end_anchor: Optional[WordTextAnchor] = None


class WordFieldProfile(BaseModel):
    """A field instruction (TOC/REF/PAGE/…)."""

    model_config = ConfigDict(extra="forbid")

    instr: str
    anchor: WordTextAnchor


class WordStyleProfile(BaseModel):
    """Effective style formatting after basedOn resolution."""

    model_config = ConfigDict(extra="forbid")

    style_id: str
    name: str
    type: str
    based_on: Optional[str] = None
    font_ascii: Optional[str] = None
    font_east_asia: Optional[str] = None
    size_pt: Optional[float] = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: Optional[str] = None


class WordDocumentProfileSummary(BaseModel):
    """Counts for quick display."""

    model_config = ConfigDict(extra="forbid")

    paragraphs: int = Field(ge=0, default=0)
    tables: int = Field(ge=0, default=0)
    sections: int = Field(ge=0, default=0)
    styles: int = Field(ge=0, default=0)
    bookmarks: int = Field(ge=0, default=0)
    fields: int = Field(ge=0, default=0)


class WordDocumentProfileResult(BaseModel):
    """Read-only Word document profile (M0)."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    source_path: str
    summary: WordDocumentProfileSummary
    defaults: Dict[str, Any] = Field(default_factory=dict)
    sections: List[WordSectionProfile] = Field(default_factory=list)
    styles: List[WordStyleProfile] = Field(default_factory=list)
    paragraphs: List[WordParagraphProfile] = Field(default_factory=list)
    tables: List[WordTableProfile] = Field(default_factory=list)
    bookmarks: List[WordBookmarkProfile] = Field(default_factory=list)
    fields: List[WordFieldProfile] = Field(default_factory=list)
    warnings: List[Dict[str, str]] = Field(default_factory=list)


__all__ = [
    "WordBookmarkProfile",
    "WordDocumentProfileResult",
    "WordDocumentProfileSummary",
    "WordFieldProfile",
    "WordNumberingProfile",
    "WordParagraphProfile",
    "WordRunProfile",
    "WordSectionProfile",
    "WordStyleProfile",
    "WordTableCellProfile",
    "WordTableProfile",
    "WordTextAnchor",
]
