"""Unit tests for M3 Word tracked changes (read + accept/reject)."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from backend.office.errors import OfficeParseError
from backend.office.word import read_docx
from backend.office.word_revision_writer import apply_word_revisions
from backend.office.word_tracked_changes import (
    WordTrackedChangesResolveRequest,
    read_word_tracked_changes,
    resolve_word_tracked_changes,
)


def _revised_doc(tmp_path: Path) -> Path:
    source = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("Hello AI")
    document.save(str(source))
    result = apply_word_revisions(
        source,
        [{"find": "AI", "replace": "人工智能"}],
        "revised.docx",
        workspace_path=str(tmp_path),
        add_comments=False,
    )
    assert result.applied == 1
    return tmp_path / "revised.docx"


def test_read_tracked_changes_reports_insert_and_delete(tmp_path: Path) -> None:
    revised = _revised_doc(tmp_path)

    result = read_word_tracked_changes(str(tmp_path), str(revised))

    kinds = {change.kind for change in result.changes}
    texts = {change.text for change in result.changes}
    assert kinds == {"insert", "delete"}
    assert "人工智能" in texts
    assert "AI" in texts
    assert all(change.paragraph_index == 0 for change in result.changes)
    assert all(change.author for change in result.changes)


def test_read_docx_includes_tracked_changes(tmp_path: Path) -> None:
    revised = _revised_doc(tmp_path)

    result = read_docx(revised)

    assert {change.kind for change in result.tracked_changes} == {"insert", "delete"}


def test_resolve_accept_keeps_insertions_and_drops_deletions(tmp_path: Path) -> None:
    revised = _revised_doc(tmp_path)

    result = resolve_word_tracked_changes(
        WordTrackedChangesResolveRequest(
            workspace_path=str(tmp_path),
            file_path=str(revised),
            mode="accept",
        )
    )

    assert result.ok is True
    assert result.insertions == 1
    assert result.deletions == 1
    accepted = Document(str(tmp_path / result.output_path))
    assert accepted.paragraphs[0].text == "Hello 人工智能"
    paragraph = accepted.paragraphs[0]._p
    assert not list(paragraph.iter(qn("w:ins")))
    assert not list(paragraph.iter(qn("w:del")))


def test_resolve_reject_restores_original_text(tmp_path: Path) -> None:
    revised = _revised_doc(tmp_path)

    result = resolve_word_tracked_changes(
        WordTrackedChangesResolveRequest(
            workspace_path=str(tmp_path),
            file_path=str(revised),
            mode="reject",
        )
    )

    assert result.ok is True
    rejected = Document(str(tmp_path / result.output_path))
    assert rejected.paragraphs[0].text == "Hello AI"
    paragraph = rejected.paragraphs[0]._p
    assert not list(paragraph.iter(qn("w:ins")))
    assert not list(paragraph.iter(qn("w:del")))


def test_resolve_overwrite_replaces_source(tmp_path: Path) -> None:
    revised = _revised_doc(tmp_path)

    result = resolve_word_tracked_changes(
        WordTrackedChangesResolveRequest(
            workspace_path=str(tmp_path),
            file_path=str(revised),
            mode="accept",
            overwrite=True,
        )
    )

    assert result.overwritten is True
    assert result.output_path == result.source_path
    assert Document(str(revised)).paragraphs[0].text == "Hello 人工智能"


def test_resolve_refuses_existing_output(tmp_path: Path) -> None:
    revised = _revised_doc(tmp_path)
    (tmp_path / "revised-accepted.docx").write_bytes(b"occupied")

    with pytest.raises(OfficeParseError):
        resolve_word_tracked_changes(
            WordTrackedChangesResolveRequest(
                workspace_path=str(tmp_path),
                file_path=str(revised),
                mode="accept",
            )
        )
