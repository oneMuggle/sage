"""Integration tests for the batch audit route (M5b)."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from backend.api.office_word_audit_routes import (
    WordBatchAuditRequest,
    batch_audit_endpoint,
)
from backend.office.errors import OfficeParseError
from backend.office.word_rulepack_models import WordRulePack, WordRuleSpec


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


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


def _doc(path: Path, text: str) -> None:
    document = Document()
    document.add_paragraph(text)
    document.save(str(path))


def test_batch_endpoint_audits_workspace(workspace: Path) -> None:
    _doc(workspace / "clean.docx", "正文")
    _doc(workspace / "dirty.docx", "残留 {{name}}")

    result = batch_audit_endpoint(
        WordBatchAuditRequest(
            workspace_path=str(workspace),
            rulepack=_pack(),
            include_report=True,
        )
    )

    assert result.totals.files == 2
    assert result.totals.error_count == 1
    assert result.report_markdown is not None
    assert "dirty.docx" in result.report_markdown


def test_batch_endpoint_rejects_bad_pattern_and_escape(workspace: Path) -> None:
    _doc(workspace / "doc.docx", "正文")

    with pytest.raises(OfficeParseError):
        batch_audit_endpoint(
            WordBatchAuditRequest(
                workspace_path=str(workspace),
                rulepack=_pack(),
                pattern="../*.docx",
            )
        )
    with pytest.raises(OfficeParseError):
        batch_audit_endpoint(
            WordBatchAuditRequest(
                workspace_path=str(workspace),
                rulepack=_pack(),
                file_paths=["../outside.docx"],
            )
        )
