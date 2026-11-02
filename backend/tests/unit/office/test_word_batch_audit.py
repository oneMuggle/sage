"""Unit tests for batch Word audit (M5b)."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from backend.office.errors import OfficeParseError
from backend.office.word_batch_audit import audit_word_batch, collect_docx_files
from backend.office.word_rulepack_models import WordRulePack, WordRuleSpec


def _pack() -> WordRulePack:
    return WordRulePack(
        id="batch-pack",
        name="Batch pack",
        rules=[
            WordRuleSpec(
                id="content/placeholder_residue",
                title="无占位符",
                category="content",
                severity="error",
                kind="content.placeholder_residue",
                params={},
            )
        ],
    )


def _doc(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_paragraph(text)
    document.save(str(path))
    return path


def test_collect_docx_files_explicit_and_pattern(tmp_path: Path) -> None:
    _doc(tmp_path / "clean.docx", "正文")
    dirty = _doc(tmp_path / "nested" / "dirty.docx", "残留 {{name}}")
    _doc(tmp_path / ".git" / "hidden.docx", "正文")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    explicit = collect_docx_files(
        tmp_path, file_paths=["clean.docx", str(dirty), "clean.docx", "notes.txt"]
    )
    assert [path.name for path in explicit] == ["clean.docx", "dirty.docx"]

    patterned = collect_docx_files(tmp_path, pattern="**/*.docx")
    assert [path.relative_to(tmp_path).as_posix() for path in patterned] == [
        "clean.docx",
        "nested/dirty.docx",
    ]

    limited = collect_docx_files(tmp_path, pattern="**/*.docx", max_files=1)
    assert len(limited) == 1


def test_collect_rejects_escape_and_bad_pattern(tmp_path: Path) -> None:
    _doc(tmp_path / "doc.docx", "正文")

    with pytest.raises(OfficeParseError):
        collect_docx_files(tmp_path, file_paths=["../outside.docx"])
    with pytest.raises(OfficeParseError):
        collect_docx_files(tmp_path, pattern="../*.docx")
    with pytest.raises(OfficeParseError):
        collect_docx_files(tmp_path, max_files=0)


def test_batch_audit_totals_and_report(tmp_path: Path) -> None:
    _doc(tmp_path / "clean.docx", "正文")
    _doc(tmp_path / "nested" / "dirty.docx", "残留 {{name}}")

    result = audit_word_batch(tmp_path, _pack(), include_report=True)

    assert result.ok is False
    assert result.totals.files == 2
    assert result.totals.ok_files == 2
    assert result.totals.failed_files == 0
    assert result.totals.error_count == 1
    assert result.report_markdown is not None
    assert "clean.docx" in result.report_markdown
    assert "nested/dirty.docx" in result.report_markdown
    assert "1 错误" in result.report_markdown
    dirty = next(
        file for file in result.files if file.source_path.endswith("dirty.docx")
    )
    assert dirty.ok is False
    assert dirty.issues[0].rule_id == "content/placeholder_residue"


def test_batch_audit_reports_parse_failures_and_size(tmp_path: Path) -> None:
    _doc(tmp_path / "clean.docx", "正文")
    (tmp_path / "broken.docx").write_bytes(b"not a docx")

    result = audit_word_batch(tmp_path, _pack(), include_report=False)

    assert result.report_markdown is None
    assert result.totals.failed_files == 1
    broken = next(file for file in result.files if file.source_path == "broken.docx")
    assert broken.ok is False
    assert broken.error

    sized = audit_word_batch(
        tmp_path,
        _pack(),
        file_paths=["clean.docx"],
        max_size_bytes=1024,
        include_report=False,
    )
    assert sized.totals.failed_files == 1
    assert sized.files[0].error == "文件超过大小上限"


def test_batch_audit_clean_workspace_is_ok(tmp_path: Path) -> None:
    _doc(tmp_path / "clean.docx", "正文")

    result = audit_word_batch(tmp_path, _pack())

    assert result.ok is True
    assert result.totals.files == 1
    assert result.totals.error_count == 0
