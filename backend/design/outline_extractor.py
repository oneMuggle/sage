"""Word → deck outline extraction (M5a).

Turns a Word document into a slide-friendly markdown outline that can be
used directly as a design brief. Reuses the Office read pipeline rather
than parsing DOCX a second time, so the two subsystems share one notion
of headings, body text and tables.

Limits are deliberate: an outline is a prompt, not a transcript. Bullets
are trimmed to ``_MAX_BULLET_CHARS`` and capped per slide, and the whole
document is capped at ``_MAX_SLIDES`` so a 200-page report still yields a
usable deck skeleton.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

_MAX_SLIDES = 40
_MAX_BULLETS_PER_SLIDE = 6
_MAX_BULLET_CHARS = 140
_MAX_TITLE_CHARS = 80

_WHITESPACE_RE = re.compile(r"\s+")


class OutlineSlide(BaseModel):
    """One slide of the extracted outline."""

    model_config = ConfigDict(extra="forbid")

    title: str
    bullets: List[str]


class OutlineResult(BaseModel):
    """Result of :meth:`OutlineExtractor.extract`."""

    model_config = ConfigDict(extra="forbid")

    title: str
    source_path: str
    slide_count: int
    outline_md: str


def _clean(text: str, limit: int) -> str:
    """Collapse whitespace and truncate with an ellipsis."""
    collapsed = _WHITESPACE_RE.sub(" ", text or "").strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


class OutlineExtractor:
    """Extract a deck outline from a Word document."""

    def extract(self, docx_path: Path) -> OutlineResult:
        """Read ``docx_path`` and return its slide outline.

        Raises:
            OfficeFileNotFoundError: file doesn't exist.
            OfficeParseError: file exists but isn't a valid DOCX.
        """
        from backend.office.word import read_docx

        path = Path(docx_path)
        result = read_docx(path)
        paragraphs: List[Tuple[int, str]] = [
            (p.level, p.text) for p in result.paragraphs
        ]
        table_dims: List[Tuple[int, int]] = [
            (len(t.rows), max((len(r) for r in t.rows), default=0))
            for t in result.tables
        ]
        return self.from_paragraphs(
            paragraphs,
            source_name=path.stem,
            source_path=str(path),
            tables=table_dims,
        )

    def from_paragraphs(
        self,
        paragraphs: Iterable[Tuple[int, str]],
        *,
        source_name: str = "untitled",
        source_path: str = "",
        tables: Optional[Sequence[Tuple[int, int]]] = None,
    ) -> OutlineResult:
        """Build an outline from ``(level, text)`` pairs.

        ``level`` follows the Office convention: ``0`` is body text and
        ``>= 1`` is a heading of that depth.
        """
        slides = self._build_slides(paragraphs, source_name)
        if not slides:
            slides = [
                OutlineSlide(
                    title=_clean(source_name, _MAX_TITLE_CHARS) or "Slides",
                    bullets=[],
                )
            ]
        else:
            slides = slides[:_MAX_SLIDES]
            if tables:
                table_bullets = [
                    f"表格：{rows} 行 × {cols} 列"
                    for rows, cols in tables
                    if rows > 0 and cols > 0
                ]
                slides[-1].bullets.extend(
                    table_bullets[:_MAX_BULLETS_PER_SLIDE]
                )

        return OutlineResult(
            title=slides[0].title,
            source_path=source_path,
            slide_count=len(slides),
            outline_md=self._render_markdown(slides),
        )

    # -- internals ------------------------------------------------------

    def _build_slides(
        self, paragraphs: Iterable[Tuple[int, str]], source_name: str,
    ) -> List[OutlineSlide]:
        slides: List[OutlineSlide] = []
        current: Optional[OutlineSlide] = None

        for level, raw in paragraphs:
            text = _clean(raw, _MAX_BULLET_CHARS)
            if not text:
                continue
            if level >= 1:
                if len(slides) >= _MAX_SLIDES:
                    break
                current = OutlineSlide(
                    title=_clean(text, _MAX_TITLE_CHARS), bullets=[]
                )
                slides.append(current)
                continue
            if current is None:
                current = OutlineSlide(
                    title=_clean(source_name, _MAX_TITLE_CHARS) or "概述",
                    bullets=[],
                )
                slides.append(current)
            if len(current.bullets) >= _MAX_BULLETS_PER_SLIDE:
                continue
            if current.bullets and current.bullets[-1] == text:
                continue
            current.bullets.append(text)

        return slides

    def _render_markdown(self, slides: Sequence[OutlineSlide]) -> str:
        lines: List[str] = [f"# {slides[0].title}", ""]
        for index, slide in enumerate(slides, start=1):
            lines.append(f"## {index}. {slide.title}")
            if not slide.bullets:
                lines.append("- （无正文内容，按标题展开）")
            else:
                lines.extend(f"- {bullet}" for bullet in slide.bullets)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


__all__ = ["OutlineExtractor", "OutlineResult", "OutlineSlide"]
