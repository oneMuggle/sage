"""Security regressions for bounded Office ZIP expansion."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.wiki import file_parser


@pytest.mark.unit()
def test_docx_image_extraction_rejects_oversized_member_before_read(monkeypatch):
    info = SimpleNamespace(filename="word/media/bomb.png", file_size=file_parser.MAX_IMAGE_BYTES + 1)
    archive = Mock()
    archive.__enter__ = Mock(return_value=archive)
    archive.__exit__ = Mock(return_value=False)
    archive.infolist.return_value = [info]
    zip_module = SimpleNamespace(ZipFile=Mock(return_value=archive))
    monkeypatch.setitem(sys.modules, "zipfile", zip_module)

    assert file_parser._extract_images_docx(Path("bomb.docx")) == []
    archive.read.assert_not_called()


@pytest.mark.unit()
def test_pptx_image_extraction_rejects_total_budget_before_read(monkeypatch):
    infos = [
        SimpleNamespace(filename="ppt/media/one.png", file_size=file_parser.MAX_IMAGE_BYTES),
        SimpleNamespace(filename="ppt/media/two.png", file_size=1),
    ]
    archive = Mock()
    archive.__enter__ = Mock(return_value=archive)
    archive.__exit__ = Mock(return_value=False)
    archive.infolist.return_value = infos
    archive.read.side_effect = [b"x" * file_parser.MAX_IMAGE_BYTES, b"x"]
    zip_module = SimpleNamespace(ZipFile=Mock(return_value=archive))
    monkeypatch.setitem(sys.modules, "zipfile", zip_module)

    assert file_parser._extract_images_pptx(Path("bomb.pptx")) == []
    assert archive.read.call_count == 1


@pytest.mark.unit()
def test_parse_document_rejects_office_zip_budget_before_parser(monkeypatch, tmp_path):
    source = tmp_path / "bomb.docx"
    source.write_bytes(b"small zip container")
    monkeypatch.setattr(file_parser, "_office_zip_within_budget", lambda _path: False)
    parser = Mock(side_effect=AssertionError("Office parser must not run"))
    monkeypatch.setattr(file_parser, "_parse_docx", parser)

    with pytest.raises(ValueError, match="Office ZIP expansion"):
        file_parser.parse_document(source, max_seconds=0)
    parser.assert_not_called()


@pytest.mark.unit()
def test_parse_document_reads_xlsx_through_opened_descriptor(monkeypatch, tmp_path):
    source = tmp_path / "data.xlsx"
    source.write_bytes(b"xlsx")
    monkeypatch.setattr(file_parser, "_office_zip_within_budget", lambda _path: True)
    monkeypatch.setattr(file_parser, "_parse_xlsx", lambda path: str(path))

    fd = source.open("rb")
    try:
        text = file_parser.parse_document(source, opened_fd=fd.fileno(), max_seconds=0)
    finally:
        fd.close()

    assert "/proc/self/fd/" in text


def test_pdf_image_budget_rejects_oversized_image_before_append(monkeypatch):
    class FakeDoc:
        def __iter__(self):
            return iter([object()])

        def close(self):
            self.closed = True

        def extract_image(self, _xref):
            return {"image": b"x" * (file_parser.MAX_IMAGE_BYTES + 1), "ext": "png"}

    class FakeFitz:
        def open(self, _path):
            return FakeDoc()

    monkeypatch.setitem(sys.modules, "fitz", FakeFitz())
    assert file_parser._extract_images_pdf(Path("x.pdf")) == []


    info = SimpleNamespace(
        filename="word/document.xml",
        file_size=file_parser.MAX_OFFICE_UNCOMPRESSED_BYTES + 1,
    )
    archive = Mock()
    archive.__enter__ = Mock(return_value=archive)
    archive.__exit__ = Mock(return_value=False)
    archive.infolist.return_value = [info]
    zip_module = SimpleNamespace(ZipFile=Mock(return_value=archive))
    monkeypatch.setitem(sys.modules, "zipfile", zip_module)

    assert file_parser._office_zip_within_budget(Path("bomb.docx")) is False
    archive.read.assert_not_called()
