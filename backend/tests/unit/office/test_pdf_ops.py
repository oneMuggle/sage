"""Unit tests for M6 PDF page operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.errors import OfficeParseError, OfficePathError
from backend.office.pdf_ops import (
    PdfMergeRequest,
    PdfPageNumbersRequest,
    PdfPagesRequest,
    PdfRotateRequest,
    PdfSplitRequest,
    PdfWatermarkRequest,
    merge_pdfs,
    number_pdf_pages,
    rotate_pdf,
    split_pdf,
    update_pages,
    watermark_pdf,
)


def _pdf(path: Path, pages: int = 2, prefix: str = "Page") -> Path:
    import fitz

    document = fitz.open()
    try:
        for index in range(1, pages + 1):
            page = document.new_page(width=595.28, height=841.89)
            page.insert_text((72, 72), f"{prefix} {index}", fontname="helv", fontsize=12)
        document.save(str(path))
    finally:
        document.close()
    return path


def _text(path: Path) -> str:
    import fitz

    document = fitz.open(str(path))
    try:
        return "\n".join(page.get_text() for page in document)
    finally:
        document.close()


def _page_count(path: Path) -> int:
    import fitz

    document = fitz.open(str(path))
    try:
        return document.page_count
    finally:
        document.close()


def test_merge_pdfs_concatenates_in_order(tmp_path: Path) -> None:
    first = _pdf(tmp_path / "a.pdf", 2, "A")
    second = _pdf(tmp_path / "b.pdf", 1, "B")

    result = merge_pdfs(
        PdfMergeRequest(
            workspace_path=str(tmp_path),
            file_paths=[str(first), str(second)],
            output_filename="merged.pdf",
        )
    )

    assert result.ok is True
    output = tmp_path / result.outputs[0]
    assert _page_count(output) == 3
    text = _text(output)
    assert "A 2" in text
    assert "B 1" in text


def test_rotate_selected_page(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "doc.pdf", 2)

    result = rotate_pdf(
        PdfRotateRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            angle=90,
            pages=["1"],
        )
    )

    import fitz

    document = fitz.open(str(tmp_path / result.outputs[0]))
    try:
        assert document.load_page(0).rotation == 90
        assert document.load_page(1).rotation == 0
    finally:
        document.close()


def test_extract_and_delete_pages(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "doc.pdf", 3)

    extracted = update_pages(
        PdfPagesRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            action="extract",
            pages=["1"],
        )
    )
    extract_path = tmp_path / extracted.outputs[0]
    assert _page_count(extract_path) == 1
    assert "Page 1" in _text(extract_path)

    removed = update_pages(
        PdfPagesRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            action="delete",
            pages=["2"],
        )
    )
    removed_path = tmp_path / removed.outputs[0]
    assert _page_count(removed_path) == 2
    text = _text(removed_path)
    assert "Page 1" in text
    assert "Page 3" in text


def test_split_pdf_creates_one_file_per_range(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "doc.pdf", 3)

    result = split_pdf(
        PdfSplitRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            ranges=["1", "2-3"],
            output_prefix="part",
        )
    )

    assert len(result.outputs) == 2
    assert _page_count(tmp_path / result.outputs[0]) == 1
    assert _page_count(tmp_path / result.outputs[1]) == 2


def test_watermark_and_page_numbers(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "doc.pdf", 2)

    watermarked = watermark_pdf(
        PdfWatermarkRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            text="SAGE",
        )
    )
    assert "SAGE" in _text(tmp_path / watermarked.outputs[0])

    numbered = number_pdf_pages(
        PdfPageNumbersRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            start=1,
            template="P{n}",
        )
    )
    text = _text(tmp_path / numbered.outputs[0])
    assert "P1" in text
    assert "P2" in text


def test_split_invalid_range_leaves_no_partial_outputs(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "doc.pdf", 3)

    with pytest.raises(OfficeParseError):
        split_pdf(
            PdfSplitRequest(
                workspace_path=str(tmp_path),
                file_path=str(source),
                ranges=["1", "4"],
            )
        )

    assert not (tmp_path / "doc-1.pdf").exists()


def test_invalid_page_range_is_rejected(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "doc.pdf", 2)

    with pytest.raises(OfficeParseError):
        update_pages(
            PdfPagesRequest(
                workspace_path=str(tmp_path),
                file_path=str(source),
                action="extract",
                pages=["3"],
            )
        )


def test_refuses_existing_output(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "doc.pdf", 2)
    (tmp_path / "doc-rotated.pdf").write_bytes(b"occupied")

    with pytest.raises(OfficeParseError):
        rotate_pdf(
            PdfRotateRequest(
                workspace_path=str(tmp_path), file_path=str(source), angle=90
            )
        )


def test_rejects_path_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = _pdf(tmp_path / "outside.pdf", 1)

    with pytest.raises(OfficePathError):
        rotate_pdf(
            PdfRotateRequest(
                workspace_path=str(workspace), file_path=str(outside), angle=90
            )
        )
