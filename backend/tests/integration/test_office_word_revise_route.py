"""Integration tests for the native revision route (M4b)."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from backend.api.office_word_audit_routes import (
    WordAuditReviseRequest,
    WordRevisionChangeRequest,
    revise_word_endpoint,
)
from backend.office.errors import OfficeParseError, OfficePathError, OfficeSizeLimitError
from backend.office.word_rulepack_models import WordRulePack, WordRuleSpec


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _term_pack() -> WordRulePack:
    return WordRulePack(
        id="revise-pack",
        name="Revise pack",
        rules=[
            WordRuleSpec(
                id="content/terminology",
                title="术语统一",
                category="content",
                severity="warning",
                kind="content.terminology",
                params={"pairs": [{"preferred": "人工智能", "variants": ["AI"]}]},
                fixable=True,
                fix_hint="统一为人工智能",
            )
        ],
    )


def _save_doc(workspace: Path, text: str = "我们采用 AI 方案。") -> Path:
    document = Document()
    document.add_paragraph(text)
    path = workspace / "doc.docx"
    document.save(str(path))
    return path


def test_revise_endpoint_derives_plan_from_audit(workspace: Path) -> None:
    path = _save_doc(workspace)

    result = revise_word_endpoint(
        WordAuditReviseRequest(
            workspace_path=str(workspace),
            file_path=str(path),
            rulepack=_term_pack(),
            output_filename="revised.docx",
        )
    )

    assert result.applied == 1
    assert result.skipped == 0
    assert result.output_path == "revised.docx"
    assert result.remaining is not None
    assert not any(
        issue.rule_id == "content/terminology" for issue in result.remaining.issues
    )
    assert (workspace / "revised.docx").is_file()


def test_revise_endpoint_accepts_explicit_changes(workspace: Path) -> None:
    path = _save_doc(workspace, "正文包含 AI。")

    result = revise_word_endpoint(
        WordAuditReviseRequest(
            workspace_path=str(workspace),
            file_path=str(path),
            rulepack=_term_pack(),
            changes=[
                WordRevisionChangeRequest(
                    rule_id="content/terminology",
                    find="AI",
                    replace="人工智能",
                    comment="统一术语",
                )
            ],
            output_filename="explicit.docx",
        )
    )

    assert result.applied == 1
    assert result.changes[0].comment == "统一术语"
    assert (workspace / "explicit.docx").is_file()


def test_revise_endpoint_rejects_when_no_plan(workspace: Path) -> None:
    path = _save_doc(workspace, "没有问题文本。")

    with pytest.raises(OfficeParseError):
        revise_word_endpoint(
            WordAuditReviseRequest(
                workspace_path=str(workspace),
                file_path=str(path),
                rulepack=_term_pack(),
            )
        )


def test_revise_endpoint_rejects_size_and_escape(workspace: Path) -> None:
    path = _save_doc(workspace)

    with pytest.raises(OfficeSizeLimitError):
        revise_word_endpoint(
            WordAuditReviseRequest(
                workspace_path=str(workspace),
                file_path=str(path),
                rulepack=_term_pack(),
                changes=[WordRevisionChangeRequest(find="AI", replace="人工智能")],
                max_size_bytes=1024,
            )
        )
    with pytest.raises(OfficePathError):
        revise_word_endpoint(
            WordAuditReviseRequest(
                workspace_path=str(workspace),
                file_path="../outside.docx",
                rulepack=_term_pack(),
            )
        )
