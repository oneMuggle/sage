"""Unit tests for M6b PDF tables: stats, complexity diagnosis, structured fallback."""

from __future__ import annotations

from pathlib import Path

from backend.office.extractors import ExtractRequest, extract_document, service as service_module
from backend.office.extractors.base import ExtractedBlock, StructuredDocument
from backend.office.extractors.tables import (
    assess_table_complexity,
    describe_complexity,
    table_markdown,
)
from backend.office.pdf import (
    _extract_page_tables_with_stats,
    _probe_borderless_table,
    read_pdf,
)


def _ruled_pdf(
    path: Path, *, rows: int = 3, cols: int = 2, merge_header: bool = False
) -> Path:
    """A PDF with a vector-ruled table; the header cell may be merged."""
    import pymupdf

    document = pymupdf.open()
    try:
        page = document.new_page(width=400, height=300)
        x0, y0 = 50, 50
        cell_w, cell_h = 60, 20
        for row in range(rows + 1):
            page.draw_line(
                pymupdf.Point(x0, y0 + row * cell_h),
                pymupdf.Point(x0 + cols * cell_w, y0 + row * cell_h),
            )
        for col in range(cols + 1):
            # A merged header drops the separator under the first row only.
            top = y0 + cell_h if (merge_header and col == 1) else y0
            page.draw_line(
                pymupdf.Point(x0 + col * cell_w, top),
                pymupdf.Point(x0 + col * cell_w, y0 + rows * cell_h),
            )
        for row in range(rows):
            for col in range(cols):
                if merge_header and row == 0 and col > 0:
                    continue
                page.insert_text(
                    (x0 + col * cell_w + 4, y0 + row * cell_h + 14),
                    f"{row}{col}",
                    fontname="helv",
                    fontsize=9,
                )
        document.save(str(path))
    finally:
        document.close()
    return path


def _borderless_pdf(path: Path) -> Path:
    """A PDF whose table is aligned by whitespace only — no ruling lines."""
    import pymupdf

    document = pymupdf.open()
    try:
        page = document.new_page(width=500, height=300)
        rows = [
            ("name", "age", "city"),
            ("alice", "30", "beijing"),
            ("bob", "28", "shanghai"),
            ("carol", "35", "shenzhen"),
        ]
        for index, row in enumerate(rows):
            for col, value in enumerate(row):
                page.insert_text(
                    (40 + col * 80, 50 + index * 20), value, fontname="cour", fontsize=10
                )
        document.save(str(path))
    finally:
        document.close()
    return path


def _prose_pdf(path: Path) -> Path:
    """Prose in a monospaced font — the known false positive of text alignment."""
    import pymupdf

    document = pymupdf.open()
    try:
        page = document.new_page(width=500, height=300)
        body = (
            "The quick brown fox jumps over the lazy dog while the committee "
            "reviews the quarterly figures and the secretary prepares minutes "
            "for distribution to every member of the board before the meeting."
        )
        for index in range(8):
            page.insert_text(
                (40, 40 + index * 16),
                body[: 60 + index * 5],
                fontname="cour",
                fontsize=9,
            )
        document.save(str(path))
    finally:
        document.close()
    return path


def _page_stats(source: Path):
    import pymupdf

    document = pymupdf.open(str(source))
    try:
        return _extract_page_tables_with_stats(document[0], page_number=1)
    finally:
        document.close()


class _FakeDocling:
    """Stand-in for the optional docling backend."""

    name = "docling"

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def supports(self, suffix: str) -> bool:
        return suffix.lower() == ".pdf"

    def extract(self, path: Path) -> StructuredDocument:
        if self._fail:
            raise RuntimeError("docling exploded")
        markdown = "| 00 | 01 |\n| --- | --- |\n| 10 | 11 |"
        return StructuredDocument(
            source_path=path.name,
            format="pdf",
            extractor=self.name,
            markdown=markdown,
            blocks=[
                ExtractedBlock(type="table", text=markdown, anchor={"table_index": 0})
            ],
        )


