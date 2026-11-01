"""Unit tests for semantic rule checks (M4a)."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from backend.office.errors import OfficeParseError
from backend.office.word_audit import audit_word_document
from backend.office.word_rulepack_builtin import builtin_rulepacks
from backend.office.word_rulepack_models import WordRulePack, WordRuleSpec


def _rule(
    rule_id: str,
    kind: str,
    params: dict = None,
    *,
    severity: str = "warning",
    fixable: bool = False,
) -> WordRuleSpec:
    return WordRuleSpec(
        id=rule_id,
        title=rule_id,
        category="content",
        severity=severity,
        kind=kind,
        params=params or {},
        fixable=fixable,
    )


def _pack(*rules: WordRuleSpec) -> WordRulePack:
    return WordRulePack(id="semantic", name="Semantic", rules=list(rules))


def _doc(path: Path, texts: list[str]) -> Path:
    document = Document()
    for text in texts:
        document.add_paragraph(text)
    document.save(str(path))
    return path


def test_date_format_flags_minority_style(tmp_path: Path) -> None:
    path = _doc(
        tmp_path / "dates.docx",
        [
            "会议日期 2026年10月31日。",
            "截止日期 2026年11月2日。",
            "生效日期 2026-11-01。",
        ],
    )

    result = audit_word_document(
        path,
        _pack(_rule("content/date_format", "content.date_format")),
        workspace_path=str(tmp_path),
    )

    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.rule_id == "content/date_format"
    assert issue.scope == "paragraph"
    assert issue.anchor is not None
    assert issue.anchor.paragraph_index == 2
    assert issue.expected == "YYYY年M月D日"
    assert "2026-11-01" in issue.message


def test_date_format_allowed_list(tmp_path: Path) -> None:
    path = _doc(
        tmp_path / "dates.docx",
        ["2026年10月31日。", "2026年11月2日。", "2026-11-01。"],
    )

    result = audit_word_document(
        path,
        _pack(
            _rule("content/date_format", "content.date_format", {"allowed": ["iso"]})
        ),
        workspace_path=str(tmp_path),
    )

    assert len(result.issues) == 2
    assert {issue.anchor.paragraph_index for issue in result.issues if issue.anchor} == {
        0,
        1,
    }


def test_terminology_flags_variants_with_anchor(tmp_path: Path) -> None:
    path = _doc(
        tmp_path / "terms.docx",
        ["我们采用 AI 方案。", "人工智能是研究领域。", "AI 与机器学习。"],
    )

    result = audit_word_document(
        path,
        _pack(
            _rule(
                "content/terminology",
                "content.terminology",
                {"pairs": [{"preferred": "人工智能", "variants": ["AI"]}]},
                fixable=True,
            )
        ),
        workspace_path=str(tmp_path),
    )

    assert len(result.issues) == 2
    assert all(issue.anchor is not None for issue in result.issues)
    assert {issue.anchor.paragraph_index for issue in result.issues if issue.anchor} == {
        0,
        2,
    }
    assert all(issue.expected == "人工智能" for issue in result.issues)
    assert all(issue.actual == "AI" for issue in result.issues)
    assert all(issue.fixable for issue in result.issues)


def test_required_phrases_missing_and_present(tmp_path: Path) -> None:
    missing = _doc(tmp_path / "missing.docx", ["正文内容。"])
    pack = _pack(
        _rule(
            "content/required_phrases",
            "content.required_phrases",
            {"phrases": ["特此通知"]},
        )
    )

    result = audit_word_document(missing, pack, workspace_path=str(tmp_path))
    assert len(result.issues) == 1
    assert result.issues[0].scope == "document"
    assert result.issues[0].anchor is None

    present = _doc(tmp_path / "present.docx", ["正文内容。", "特此通知。"])
    assert (
        audit_word_document(present, pack, workspace_path=str(tmp_path)).issues == []
    )


def test_semantic_rule_params_are_validated(tmp_path: Path) -> None:
    path = _doc(tmp_path / "doc.docx", ["2026-11-01"])

    with pytest.raises(OfficeParseError):
        audit_word_document(
            path,
            _pack(
                _rule(
                    "content/date_format",
                    "content.date_format",
                    {"allowed": ["unknown-style"]},
                )
            ),
            workspace_path=str(tmp_path),
        )
    with pytest.raises(OfficeParseError):
        audit_word_document(
            path,
            _pack(_rule("content/terminology", "content.terminology", {"pairs": []})),
            workspace_path=str(tmp_path),
        )
    with pytest.raises(OfficeParseError):
        audit_word_document(
            path,
            _pack(
                _rule(
                    "content/required_phrases",
                    "content.required_phrases",
                    {"phrases": []},
                )
            ),
            workspace_path=str(tmp_path),
        )


def test_builtin_general_quality_includes_date_format() -> None:
    general = next(pack for pack in builtin_rulepacks() if pack.id == "general-quality")
    assert any(rule.kind == "content.date_format" for rule in general.rules)
