"""Unit tests for the Office text extraction adapter (Task 3 step 5+6).

``backend.wiki.extract.extract_text_for_ingest`` is the bridge that lets
DOCX/PPTX/XLSX files flow through the existing Wiki ingest pipeline
(which originally only handled plain text via ``Path.read_text``).

The contract:

* **Plain text** suffixes (``.md``, ``.markdown``, ``.txt``) are passed
  through unchanged.
* **Office binaries** (``.docx``, ``.pptx``, ``.xlsx``) are decoded via
  the existing :mod:`backend.office` readers, flattened to text, and
  returned with an explicit ``truncated`` flag when the text byte cap
  is hit.
* **Unsupported** extensions raise :class:`ValueError` so the caller
  surfaces a clear error instead of pretending the file was empty.
* **Hard limits** are enforced before / during parse:

  - ``max_file_bytes`` rejects oversized files *before* opening them
    (single file size cap).
  - ``max_text_chars`` bounds the returned text and flags truncation.
  - ``max_seconds`` caps total parse wall-clock and raises on overrun.

The tests exercise real DOCX/PPTX/XLSX fixtures built from the existing
generators (round-trip) so we don't depend on synthetic binary blobs.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.office.errors import OfficeParseError
from backend.office.excel import generate_xlsx
from backend.office.models import (
    OfficeExcelGenerateRequest,
    OfficePptGenerateRequest,
    OfficeWordGenerateRequest,
)
from backend.office.ppt import generate_ppt
from backend.office.word import generate_docx

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────────────────────────────
# Fixtures: real Office binaries via the existing generators
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def docx_path(tmp_path: Path) -> Path:
    """Generate a real DOCX with paragraphs + a small table."""
    req = OfficeWordGenerateRequest(
        title="Sample",
        paragraphs=[
            {"text": "First paragraph about topic alpha.", "heading": None},
            {"text": "Second paragraph about topic beta.", "heading": None},
        ],
        tables=[
            {
                "headers": ["A", "B"],
                "rows": [["1", "2"], ["3", "4"]],
            }
        ],
        workspace_path=str(tmp_path),
        filename="sample.docx",
    )
    return generate_docx(req, output_dir=str(tmp_path))


@pytest.fixture()
def pptx_path(tmp_path: Path) -> Path:
    req = OfficePptGenerateRequest(
        slides=[
            {
                "title": "Slide One",
                "bullets": ["Alpha bullet", "Beta bullet"],
                "notes": "Speaker notes for slide one.",
            },
            {
                "title": "Slide Two",
                "bullets": ["Gamma bullet"],
                "notes": None,
            },
        ],
        workspace_path=str(tmp_path),
        filename="sample.pptx",
    )
    return generate_ppt(req, output_dir=str(tmp_path))


@pytest.fixture()
def xlsx_path(tmp_path: Path) -> Path:
    req = OfficeExcelGenerateRequest(
        sheets=[
            {
                "name": "Data",
                "headers": ["col1", "col2"],
                "rows": [["alpha", "1"], ["beta", "2"]],
            }
        ],
        workspace_path=str(tmp_path),
        filename="sample.xlsx",
    )
    return generate_xlsx(req, output_dir=str(tmp_path))


# ──────────────────────────────────────────────────────────────────────
# Plain text passthrough
# ──────────────────────────────────────────────────────────────────────


def test_plain_markdown_passthrough(tmp_path: Path):
    """Markdown files are returned verbatim (caller slices the cap)."""
    from backend.wiki.extract import extract_text_for_ingest

    src = tmp_path / "note.md"
    src.write_text("# Hello\n\nbody", encoding="utf-8")

    text = extract_text_for_ingest(src)
    assert "Hello" in text
    assert "body" in text


def test_plain_txt_passthrough(tmp_path: Path):
    from backend.wiki.extract import extract_text_for_ingest

    src = tmp_path / "note.txt"
    src.write_text("plain text content", encoding="utf-8")

    assert extract_text_for_ingest(src) == "plain text content"


# ──────────────────────────────────────────────────────────────────────
# Office binaries
# ──────────────────────────────────────────────────────────────────────


def test_docx_extract_returns_paragraphs_and_tables(docx_path: Path):
    from backend.wiki.extract import extract_text_for_ingest

    text = extract_text_for_ingest(docx_path)
    # Paragraph text appears.
    assert "First paragraph about topic alpha." in text
    assert "Second paragraph about topic beta." in text
    # Table cells appear (flattened).
    assert "A" in text
    assert "B" in text
    assert "1" in text


def test_pptx_extract_returns_slide_titles_and_bullets(pptx_path: Path):
    from backend.wiki.extract import extract_text_for_ingest

    text = extract_text_for_ingest(pptx_path)
    assert "Slide One" in text
    assert "Alpha bullet" in text
    assert "Beta bullet" in text
    assert "Slide Two" in text
    assert "Gamma bullet" in text
    assert "Speaker notes for slide one." in text


def test_xlsx_extract_returns_sheet_headers_and_rows(xlsx_path: Path):
    from backend.wiki.extract import extract_text_for_ingest

    text = extract_text_for_ingest(xlsx_path)
    assert "Data" in text  # sheet name
    assert "col1" in text
    assert "col2" in text
    assert "alpha" in text
    assert "beta" in text


# ──────────────────────────────────────────────────────────────────────
# Hard limits
# ──────────────────────────────────────────────────────────────────────


def test_oversized_file_rejected_before_open(tmp_path: Path):
    """``max_file_bytes`` must short-circuit before openpyxl/python-docx
    crash on multi-GB inputs.
    """
    from backend.wiki.extract import (
        MAX_FILE_BYTES,
        FileTooLargeError,
        extract_text_for_ingest,
    )

    big = tmp_path / "huge.docx"
    big.write_bytes(b"PK\x03\x04" + b"\x00" * 1024)  # 1KB ZIP-like header

    # 1KB file < 1MB cap → size gate passes, parser raises because the
    # fake DOCX body is not a real ZIP (regression guard: parser is
    # actually invoked when the gate lets the file through).
    with pytest.raises(OfficeParseError, match=r"Failed to parse DOCX"):
        extract_text_for_ingest(big, max_file_bytes=1024 * 1024)

    # 1KB file > 512B cap → FileTooLargeError BEFORE any open.
    with pytest.raises(FileTooLargeError):
        extract_text_for_ingest(big, max_file_bytes=512)

    # Default cap is exported and >= 1MB (spec: "限制单文件大小").
    assert MAX_FILE_BYTES >= 1 * 1024 * 1024


def test_text_byte_cap_truncates_docx(docx_path: Path):
    """``max_text_chars`` bounds the returned string; ``truncated`` flag set."""
    from backend.wiki.extract import extract_text_for_ingest

    # Tiny cap so we deterministically overflow.
    text, meta = extract_text_for_ingest(docx_path, max_text_chars=20, return_meta=True)
    assert len(text) <= 20
    assert meta["truncated"] is True
    assert meta["doc_type"] == "docx"


def test_text_byte_cap_zero_is_fine(tmp_path: Path):
    """A 0 cap must not crash — it should return empty + truncated=True."""
    from backend.wiki.extract import extract_text_for_ingest

    plain = tmp_path / "a.md"
    plain.write_text("hello", encoding="utf-8")
    text, meta = extract_text_for_ingest(plain, max_text_chars=0, return_meta=True)
    assert text == ""
    assert meta["truncated"] is True


def test_parse_timeout_raises_soft_error(tmp_path: Path, monkeypatch):
    """A parser that overruns ``max_seconds`` must raise a safe error
    so the Wiki ingest pipeline surfaces a structured failure instead
    of hanging the chat.
    """
    from backend.wiki import extract as ext

    def _slow(*_a, **_kw):
        # Force overrun regardless of the host's clock resolution.
        time.sleep(0.5)
        return "STUB"

    # Patch _read_docx_text inside the module (not the office readers
    # themselves, so other tests still get fast results).
    monkeypatch.setattr(ext, "_read_docx_text", _slow)

    src = tmp_path / "real.docx"
    # Real-but-tiny DOCX header; the timeout fires before the parser
    # inspects payload validity.
    src.write_bytes(b"PK\x03\x04" + b"\x00" * 64)

    with pytest.raises(ext.ParseTimeoutError):
        # max_seconds=0.05 → guaranteed overrun from a 0.5s sleep.
        ext.extract_text_for_ingest(src, max_seconds=0.05)


def test_unsupported_suffix_raises_value_error(tmp_path: Path):
    """Passing a path the adapter doesn't know must raise immediately —
    the Wiki ingest pipeline has its own file-type validator upstream,
    so we don't accept random binaries here.
    """
    from backend.wiki.extract import extract_text_for_ingest

    weird = tmp_path / "thing.exe"
    weird.write_bytes(b"MZ\x00\x00")

    with pytest.raises(ValueError, match=r"unsupported_suffix"):
        extract_text_for_ingest(weird)


def test_office_zip_budget_rejects_before_reader(monkeypatch, tmp_path: Path):
    """The public ingest adapter gates Office expansion before its reader."""
    import backend.wiki.extract as ext

    source = tmp_path / "bomb.docx"
    source.write_bytes(b"small")
    monkeypatch.setattr(ext, "_read_docx_text", lambda _path: "must not run")
    monkeypatch.setattr(ext, "_office_zip_within_budget", lambda _path: False)

    with pytest.raises(ValueError, match="Office ZIP expansion"):
        ext.extract_text_for_ingest(source)


def test_office_zip_member_count_rejects_before_reader(monkeypatch, tmp_path: Path):
    """An excessive central-directory member count is rejected pre-reader."""
    import sys
    from types import SimpleNamespace
    from unittest.mock import Mock

    import backend.wiki.extract as ext

    source = tmp_path / "many.docx"
    source.write_bytes(b"small")
    archive = Mock()
    archive.__enter__ = Mock(return_value=archive)
    archive.__exit__ = Mock(return_value=False)
    archive.infolist.return_value = [SimpleNamespace(file_size=0)] * (
        ext.MAX_OFFICE_ZIP_MEMBERS + 1
    )
    monkeypatch.setitem(
        sys.modules, "zipfile", SimpleNamespace(ZipFile=Mock(return_value=archive))
    )
    reader = Mock(side_effect=AssertionError("reader must not run"))
    monkeypatch.setattr(ext, "_read_docx_text", reader)

    with pytest.raises(ValueError, match="Office ZIP expansion"):
        ext.extract_text_for_ingest(source)
    reader.assert_not_called()


def test_office_reader_uses_held_fd_proc_path(monkeypatch, tmp_path: Path):
    """The ZIP check and reader both use the held descriptor pathname."""
    import os

    import backend.wiki.extract as ext

    source = tmp_path / "held.docx"
    source.write_bytes(b"small")
    fd = os.open(source, os.O_RDONLY)
    seen = []
    try:
        monkeypatch.setattr(
            ext,
            "_office_zip_within_budget",
            lambda path: seen.append(path) or True,
        )
        monkeypatch.setattr(
            ext, "_read_docx_text", lambda path: seen.append(path) or "ok"
        )
        assert ext.extract_text_for_ingest(source, opened_fd=fd) == "ok"
    finally:
        os.close(fd)
    assert all(str(path).startswith("/proc/self/fd/") for path in seen)


# ──────────────────────────────────────────────────────────────────────
# Module surface
# ──────────────────────────────────────────────────────────────────────


def test_module_exposes_constants_and_helpers():
    """Regression guard: the limits are part of the public surface and
    downstream tools / observability rely on them.
    """
    import backend.wiki.extract as ext

    assert hasattr(ext, "extract_text_for_ingest")
    assert hasattr(ext, "MAX_FILE_BYTES")
    assert hasattr(ext, "MAX_TEXT_CHARS")
    assert hasattr(ext, "MAX_PARSE_SECONDS")
    assert issubclass(ext.FileTooLargeError, Exception)
    assert issubclass(ext.ParseTimeoutError, Exception)


# ──────────────────────────────────────────────────────────────────────
# Integration with wiki ingest
# ──────────────────────────────────────────────────────────────────────


def test_wiki_ingest_uses_adapter_for_docx(tmp_path: Path, monkeypatch):
    """The wiki ingest ``analyze_source`` helper must route Office
    binaries through ``extract_text_for_ingest`` instead of
    ``Path.read_text`` (which would raise on binary content).
    """
    from backend.wiki import ingest as wiki_ingest

    captured: dict = {}

    def _fake_extract(path, **_kw):
        captured["path"] = str(path)
        return "synthetic office content"

    monkeypatch.setattr(wiki_ingest, "extract_text_for_ingest", _fake_extract)

    fake_target = tmp_path / "report.docx"
    fake_target.write_bytes(b"PK\x03\x04stub")

    async def _noop_llm(messages, temperature):
        return "{}"

    import asyncio
    asyncio.run(
        wiki_ingest.analyze_source(fake_target, _noop_llm)
    )

    assert captured.get("path") == str(fake_target)
