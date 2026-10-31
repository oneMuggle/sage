"""Dataclasses for the LaTeX parser/renderer (dependency-free, py38-safe)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LatexAnchor:
    """Source position for a LaTeX block/warning."""

    file: str
    line: int = 0
    column: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"file": self.file, "line": self.line, "column": self.column}


@dataclass(frozen=True)
class LatexWarning:
    """A non-fatal parser problem (unknown macro, missing include, ...)."""

    code: str
    message: str
    anchor: Optional[LatexAnchor] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.anchor is not None:
            payload["anchor"] = self.anchor.to_dict()
        if self.detail:
            payload["detail"] = dict(self.detail)
        return payload


@dataclass
class LatexMetadata:
    """Document metadata extracted from the preamble/body."""

    document_class: Optional[str] = None
    document_options: List[str] = field(default_factory=list)
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    affiliations: List[str] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    date: Optional[str] = None
    abstract: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    extra: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_class": self.document_class,
            "document_options": list(self.document_options),
            "title": self.title,
            "authors": list(self.authors),
            "affiliations": list(self.affiliations),
            "emails": list(self.emails),
            "date": self.date,
            "abstract": self.abstract,
            "keywords": list(self.keywords),
            "extra": dict(self.extra),
        }


@dataclass
class LatexListItem:
    """One list item, stored as Markdown-ish text."""

    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text}


@dataclass
class LatexBlock:
    """A renderable block. ``text`` fields carry Markdown + ``$...$`` math."""

    type: str
    level: int = 0
    text: str = ""
    ordered: bool = False
    items: List[LatexListItem] = field(default_factory=list)
    latex: str = ""
    display: bool = True
    src: Optional[str] = None
    caption: Optional[str] = None
    label: Optional[str] = None
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    entries: List[Dict[str, str]] = field(default_factory=list)
    anchor: Optional[LatexAnchor] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"type": self.type}
        if self.level:
            payload["level"] = self.level
        if self.text:
            payload["text"] = self.text
        if self.type == "list":
            payload["ordered"] = self.ordered
            payload["items"] = [item.to_dict() for item in self.items]
        if self.type == "equation":
            payload["latex"] = self.latex
            payload["display"] = self.display
            if self.label:
                payload["label"] = self.label
        if self.type in ("figure", "table"):
            if self.src:
                payload["src"] = self.src
            if self.caption:
                payload["caption"] = self.caption
            if self.label:
                payload["label"] = self.label
        if self.type == "table":
            payload["headers"] = list(self.headers)
            payload["rows"] = [list(row) for row in self.rows]
        if self.type == "bibliography":
            payload["entries"] = [dict(entry) for entry in self.entries]
        if self.type in ("code", "quote") and self.text:
            payload["text"] = self.text
        if self.anchor is not None:
            payload["anchor"] = self.anchor.to_dict()
        return payload


@dataclass
class LatexDocument:
    """Parsed project result."""

    source_path: str
    metadata: LatexMetadata
    blocks: List[LatexBlock] = field(default_factory=list)
    warnings: List[LatexWarning] = field(default_factory=list)
    includes: List[str] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "metadata": self.metadata.to_dict(),
            "blocks": [block.to_dict() for block in self.blocks],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "includes": list(self.includes),
            "citations": list(self.citations),
        }
