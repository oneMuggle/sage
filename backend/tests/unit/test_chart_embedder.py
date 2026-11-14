"""Tests for backend.design.chart_embedder (M5a)."""
from __future__ import annotations

import pytest

from backend.design.chart_embedder import (
    DEFAULT_SLOT,
    ChartEmbedder,
    bytes_to_data_url,
)

<<<<<<< HEAD
try:
    import matplotlib  # noqa: F401
    _has_matplotlib = True
except ImportError:
    _has_matplotlib = False

=======
>>>>>>> origin/main
PNG_STUB = b"\x89PNG\r\n\x1a\n" + b"payload"


class _FakeFigure:
    """Duck-typed matplotlib figure: only savefig is used."""

    def savefig(self, buffer, *, format="png", dpi=150, bbox_inches=None):
        assert format == "png"
        assert dpi == 150
        assert bbox_inches == "tight"
        buffer.write(PNG_STUB)


class TestBytesToDataUrl:
    def test_png_magic_sets_mime(self):
        url = bytes_to_data_url(PNG_STUB)
        assert url.startswith("data:image/png;base64,")

    def test_empty_payload_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            bytes_to_data_url(b"")


class TestFigToDataUrl:
    def test_serializes_figure(self):
        url = ChartEmbedder().fig_to_data_url(_FakeFigure())
        assert url.startswith("data:image/png;base64,")


class TestEmbed:
    def test_replaces_placeholder(self):
        html = "<body><div>" + DEFAULT_SLOT + "</div></body>"
        result = ChartEmbedder().embed(html, "data:image/png;base64,AAA")
        assert result.injected_at_slot is True
        assert DEFAULT_SLOT not in result.html
        assert '<img src="data:image/png;base64,AAA"' in result.html

    def test_injects_before_body_close(self):
        html = "<html><body><p>x</p></body></html>"
        result = ChartEmbedder().embed(html, "data:image/png;base64,AAA")
        assert result.injected_at_slot is False
        assert result.html.endswith("</figure></body></html>")

    def test_appends_without_body_tag(self):
        html = "<section>slide</section>"
        result = ChartEmbedder().embed(html, "data:image/png;base64,AAA")
        assert result.html.startswith(html)
        assert result.html.endswith("</figure>")

    def test_custom_slot(self):
        html = '<div data-chart="sales"></div>'
        result = ChartEmbedder().embed(
            html, "data:image/png;base64,AAA", slot='data-chart="sales"',
        )
        assert result.injected_at_slot is True
        assert '<figure class="chart"' in result.html


class TestSpecToDataUrl:
<<<<<<< HEAD
    @pytest.mark.skipif(
        not _has_matplotlib, reason="matplotlib not installed"
    )
=======
>>>>>>> origin/main
    def test_renders_chart_spec(self):
        from backend.office.models import ChartSeriesSpec, ChartSpec

        spec = ChartSpec(
            type="bar",
            title="季度收入",
            labels=["Q1", "Q2"],
            series=[ChartSeriesSpec(name="收入", y=[12.0, 18.0])],
        )
        url = ChartEmbedder().spec_to_data_url(spec)
        assert url.startswith("data:image/png;base64,")
        assert len(url) > 200
