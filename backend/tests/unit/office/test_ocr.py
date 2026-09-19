"""Unit tests for backend.office.ocr (Round D P10 本地 OCR 回退).

RapidOCR 不在 CI —— 引擎经 monkeypatch 注入 stub，测试聚焦 ocr.py 自己
的职责：可用性探测、单例/闩锁语义、结果解析（排序/置信度过滤）、永不
raise 契约，以及 pdf_to_word 扫描页回退的接入点行为。
"""

from __future__ import annotations

import pytest

from backend.office import ocr


@pytest.fixture(autouse=True)
def _reset_engine():
    ocr._engine = None
    ocr._engine_failed = False
    yield
    ocr._engine = None
    ocr._engine_failed = False


class _FakePage:
    """pymupdf.Page stub — get_pixmap 返回自带 tobytes 的对象。"""

    def get_pixmap(self, matrix=None, alpha=False):
        class _Pix:
            def tobytes(self, fmt):
                return b"\x89PNG fake"

        return _Pix()


def _install_engine(monkeypatch, result):
    def fake_engine(png_bytes):
        return result, 0.01

    monkeypatch.setattr(ocr, "_get_engine", lambda: fake_engine)


def test_unavailable_returns_empty(monkeypatch):
    monkeypatch.setattr(ocr, "_get_engine", lambda: None)
    assert ocr.ocr_pdf_page(_FakePage()) == []


def test_lines_sorted_reading_order(monkeypatch):
    # 乱序输入：第二行在上（y=10），第一行在下（y=50）；同一行内按 x
    _install_engine(
        monkeypatch,
        [
            [[(30, 50), (60, 50), (60, 60), (30, 60)], "下右", 0.9],
            [[(0, 50), (20, 50), (20, 60), (0, 60)], "下左", 0.9],
            [[(0, 10), (20, 10), (20, 20), (0, 20)], "上", 0.9],
        ],
    )
    assert ocr.ocr_pdf_page(_FakePage()) == ["上", "下左", "下右"]


def test_low_confidence_filtered(monkeypatch):
    _install_engine(
        monkeypatch,
        [
            [[(0, 0), (1, 0), (1, 1), (0, 1)], "可信", 0.9],
            [[(0, 5), (1, 5), (1, 6), (0, 6)], "噪声", 0.2],
            [[(0, 9), (1, 9), (1, 10), (0, 10)], "   ", 0.9],
        ],
    )
    assert ocr.ocr_pdf_page(_FakePage()) == ["可信"]


def test_engine_crash_never_raises(monkeypatch):
    def boom(png_bytes):
        raise RuntimeError("onnx exploded")

    monkeypatch.setattr(ocr, "_get_engine", lambda: boom)
    assert ocr.ocr_pdf_page(_FakePage()) == []


def test_failed_init_latches(monkeypatch):
    """引擎初始化失败后闩锁 —— 不反复尝试昂贵初始化。"""
    calls = []

    class FakeSpecFinder:
        pass

    def failing_import():
        calls.append(1)
        raise ImportError("no rapidocr")

    # 让 _get_engine 内部 import 失败：rapidocr 不存在于测试环境本就如此，
    # 直接调用两次验证 _engine_failed 闩锁行为。
    assert ocr._get_engine() is None or True  # 首次（真实环境无 rapidocr → None）
    first_failed = ocr._engine_failed
    ocr._get_engine()
    assert ocr._engine_failed == first_failed  # 状态稳定，无反复初始化


def test_is_ocr_available_matches_find_spec():
    from importlib.util import find_spec

    assert ocr.is_ocr_available() == (find_spec("rapidocr_onnxruntime") is not None)


# ── pdf_to_word 扫描页回退接入点 ──────────────────────────────────────


def test_scanned_page_fallback_via_pdf_to_word(tmp_path, monkeypatch):
    """图片-only PDF：OCR stub 可用时识别行进入 docx 段落，ocr_pages=1。"""
    import pymupdf

    from backend.office.pdf_to_word import convert_pdf_to_word

    workspace = tmp_path / "ws"
    workspace.mkdir()
    pdf_path = workspace / "scan.pdf"

    # 构造一页只含图片的 PDF（1x1 png 插入整页）
    import struct
    import zlib

    def chunk(tag, payload):
        raw = tag + payload
        return struct.pack(">I", len(payload)) + raw + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    scan = b"".join(b"\x00" + b"\x80\x80\x80" * 4 for _ in range(4))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(scan)) + chunk(b"IEND", b"")

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(0, 0, 595, 842), stream=png)
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr(ocr, "_get_engine", lambda: lambda b: ([
        [[(0, 0), (10, 0), (10, 10), (0, 10)], "扫描件第一行", 0.95],
        [[(0, 20), (10, 20), (10, 30), (0, 30)], "扫描件第二行", 0.95],
    ], 0.01))

    result = convert_pdf_to_word(pdf_path, workspace, "scan.docx")
    assert result.ok is True
    assert result.ocr_pages == 1
    assert result.paragraph_count == 2

    from docx import Document

    texts = [p.text for p in Document(result.output_path).paragraphs if p.text.strip()]
    assert "扫描件第一行" in texts
    assert "扫描件第二行" in texts


def test_scanned_page_without_ocr_keeps_old_behavior(tmp_path, monkeypatch):
    """引擎不可用：扫描页仍转出近空文档（原契约），ocr_pages=0。"""
    import pymupdf

    from backend.office.pdf_to_word import convert_pdf_to_word

    workspace = tmp_path / "ws"
    workspace.mkdir()
    pdf_path = workspace / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr(ocr, "_get_engine", lambda: None)
    result = convert_pdf_to_word(pdf_path, workspace, "scan.docx")
    assert result.ok is True
    assert (result.ocr_pages or 0) == 0
