"""Tests for HTML to PPTX mapper (M3)."""
from __future__ import annotations

import pytest

from backend.design.pptx_mapper import (
    PPTX_AVAILABLE,
    HtmlToPptxMapper,
    SlideContent,
    _strip_html,
)


@pytest.fixture()
def mapper():
    if not PPTX_AVAILABLE:
        pytest.skip("python-pptx not installed")
    return HtmlToPptxMapper()


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


class TestStripHtml:
    """Test HTML tag stripping and entity decoding."""

    def test_strips_simple_tags(self):
        html = "<b>Bold</b> and <i>italic</i>"
        assert _strip_html(html) == "Bold and italic"

    def test_decodes_entities(self):
        html = "AT&amp;T &lt;5% &quot;quoted&quot;"
        assert _strip_html(html) == 'AT&T <5% "quoted"'

    def test_decodes_nbsp(self):
        html = "word&nbsp;word"
        assert _strip_html(html) == "word word"


class TestSlideContent:
    """Test SlideContent model."""

    def test_to_dict(self):
        slide = SlideContent()
        slide.title = "Title"
        slide.subtitle = "Subtitle"
        slide.content_lines = ["Line 1", "Line 2"]
        slide.image_paths = ["img.png"]
        d = slide.to_dict()
        assert d["title"] == "Title"
        assert d["subtitle"] == "Subtitle"
        assert d["content_lines"] == ["Line 1", "Line 2"]
        assert d["image_paths"] == ["img.png"]


class TestParseHtml:
    """Test HTML deck parsing."""

    def test_extracts_single_slide(self, mapper):
        html = """
        <section class="slide">
            <h1>Title</h1>
            <p>Content line</p>
        </section>
        """
        slides = mapper.parse_html(html)
        assert len(slides) == 1
        assert slides[0].title == "Title"
        assert slides[0].content_lines == ["Content line"]

    def test_extracts_multiple_slides(self, mapper):
        html = """
        <section class="slide">
            <h1>Slide 1</h1>
        </section>
        <section class="slide">
            <h1>Slide 2</h1>
        </section>
        <section class="slide">
            <h1>Slide 3</h1>
        </section>
        """
        slides = mapper.parse_html(html)
        assert len(slides) == 3
        assert slides[0].title == "Slide 1"
        assert slides[1].title == "Slide 2"
        assert slides[2].title == "Slide 3"

    def test_extracts_title_and_subtitle(self, mapper):
        html = """
        <section class="slide">
            <h1>Main Title</h1>
            <h2>Subtitle</h2>
        </section>
        """
        slides = mapper.parse_html(html)
        assert slides[0].title == "Main Title"
        assert slides[0].subtitle == "Subtitle"

    def test_extracts_paragraphs(self, mapper):
        html = """
        <section class="slide">
            <h1>Title</h1>
            <p>First paragraph</p>
            <p>Second paragraph</p>
        </section>
        """
        slides = mapper.parse_html(html)
        assert slides[0].content_lines == ["First paragraph", "Second paragraph"]

    def test_extracts_unordered_list(self, mapper):
        html = """
        <section class="slide">
            <h1>Title</h1>
            <ul>
                <li>Item one</li>
                <li>Item two</li>
                <li>Item three</li>
            </ul>
        </section>
        """
        slides = mapper.parse_html(html)
        assert slides[0].content_lines == [
            "• Item one",
            "• Item two",
            "• Item three",
        ]

    def test_extracts_ordered_list(self, mapper):
        html = """
        <section class="slide">
            <h1>Title</h1>
            <ol>
                <li>First</li>
                <li>Second</li>
            </ol>
        </section>
        """
        slides = mapper.parse_html(html)
        assert slides[0].content_lines == ["• First", "• Second"]

    def test_extracts_images(self, mapper):
        html = """
        <section class="slide">
            <h1>Title</h1>
            <img src="chart.png" alt="Chart">
            <img src="photo.jpg">
        </section>
        """
        slides = mapper.parse_html(html)
        assert slides[0].image_paths == ["chart.png", "photo.jpg"]

    def test_handles_html_entities_in_content(self, mapper):
        html = """
        <section class="slide">
            <h1>AT&amp;T Report</h1>
            <p>Revenue &gt; $1M</p>
        </section>
        """
        slides = mapper.parse_html(html)
        assert slides[0].title == "AT&T Report"
        assert slides[0].content_lines == ["Revenue > $1M"]

    def test_empty_html_returns_empty_list(self, mapper):
        html = "<div>No slides here</div>"
        slides = mapper.parse_html(html)
        assert slides == []

    def test_complex_real_world_deck(self, mapper):
        html = """
        <section class="slide">
            <h1>Q3 2024 Performance</h1>
            <h2>Financial Results</h2>
            <p>Revenue increased 23% compared to Q2.</p>
            <ul>
                <li>North America: +15%</li>
                <li>Europe: +32%</li>
                <li>Asia-Pacific: +41%</li>
            </ul>
            <img src="revenue-chart.png">
        </section>
        <section class="slide">
            <h1>Next Quarter Outlook</h1>
            <p>Based on current pipeline and market conditions.</p>
            <ol>
                <li>Continue expansion in Europe</li>
                <li>Launch new product line</li>
                <li>Optimize supply chain</li>
            </ol>
        </section>
        """
        slides = mapper.parse_html(html)
        assert len(slides) == 2
        assert slides[0].title == "Q3 2024 Performance"
        assert slides[0].subtitle == "Financial Results"
        assert len(slides[0].content_lines) == 4  # 1 paragraph + 3 list items
        assert slides[0].image_paths == ["revenue-chart.png"]
        assert slides[1].title == "Next Quarter Outlook"
        assert len(slides[1].content_lines) == 4  # 1 paragraph + 3 list items


