"""Round D P10: pdf_to_word 扫描页 OCR 回退的单元测试。

复用 office-p4a 的 pytesseract 兜底（ocr_page_if_needed）——tesseract
不在 CI，回退经 monkeypatch stub 验证接入点行为：触发条件（无文本层/
无表格/有图）、识别行入段落、ocr_pages 计数、引擎不可用时保持原契约。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pymupdf
import pytest

from backend.office import ocr
from backend.office.pdf_to_word import convert_pdf_to_word


def _tiny_png() -> bytes:
    def chunk(tag, payload):
        raw = tag + payload
        return struct.pack(">I", len(payload)) + raw + struct.pack(
            ">I", zlib.crc32(raw) & 0xFFFFFFFF
        )

    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    scan = b"".join(b"\x00" + b"\x80\x80\x80" * 4 for _ in range(4))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(scan))
        + chunk(b"IEND", b"")
    )


def _make_scan_pdf(path: Path, *, with_image: bool = True) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    if with_image:
        page.insert_image(pymupdf.Rect(0, 0, 595, 842), stream=_tiny_png())
    doc.save(str(path))
    doc.close()


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return workspace


def test_scanned_page_ocr_fallback(ws, monkeypatch):
    """图片-only 页：OCR stub 返回文本 → 段落写入 + ocr_pages=1。"""
    pdf_path = ws / "scan.pdf"
    _make_scan_pdf(pdf_path)

    monkeypatch.setattr(
        ocr, "ocr_page_if_needed", lambda page, text: "扫描件第一行\n扫描件第二行\n"
    )

    result = convert_pdf_to_word(pdf_path, ws, "scan.docx")
    assert result.ok is True
    assert result.ocr_pages == 1
    assert result.paragraph_count == 2

    from docx import Document

    texts = [p.text for p in Document(result.output_path).paragraphs if p.text.strip()]
    assert "扫描件第一行" in texts
    assert "扫描件第二行" in texts


def test_scanned_page_without_ocr_keeps_old_behavior(ws, monkeypatch):
    """OCR 关闭/不可用（返回 None）：扫描页仍转出近空文档，ocr_pages=0。"""
    pdf_path = ws / "scan.pdf"
    _make_scan_pdf(pdf_path)

    monkeypatch.setattr(ocr, "ocr_page_if_needed", lambda page, text: None)

    result = convert_pdf_to_word(pdf_path, ws, "scan.docx")
    assert result.ok is True
    assert (result.ocr_pages or 0) == 0
    assert result.paragraph_count == 0


def test_blank_page_without_images_skips_ocr(ws, monkeypatch):
    """空白页（无图）不触发 OCR —— 回退条件要求 page_images > 0。"""
    pdf_path = ws / "blank.pdf"
    _make_scan_pdf(pdf_path, with_image=False)

    calls = []

    def spy(page, text):
        calls.append(1)
        return "不应出现"

    monkeypatch.setattr(ocr, "ocr_page_if_needed", spy)
    result = convert_pdf_to_word(pdf_path, ws, "blank.docx")
    assert result.ok is True
    assert calls == []
    assert (result.ocr_pages or 0) == 0


def test_ocr_available_flag_reported(ws, monkeypatch):
    """ocr_available = 依赖可用 AND 用户已开启（SAGE_OCR=1）。"""
    pdf_path = ws / "scan.pdf"
    _make_scan_pdf(pdf_path)
    monkeypatch.setattr(ocr, "ocr_page_if_needed", lambda page, text: None)
    monkeypatch.setattr(ocr, "ocr_available", lambda: (True, ""))
    monkeypatch.setattr(ocr, "is_ocr_enabled", lambda: True)
    assert convert_pdf_to_word(pdf_path, ws, "a.docx").ocr_available is True

    monkeypatch.setattr(ocr, "is_ocr_enabled", lambda: False)
    assert convert_pdf_to_word(pdf_path, ws, "b.docx").ocr_available is False
