"""Chart embedding for design artifacts (M5a).

Bridges matplotlib output and the HTML design pipeline: renders a chart
to PNG bytes, encodes it as a ``data:image/png;base64,…`` URL, and injects
it into an artifact at a placeholder (``{{CHART}}`` by default) or before
``</body>``.

Rendering itself is delegated to :func:`backend.office.charts.render_chart_png`
so charts share one implementation — CJK font fallbacks, validation and
matplotlib lifecycle — between Office generation and Design Studio.
"""
from __future__ import annotations

import base64
import io
import logging
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

DEFAULT_SLOT = "{{CHART}}"

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


class EmbeddedChart(BaseModel):
    """Result of embedding a chart into HTML."""

    model_config = ConfigDict(extra="forbid")

    html: str
    data_url: str
    injected_at_slot: bool


def _mime_for(payload: bytes) -> str:
    if payload.startswith(_PNG_MAGIC):
        return "image/png"
    if payload.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    return "application/octet-stream"


def bytes_to_data_url(payload: bytes) -> str:
    """Encode raw image bytes as a data URL."""
    if not payload:
        raise ValueError("empty image payload")
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{_mime_for(payload)};base64,{encoded}"


class ChartEmbedder:
    """Render matplotlib figures/specs and inject them into HTML."""

    def fig_to_data_url(
        self, fig: Any, *, fmt: str = "png", dpi: int = 150,
    ) -> str:
        """Serialize an in-memory matplotlib figure to a data URL.

        ``fig`` only needs a ``savefig(buf, format=..., dpi=...)`` method,
        which keeps this testable without importing matplotlib.
        """
        buffer = io.BytesIO()
        fig.savefig(buffer, format=fmt, dpi=dpi, bbox_inches="tight")
        return bytes_to_data_url(buffer.getvalue())

    def spec_to_data_url(self, spec: Any, output_dir: Any = None) -> str:
        """Render a :class:`~backend.office.models.ChartSpec` to a data URL.

        Raises:
            OfficeGenerateError: matplotlib missing or the spec is invalid.
        """
        from backend.office.charts import render_chart_png

        if output_dir is None:
            with tempfile.TemporaryDirectory(prefix="sage-chart-") as tmp:
                return bytes_to_data_url(
                    Path(render_chart_png(spec, Path(tmp))).read_bytes()
                )
        out_path = render_chart_png(spec, Path(output_dir))
        return bytes_to_data_url(Path(out_path).read_bytes())

    def embed(
        self, html: str, data_url: str, *, slot: str = DEFAULT_SLOT,
    ) -> EmbeddedChart:
        """Return ``html`` with the chart injected.

        Replaces ``slot`` when present; otherwise appends a figure just
        before ``</body>`` (or at the end when the document has no body
        tag).
        """
        image = (
            '<figure class="chart" data-source="sage-chart">'
            f'<img src="{data_url}" alt="" loading="lazy" />'
            "</figure>"
        )
        if slot and slot in html:
            return EmbeddedChart(
                html=html.replace(slot, image),
                data_url=data_url,
                injected_at_slot=True,
            )
        marker = html.lower().rfind("</body>")
        if marker == -1:
            return EmbeddedChart(
                html=html + image, data_url=data_url, injected_at_slot=False,
            )
        return EmbeddedChart(
            html=html[:marker] + image + html[marker:],
            data_url=data_url,
            injected_at_slot=False,
        )


__all__ = ["ChartEmbedder", "EmbeddedChart", "bytes_to_data_url", "DEFAULT_SLOT"]