# ---------------------------------------------------------------------------
# PPTX generation
# ---------------------------------------------------------------------------


class TestMapToPptx:
    """Test PPTX file generation."""

    def test_creates_pptx_file(self, mapper, tmp_path):
        html = """
        <section class="slide">
            <h1>Test Slide</h1>
            <p>Content</p>
        </section>
        """
        output = tmp_path / "test.pptx"
        mapper.map(html, output)
        assert output.exists()
        assert output.stat().st_size > 0

    def test_empty_html_creates_empty_pptx(self, mapper, tmp_path):
        html = "<div>No slides</div>"
        output = tmp_path / "empty.pptx"
        mapper.map(html, output)
        assert output.exists()
        # Empty PPTX still has some size (metadata)
        assert output.stat().st_size > 0

    def test_creates_parent_directories(self, mapper, tmp_path):
        html = """
        <section class="slide">
            <h1>Title</h1>
        </section>
        """
        output = tmp_path / "nested" / "dir" / "test.pptx"
        mapper.map(html, output)
        assert output.exists()

    def test_multiple_slides(self, mapper, tmp_path):
        html = """
        <section class="slide"><h1>Slide 1</h1></section>
        <section class="slide"><h1>Slide 2</h1></section>
        <section class="slide"><h1>Slide 3</h1></section>
        """
        output = tmp_path / "multi.pptx"
        mapper.map(html, output)
        assert output.exists()
        # Verify slide count by reading back
        from pptx import Presentation

        prs = Presentation(str(output))
        assert len(prs.slides) == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_slide_without_title(self, mapper):
        html = """
        <section class="slide">
            <p>Just content, no title</p>
        </section>
        """
        slides = mapper.parse_html(html)
        assert len(slides) == 1
        assert slides[0].title is None
        assert slides[0].content_lines == ["Just content, no title"]

    def test_slide_with_only_title(self, mapper):
        html = """
        <section class="slide">
            <h1>Only a title</h1>
        </section>
        """
        slides = mapper.parse_html(html)
        assert slides[0].title == "Only a title"
        assert slides[0].content_lines == []

    def test_nested_html_tags_in_content(self, mapper):
        html = """
        <section class="slide">
            <h1><span>Title</span> with <b>bold</b></h1>
            <p>Paragraph with <i>italic</i> and <code>code</code></p>
        </section>
        """
        slides = mapper.parse_html(html)
        assert slides[0].title == "Title with bold"
        assert slides[0].content_lines == ["Paragraph with italic and code"]

    def test_empty_list_items_skipped(self, mapper):
        html = """
        <section class="slide">
            <h1>Title</h1>
            <ul>
                <li>Valid item</li>
                <li></li>
                <li>Another item</li>
            </ul>
        </section>
        """
        slides = mapper.parse_html(html)
        # Empty items should be filtered out
        assert slides[0].content_lines == ["• Valid item", "• Another item"]


__all__ = [
    "TestStripHtml",
    "TestSlideContent",
    "TestParseHtml",
    "TestMapToPptx",
    "TestEdgeCases",
]
