from __future__ import annotations

import asyncio

import pymupdf

from backend.adapters.out.document_parse.local_engine import LocalEngine
from backend.adapters.out.document_parse.quality import (
    QualitySignals,
    compute_pdf_signals,
    score_quality,
)
from backend.domain.document_parse import ParseRequest


def _pdf_bytes(text: str, pages: int = 1) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_score_quality_full_penalties() -> None:
    signals = QualitySignals(1, 10.0, 0.9, True, True)
    assert score_quality(signals) == 0.0


def test_score_quality_clean_text() -> None:
    signals = QualitySignals(3, 2000.0, 0.0, False, False)
    assert score_quality(signals) == 1.0


def test_compute_pdf_signals_detects_blank_pages() -> None:
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    doc[0].insert_text((72, 72), "hello world " * 30)
    data = doc.tobytes()
    doc.close()
    signals = compute_pdf_signals(data)
    assert signals is not None
    assert signals.page_count == 2
    assert signals.blank_page_ratio == 0.5


def test_local_engine_returns_page_marked_text() -> None:
    engine = LocalEngine()
    result = asyncio.run(
        engine.parse(ParseRequest(filename="a.pdf", content_bytes=_pdf_bytes("hello")))
    )
    assert result.engine_used == "local"
    assert "--- page 1 ---" in result.text
    assert result.quality_score > 0.5
    assert result.duration_ms >= 0
