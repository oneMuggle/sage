"""HTML deck to PPTX structured mapper (M3).

Parses HTML deck's <section class="slide"> structure and maps to python-pptx,
preserving titles, content, images, and basic styling.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from pptx.presentation import Presentation

logger = logging.getLogger(__name__)


# Try to import python-pptx; set flag for graceful degradation
try:
    from pptx import Presentation as PptxPresentation
    from pptx.util import Inches as PptxInches, Pt as PptxPt

    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False
    PptxPresentation = None  # type: ignore
    PptxInches = None  # type: ignore
    PptxPt = None  # type: ignore


# Pattern to match slide sections
_SLIDE_SECTION_PATTERN = re.compile(
    r'<section[^>]*class="[^"]*slide[^"]*"[^>]*>(.*?)</section>',
    re.DOTALL | re.IGNORECASE,
)

# Pattern to extract headings
_HEADING_PATTERN = re.compile(
    r"<(h[1-2])[^>]*>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE,
)

# Pattern to extract paragraphs and lists (captures tag name and content)
_CONTENT_PATTERN = re.compile(
    r"<(p|ul|ol)[^>]*>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE,
)

# Pattern to extract list items
_LIST_ITEM_PATTERN = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL | re.IGNORECASE)

# Pattern to extract images
_IMAGE_PATTERN = re.compile(r'<img[^>]*src="([^"]*)"[^>]*>', re.IGNORECASE)

# Pattern to strip HTML tags
_STRIP_TAGS_PATTERN = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = _STRIP_TAGS_PATTERN.sub("", text)
    # Decode common HTML entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    return text.strip()


class SlideContent:
    """Extracted content from a single slide section."""

    def __init__(self) -> None:
        self.title: Optional[str] = None
        self.subtitle: Optional[str] = None
        self.content_lines: List[str] = []
        self.image_paths: List[str] = []

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "content_lines": self.content_lines,
            "image_paths": self.image_paths,
        }


class HtmlToPptxMapper:
    """Map HTML deck to PPTX preserving structure and style."""

    def __init__(self) -> None:
        if not PPTX_AVAILABLE:
            raise RuntimeError(
                "python-pptx is not installed. "
                "Install with: pip install python-pptx"
            )

    def parse_html(self, html: str) -> List[SlideContent]:
        """Parse HTML and extract slide content."""
        slides: List[SlideContent] = []

        for match in _SLIDE_SECTION_PATTERN.finditer(html):
            section_html = match.group(1)
            slide = self._parse_slide(section_html)
            slides.append(slide)

        return slides

    def _parse_slide(self, section_html: str) -> SlideContent:
        """Parse a single slide section."""
        slide = SlideContent()

        # Extract headings (h1 = title, h2 = subtitle)
        headings = _HEADING_PATTERN.findall(section_html)
        if len(headings) >= 1:
            slide.title = _strip_html(headings[0][1])
        if len(headings) >= 2:
            slide.subtitle = _strip_html(headings[1][1])

        # Extract content (paragraphs and lists)
        for content_match in _CONTENT_PATTERN.finditer(section_html):
            tag = content_match.group(1).lower()  # Tag name (p|ul|ol)
            content_html = content_match.group(2)  # Inner content

            if tag in ("ul", "ol"):
                # Extract list items
                for item_match in _LIST_ITEM_PATTERN.finditer(content_html):
                    line = _strip_html(item_match.group(1))
                    if line:
                        slide.content_lines.append(f"• {line}")
            else:
                # Paragraph
                line = _strip_html(content_html)
                if line:
                    slide.content_lines.append(line)

        # Extract images
        for img_match in _IMAGE_PATTERN.finditer(section_html):
            src = img_match.group(1)
            slide.image_paths.append(src)

        return slide

    def map(self, html: str, output_path: Path) -> None:
        """Parse HTML, create PPTX with matching slides."""
        slides = self.parse_html(html)

        if not slides:
            logger.warning("No slides found in HTML; creating empty PPTX")
            # Still create an empty presentation
            prs = PptxPresentation()
            prs.save(str(output_path))
            return

        prs = PptxPresentation()

        # Use the default slide layout (title + content)
        # Layout 0 is usually "Title Slide", 1 is "Title and Content"
        blank_layout = prs.slide_layouts[6]  # Blank layout

        for i, slide_content in enumerate(slides):
            logger.debug("Creating slide %d: %s", i + 1, slide_content.title)
            self._create_slide(prs, slide_content, blank_layout)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(output_path))
        logger.info("Saved PPTX with %d slides to %s", len(slides), output_path)

    def _create_slide(
        self,
        prs: Presentation,
        slide_content: SlideContent,
        layout,
    ) -> None:
        """Create a single PPTX slide from extracted content."""
        slide = prs.slides.add_slide(layout)

        # Add title
        if slide_content.title:
            left = PptxInches(0.5)
            top = PptxInches(0.5)
            width = PptxInches(9)
            height = PptxInches(1)
            title_box = slide.shapes.add_textbox(left, top, width, height)
            title_frame = title_box.text_frame
            title_frame.text = slide_content.title
            title_para = title_frame.paragraphs[0]
            title_para.font.size = PptxPt(36)
            title_para.font.bold = True

        # Add subtitle if present
        if slide_content.subtitle:
            left = PptxInches(0.5)
            top = PptxInches(1.6)
            width = PptxInches(9)
            height = PptxInches(0.5)
            subtitle_box = slide.shapes.add_textbox(left, top, width, height)
            subtitle_frame = subtitle_box.text_frame
            subtitle_frame.text = slide_content.subtitle
            subtitle_para = subtitle_frame.paragraphs[0]
            subtitle_para.font.size = PptxPt(24)
            subtitle_para.font.italic = True

        # Add content lines
        if slide_content.content_lines:
            left = PptxInches(0.5)
            top = PptxInches(2.5) if slide_content.title else PptxInches(0.5)
            width = PptxInches(9)
            height = PptxInches(4.5) if slide_content.title else PptxInches(6.5)
            content_box = slide.shapes.add_textbox(left, top, width, height)
            content_frame = content_box.text_frame
            content_frame.word_wrap = True

            for i, line in enumerate(slide_content.content_lines):
                para = content_frame.paragraphs[0] if i == 0 else content_frame.add_paragraph()
                para.text = line
                para.font.size = PptxPt(18)
                para.space_after = PptxPt(12)

        # Note: Image embedding requires file paths, not data URLs
        # For now, we skip images that are data URLs or external URLs
        # A future enhancement could download/cache external images


__all__ = ["HtmlToPptxMapper", "PPTX_AVAILABLE"]
