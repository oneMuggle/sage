"""Unit tests for SKILL.md approval validation."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.legacy_routes import (
    _validate_skill_draft_content,
    approve_skill_draft,
)

VALID_CONTENT = "---\nname: test-skill\ndescription: Use this skill for testing.\n---\n# Test"


def test_accepts_valid_skill_md_with_matching_name() -> None:
    _validate_skill_draft_content(VALID_CONTENT, "test-skill")


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("# no frontmatter", "frontmatter"),
        ("---\nname: test-skill\n---\n# Test", "description"),
        (
            "---\nname: other-skill\ndescription: Use this skill.\n---\n# Test",
            "does not match draft name",
        ),
    ],
)
def test_rejects_invalid_skill_md_content(content: str, expected_message: str) -> None:
    with pytest.raises(ValueError, match=expected_message):
        _validate_skill_draft_content(content, "test-skill")


def test_rejects_non_string_content() -> None:
    with pytest.raises(ValueError, match="UTF-8 string"):
        _validate_skill_draft_content(None, "test-skill")


def test_approve_write_oserror_returns_stable_detail_without_raw_error() -> None:
    """The approval route must not expose filesystem exception details."""
    absolute_path = "/home/fz/private/skills/fail-skill/SKILL.md"
    raw_error = "[Errno 13] Permission denied: " + absolute_path
    draft = SimpleNamespace(id="draft-os-error", name="test-skill", content=VALID_CONTENT)
    store = MagicMock()
    store.get.return_value = draft
    loader = MagicMock()
    loader.write.side_effect = OSError(raw_error)

    with patch("backend.api.legacy_routes.get_skill_draft_store", return_value=store), patch(
        "backend.api.legacy_routes.get_skill_loader", return_value=loader
    ), pytest.raises(HTTPException) as raised:
        approve_skill_draft("draft-os-error")

    exception = raised.value
    assert getattr(exception, "status_code", None) == 500
    assert exception.detail == {
        "code": "skill_write_failed",
        "message": "Failed to write skill",
    }
    assert absolute_path not in str(exception.detail)
    assert raw_error not in str(exception.detail)
    store.update_status.assert_not_called()