def _install_fake_docling(monkeypatch, *, fail: bool = False, available: bool = True) -> None:
    real_available = service_module.extractor_available
    real_get = service_module.get_extractor

    def extractor_available(name: str) -> bool:
        if name == "docling":
            return available
        return real_available(name)

    def get_extractor(name: str):
        if name == "docling":
            return _FakeDocling(fail=fail)
        return real_get(name)

    monkeypatch.setattr(service_module, "extractor_available", extractor_available)
    monkeypatch.setattr(service_module, "get_extractor", get_extractor)


def _extract_pdf(tmp_path: Path, source: Path, **kwargs):
    return extract_document(
        ExtractRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            backend=kwargs.pop("backend", "light"),
            **kwargs,
        )
    )


# ── tables.py ──────────────────────────────────────────────────────────


def test_table_markdown_renders_header_separator_and_rows() -> None:
    markdown = table_markdown([["a", "b"], ["1", "2"]])

    assert markdown.splitlines() == ["| a | b |", "| --- | --- |", "| 1 | 2 |"]


def test_table_markdown_escapes_pipes_and_flattens_newlines() -> None:
    markdown = table_markdown([["x|y", "line\nbreak"]])

    assert markdown.splitlines()[0] == "| x\\|y | line break |"


def test_table_markdown_of_no_rows_is_empty() -> None:
    assert table_markdown([]) == ""


def test_assess_table_complexity_reports_every_reason() -> None:
    diagnostics = {
        "null_cells": 1,
        "truncated": True,
        "max_cols": 12,
        "max_rows": 40,
        "failed_pages": 2,
        "borderless_candidate_pages": [3],
    }

    reasons = assess_table_complexity(diagnostics)

    assert reasons == [
        "merged_cells",
        "cell_cap_truncated",
        "wide_table",
        "tall_table",
        "table_detection_failed",
        "borderless_table_candidate",
    ]
    assert "合并单元格" in describe_complexity(reasons)


def test_assess_table_complexity_ignores_clean_tables() -> None:
    diagnostics = {
        "table_count": 1,
        "null_cells": 0,
        "total_cells": 6,
        "max_rows": 3,
        "max_cols": 2,
        "truncated": False,
        "failed_pages": 0,
        "borderless_candidate_pages": [],
    }

    assert assess_table_complexity(diagnostics) == []
    assert assess_table_complexity({}) == []


# ── PDF table statistics ───────────────────────────────────────────────


def test_page_table_stats_describe_ruled_table(tmp_path: Path) -> None:
    source = _ruled_pdf(tmp_path / "ruled.pdf")

    tables, stats = _page_stats(source)

    assert stats["table_count"] == 1
    assert stats["null_cells"] == 0
    assert stats["max_rows"] == 3
    assert stats["max_cols"] == 2
    assert stats["truncated"] is False
    assert stats["failed"] is False
    assert tables[0][0] == ["00", "01"]


def test_page_table_stats_count_merged_header_as_null_cell(tmp_path: Path) -> None:
    source = _ruled_pdf(tmp_path / "merged.pdf", merge_header=True)

    _tables, stats = _page_stats(source)

    assert stats["null_cells"] == 1
    assert "merged_cells" in assess_table_complexity(stats)


def test_borderless_probe_detects_table_but_not_prose(tmp_path: Path) -> None:
    import pymupdf

    table_pdf = _borderless_pdf(tmp_path / "borderless.pdf")
    prose_pdf = _prose_pdf(tmp_path / "prose.pdf")

    for source, expected in ((table_pdf, True), (prose_pdf, False)):
        document = pymupdf.open(str(source))
        try:
            detected = _probe_borderless_table(document[0], page_number=1)
        finally:
            document.close()
        assert detected is expected


def test_read_pdf_records_borderless_candidates_only_when_probing(tmp_path: Path) -> None:
    source = _borderless_pdf(tmp_path / "borderless.pdf")

    without = read_pdf(source, workspace_path=str(tmp_path))
    with_probe = read_pdf(
        source, workspace_path=str(tmp_path), probe_borderless_tables=True
    )

    assert without.table_diagnostics["borderless_candidate_pages"] == []
    assert with_probe.table_diagnostics["borderless_candidate_pages"] == [1]


