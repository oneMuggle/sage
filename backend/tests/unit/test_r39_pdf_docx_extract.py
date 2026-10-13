"""R39: pdf/docx/xlsx 附件提取文本单元测试

chat_attachment_routes 允许 .pdf/.docx/.xlsx 扩展后，提取文本注入聊天上下文。
依赖 pymupdf / python-docx / openpyxl —— CI 有；本地无则整文件 skip。
"""

from __future__ import annotations

import io

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

_requires_pdf = pytest.mark.skipif(not _HAS_PYMUPDF, reason="pymupdf not installed")
_requires_docx = pytest.mark.skipif(not _HAS_DOCX, reason="python-docx not installed")
_requires_xlsx = pytest.mark.skipif(not _HAS_OPENPYXL, reason="openpyxl not installed")


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


def _make_xlsx_bytes(rows: list[list[str]]) -> bytes:
    if not _HAS_OPENPYXL:
        pytest.skip("openpyxl not installed")
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
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
