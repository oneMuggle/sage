"""R39: pdf/docx/xlsx/pptx 附件提取文本单元测试

chat_attachment_routes 允许 .pdf/.docx/.xlsx/.pptx 扩展后，提取文本注入聊天上下文。
依赖 pymupdf / python-docx / openpyxl / python-pptx —— CI 有；本地无则对应用例 skip。
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import chat_attachment_routes

pytestmark = pytest.mark.unit

try:
    import pymupdf
    from docx import Document

    _HAS_PYMUPDF = True
    _HAS_DOCX = True
except ImportError:
    _HAS_PYMUPDF = False
    _HAS_DOCX = False

try:
    import openpyxl

    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False

try:
    from pptx import Presentation

    _HAS_PPTX = True
except ImportError:
    _HAS_PPTX = False

_requires_pdf = pytest.mark.skipif(not _HAS_PYMUPDF, reason="pymupdf not installed")
_requires_docx = pytest.mark.skipif(not _HAS_DOCX, reason="python-docx not installed")
_requires_xlsx = pytest.mark.skipif(not _HAS_OPENPYXL, reason="openpyxl not installed")
_requires_pptx = pytest.mark.skipif(not _HAS_PPTX, reason="python-pptx not installed")


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(chat_attachment_routes.router)
    return TestClient(app)


def _make_pdf_bytes(text: str) -> bytes:
    if not _HAS_PYMUPDF:
        pytest.skip("pymupdf not installed")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_docx_bytes(text: str) -> bytes:
    if not _HAS_DOCX:
        pytest.skip("python-docx not installed")
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestPdfExtraction:
    @_requires_pdf
    def test_upload_pdf_extracts_text(self, client):
        data = _make_pdf_bytes("hello from pdf")
        res = client.post(
            "/chat/attachments",
            files={"file": ("doc.pdf", data, "application/pdf")},
        )
        assert res.status_code == 200
        body = res.json()
        assert "error" not in body
        assert "hello from pdf" in body["text"]

    @_requires_pdf
    def test_get_text_pdf_roundtrip(self, client):
        data = _make_pdf_bytes("roundtrip pdf")
        created = client.post(
            "/chat/attachments",
            files={"file": ("doc.pdf", data, "application/pdf")},
        ).json()
        mid = created["media_ref"]["id"]
        res = client.get(f"/chat/attachments/{mid}/text")
        assert res.status_code == 200
        assert "roundtrip pdf" in res.json()["text"]


class TestDocxExtraction:
    @_requires_docx
    def test_upload_docx_extracts_paragraphs(self, client):
        data = _make_docx_bytes("hello from docx")
        res = client.post(
            "/chat/attachments",
            files={"file": ("doc.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert res.status_code == 200
        body = res.json()
        assert "error" not in body
        assert "hello from docx" in body["text"]

    @_requires_docx
    def test_get_text_docx_roundtrip(self, client):
        data = _make_docx_bytes("roundtrip docx")
        created = client.post(
            "/chat/attachments",
            files={"file": ("doc.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        ).json()
        mid = created["media_ref"]["id"]
        res = client.get(f"/chat/attachments/{mid}/text")
        assert res.status_code == 200
        assert "roundtrip docx" in res.json()["text"]


def _make_xlsx_bytes(rows: List[List[str]]) -> bytes:
    if not _HAS_OPENPYXL:
        pytest.skip("openpyxl not installed")
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_pptx_bytes(title: str, body: str, table_cell: str = "") -> bytes:
    if not _HAS_PPTX:
        pytest.skip("python-pptx not installed")
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    slide.placeholders[1].text = body
    if table_cell:
        table = slide.shapes.add_table(
            1, 1, 100000, 100000, 3000000, 500000
        ).table
        table.cell(0, 0).text = table_cell
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


class TestXlsxExtraction:
    @_requires_xlsx
    def test_upload_xlsx_extracts_cells(self, client):
        data = _make_xlsx_bytes([["name", "value"], ["alpha", "1"], ["beta", "2"]])
        res = client.post(
            "/chat/attachments",
            files={"file": ("data.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert res.status_code == 200
        body = res.json()
        assert "error" not in body
        assert "alpha" in body["text"]
        assert "beta" in body["text"]

    @_requires_xlsx
    def test_get_text_xlsx_roundtrip(self, client):
        data = _make_xlsx_bytes([["col_a", "col_b"], ["x", "y"]])
        created = client.post(
            "/chat/attachments",
            files={"file": ("data.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        ).json()
        mid = created["media_ref"]["id"]
        res = client.get(f"/chat/attachments/{mid}/text")
        assert res.status_code == 200
        assert "col_a" in res.json()["text"]


class TestPptxExtraction:
    @_requires_pptx
    def test_upload_pptx_extracts_slides(self, client):
        data = _make_pptx_bytes("Quarterly Review", "Revenue grew 12 percent", "North 42")
        res = client.post(
            "/chat/attachments",
            files={
                "file": (
                    "deck.pptx",
                    data,
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert "error" not in body
        assert "Quarterly Review" in body["text"]
        assert body["text"].count("Quarterly Review") == 1
        assert "Revenue grew 12 percent" in body["text"]
        assert "North 42" in body["text"]

    @_requires_pptx
    def test_get_text_pptx_roundtrip(self, client):
        data = _make_pptx_bytes("Roundtrip Deck", "slide body text")
        created = client.post(
            "/chat/attachments",
            files={
                "file": (
                    "deck.pptx",
                    data,
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
        ).json()
        mid = created["media_ref"]["id"]
        res = client.get(f"/chat/attachments/{mid}/text")
        assert res.status_code == 200
        assert "Roundtrip Deck" in res.json()["text"]
        assert "slide body text" in res.json()["text"]


class TestExtractDispatcher:
    """发送侧与上传侧共用的 extract_attachment_text 分发表。"""

    def test_plain_text_utf8(self):
        assert chat_attachment_routes.extract_attachment_text(b"hello", "txt") == "hello"

    def test_extension_with_leading_dot(self):
        assert chat_attachment_routes.extract_attachment_text(b"hi", ".md") == "hi"

    @_requires_xlsx
    def test_xlsx_uses_binary_extractor(self):
        """回归：xlsx 曾被发送侧当 UTF-8 文本解码 → not_utf8。"""
        data = _make_xlsx_bytes([["cell_a", "cell_b"]])
        text = chat_attachment_routes.extract_attachment_text(data, "xlsx")
        assert "cell_a" in text

    @_requires_pptx
    def test_pptx_uses_binary_extractor(self):
        data = _make_pptx_bytes("Dispatcher Title", "Dispatcher Body")
        text = chat_attachment_routes.extract_attachment_text(data, "pptx")
        assert "Dispatcher Title" in text
        assert "Dispatcher Body" in text


class TestSendPathContract:
    @_requires_xlsx
    def test_async_wrapper_uses_binary_extractor(self):
        data = _make_xlsx_bytes([["async_cell"]])
        text = asyncio.run(
            chat_attachment_routes.extract_attachment_text_async(data, "xlsx")
        )
        assert "async_cell" in text

    def test_legacy_send_path_calls_shared_dispatcher(self):
        """回归：发送侧必须调用统一异步分发器，不能退回 UTF-8 解码分支。"""
        source = (
            Path(__file__).resolve().parents[2] / "api" / "legacy_routes.py"
        ).read_text(encoding="utf-8")
        assert "_r66_car.extract_attachment_text_async" in source
        assert "_r66_car._extract_document_text" not in source
        assert 'r37_bytes.decode("utf-8")' not in source


class TestOfficeZipBudget:
    def test_rejects_oversized_uncompressed(self, monkeypatch):
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("a.xml", b"012345")
            archive.writestr("b.xml", b"789012")
        monkeypatch.setattr(chat_attachment_routes, "MAX_OFFICE_UNCOMPRESSED_BYTES", 10)
        with pytest.raises(ValueError, match="解压后过大"):
            chat_attachment_routes._guard_office_zip_budget(buf.getvalue())

    def test_rejects_oversized_member(self, monkeypatch):
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("a.xml", b"0123456789")
        monkeypatch.setattr(chat_attachment_routes, "MAX_OFFICE_UNCOMPRESSED_BYTES", 5)
        with pytest.raises(ValueError, match="成员大小非法"):
            chat_attachment_routes._guard_office_zip_budget(buf.getvalue())

    @_requires_xlsx
    def test_accepts_normal_office_file(self):
        chat_attachment_routes._guard_office_zip_budget(_make_xlsx_bytes([["x"]]))

    def test_rejects_too_many_members(self, monkeypatch):
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("a.xml", b"<a/>")
            archive.writestr("b.xml", b"<b/>")
        monkeypatch.setattr(chat_attachment_routes, "MAX_OFFICE_ZIP_MEMBERS", 1)
        with pytest.raises(ValueError, match="条目过多"):
            chat_attachment_routes._guard_office_zip_budget(buf.getvalue())