# ── light backend ──────────────────────────────────────────────────────


def test_light_pdf_emits_table_blocks(tmp_path: Path) -> None:
    source = _ruled_pdf(tmp_path / "ruled.pdf")

    result = _extract_pdf(tmp_path, source)

    table_blocks = [block for block in result.document.blocks if block.type == "table"]
    assert len(table_blocks) == 1
    assert table_blocks[0].anchor == {"page": 1, "table_index": 0}
    assert "| 00 | 01 |" in result.document.markdown
    assert not any(warning["code"] == "table_complex" for warning in result.document.warnings)


def test_light_pdf_warns_on_complex_tables(tmp_path: Path) -> None:
    source = _ruled_pdf(tmp_path / "merged.pdf", merge_header=True)

    result = _extract_pdf(tmp_path, source)

    codes = [warning["code"] for warning in result.document.warnings]
    assert "table_complex" in codes
    assert result.document.table_diagnostics["null_cells"] == 1


# ── structured-backend fallback ────────────────────────────────────────


def test_complex_pdf_routes_to_structured_backend(tmp_path: Path, monkeypatch) -> None:
    _install_fake_docling(monkeypatch)
    source = _ruled_pdf(tmp_path / "merged.pdf", merge_header=True)

    result = _extract_pdf(tmp_path, source)

    assert result.extractor == "docling"
    codes = [warning["code"] for warning in result.document.warnings]
    assert "table_fallback_docling" in codes
    assert any(block.type == "table" for block in result.document.blocks)


def test_clean_pdf_does_not_trigger_fallback(tmp_path: Path, monkeypatch) -> None:
    _install_fake_docling(monkeypatch)
    source = _ruled_pdf(tmp_path / "clean.pdf")

    result = _extract_pdf(tmp_path, source)

    assert result.extractor == "light"
    codes = [warning["code"] for warning in result.document.warnings]
    assert not any(code.startswith("table_fallback") for code in codes)


def test_fallback_off_keeps_light_result(tmp_path: Path, monkeypatch) -> None:
    _install_fake_docling(monkeypatch)
    source = _ruled_pdf(tmp_path / "merged.pdf", merge_header=True)

    result = _extract_pdf(tmp_path, source, table_fallback="off")

    assert result.extractor == "light"
    codes = [warning["code"] for warning in result.document.warnings]
    assert not any(code.startswith("table_fallback") for code in codes)


def test_fallback_force_always_uses_structured_backend(tmp_path: Path, monkeypatch) -> None:
    _install_fake_docling(monkeypatch)
    source = _ruled_pdf(tmp_path / "clean.pdf")

    result = _extract_pdf(tmp_path, source, table_fallback="force")

    assert result.extractor == "docling"


def test_fallback_reports_unavailable_structured_backend(tmp_path: Path, monkeypatch) -> None:
    _install_fake_docling(monkeypatch, available=False)
    source = _ruled_pdf(tmp_path / "merged.pdf", merge_header=True)

    result = _extract_pdf(tmp_path, source)

    assert result.extractor == "light"
    codes = [warning["code"] for warning in result.document.warnings]
    assert "table_fallback_unavailable" in codes
    # The light result survives — the merged header cell shows up as a hole.
    assert "| 00 |  |" in result.document.markdown
    assert "| 10 | 11 |" in result.document.markdown


def test_fallback_failure_keeps_light_result(tmp_path: Path, monkeypatch) -> None:
    _install_fake_docling(monkeypatch, fail=True)
    source = _ruled_pdf(tmp_path / "merged.pdf", merge_header=True)

    result = _extract_pdf(tmp_path, source)

    assert result.extractor == "light"
    codes = [warning["code"] for warning in result.document.warnings]
    assert "table_fallback_failed" in codes
    assert "| 10 | 11 |" in result.document.markdown
