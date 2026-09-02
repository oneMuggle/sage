"""Integration tests for approval queue API endpoints.

Tests for Task 10: listing, approving, and rejecting skill drafts
via REST API endpoints.

- GET /skill-drafts — list drafts (optional status filter)
- POST /skill-drafts/{id}/approve — approve + write to disk
- POST /skill-drafts/{id}/reject — reject draft
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.legacy_routes import router
from backend.skills.review_service import SkillDraft


@pytest.fixture()
def client():
    """Create a TestClient with the legacy router mounted."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})


def _make_draft(
    draft_id: str = "draft-1",
    name: str = "test-skill",
    content: str = "# Test Skill\n\nSome content.",
    status: str = "pending",
) -> SkillDraft:
    """Helper to build a SkillDraft for tests."""
    return SkillDraft(
        id=draft_id,
        name=name,
        description="A test skill",
        when_to_use="when testing",
        content=content,
        trigger_type="complex_turn",
        source_session_id="session-abc",
        source_context={"messages": []},
        status=status,
        created_at=1700000000000,
    )


# ------------------------------------------------------------------ #
# GET /skill-drafts
# ------------------------------------------------------------------ #


class TestListSkillDrafts:
    """GET /skill-drafts endpoint tests."""

    def test_list_skill_drafts_default_status(self, client):
        """GET /skill-drafts returns pending drafts by default."""
        draft_a = _make_draft("id-1", "skill-a")
        draft_b = _make_draft("id-2", "skill-b")

        mock_store = MagicMock()
        mock_store.list.return_value = [draft_a, draft_b]

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ):
            response = client.get("/skill-drafts")

        assert response.status_code == 200
        data = response.json()
        assert "drafts" in data
        drafts = data["drafts"]
        assert len(drafts) == 2
        # list() should be called with default status="pending"
        mock_store.list.assert_called_once_with(status="pending")

    def test_list_skill_drafts_with_status_filter(self, client):
        """GET /skill-drafts?status=approved passes status through."""
        draft = _make_draft("id-1", "skill-a", status="approved")

        mock_store = MagicMock()
        mock_store.list.return_value = [draft]

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ):
            response = client.get("/skill-drafts?status=approved")

        assert response.status_code == 200
        data = response.json()
        assert len(data["drafts"]) == 1
        mock_store.list.assert_called_once_with(status="approved")

    def test_list_skill_drafts_empty(self, client):
        """GET /skill-drafts returns empty list when no drafts."""
        mock_store = MagicMock()
        mock_store.list.return_value = []

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ):
            response = client.get("/skill-drafts")

        assert response.status_code == 200
        assert response.json()["drafts"] == []

    def test_list_skill_drafts_serializes_fields(self, client):
        """Each draft in response includes key fields."""
        draft = _make_draft("id-xyz", "my-skill", content="# Hello")

        mock_store = MagicMock()
        mock_store.list.return_value = [draft]

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ):
            response = client.get("/skill-drafts")

        assert response.status_code == 200
        drafts = response.json()["drafts"]
        assert len(drafts) == 1
        d = drafts[0]
        assert d["id"] == "id-xyz"
        assert d["name"] == "my-skill"
        assert d["content"] == "# Hello"
        assert d["status"] == "pending"


# ------------------------------------------------------------------ #
# POST /skill-drafts/{id}/approve  # noqa: ERA001
# ------------------------------------------------------------------ #


class TestApproveSkillDraft:
    """POST /skill-drafts/{id}/approve endpoint tests."""

    def test_approve_writes_to_disk_and_updates_status(self, client):
        """Approving a new draft writes SKILL.md and marks it approved."""
        content = "---\nname: cool-skill\ndescription: Use this skill for testing.\n---\n# Cool\n\nContent here."
        draft = _make_draft("draft-42", "cool-skill", content=content)

        mock_store = MagicMock()
        mock_store.get.return_value = draft

        mock_loader = MagicMock()
        mock_port = MagicMock()
        mock_port.rescan_skill_mds.return_value = {
            "loaded": [{"name": "cool-skill"}], "skipped": [], "total_loaded": 1
        }

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ), patch(
            "backend.api.legacy_routes.get_skill_loader",
            return_value=mock_loader,
        ), patch(
            "backend.api.legacy_routes._get_skill_adapter",
            return_value=mock_port,
        ):
            response = client.post("/skill-drafts/draft-42/approve")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["skill_name"] == "cool-skill"
        assert data["reloaded"] is True
        mock_port.rescan_skill_mds.assert_called_once_with()

        # Approval must explicitly request the non-overwriting behavior.
        mock_loader.write.assert_called_once_with("cool-skill", content, overwrite=False)

        mock_store.update_status.assert_called_once_with("draft-42", "approved")

    def test_approve_existing_skill_returns_409_without_overwriting(self, client):
        """An existing skill blocks approval and leaves the draft pending."""
        content = "---\nname: cool-skill\ndescription: Use this skill for testing.\n---\n# New"
        draft = _make_draft("draft-existing", "cool-skill", content=content)

        mock_store = MagicMock()
        mock_store.get.return_value = draft
        mock_loader = MagicMock()
        mock_loader.write.side_effect = FileExistsError("/skills/cool-skill/SKILL.md")
        mock_port = MagicMock()

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ), patch(
            "backend.api.legacy_routes.get_skill_loader",
            return_value=mock_loader,
        ), patch(
            "backend.api.legacy_routes._get_skill_adapter",
            return_value=mock_port,
        ):
            response = client.post("/skill-drafts/draft-existing/approve")

        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "skill_already_exists",
            "message": "Skill already exists",
        }
        mock_loader.write.assert_called_once_with("cool-skill", content, overwrite=False)
        mock_store.update_status.assert_not_called()
        mock_port.rescan_skill_mds.assert_not_called()

    def test_approve_invalid_content_returns_400_without_side_effects(self, client):
        """Malformed SKILL.md content is rejected before writing or approval."""
        draft = _make_draft("draft-invalid-content", "bad-skill", content="# Missing frontmatter")

        mock_store = MagicMock()
        mock_store.get.return_value = draft
        mock_loader = MagicMock()

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ), patch(
            "backend.api.legacy_routes.get_skill_loader",
            return_value=mock_loader,
        ):
            response = client.post("/skill-drafts/draft-invalid-content/approve")

        assert response.status_code == 400
        mock_loader.write.assert_not_called()
        mock_store.update_status.assert_not_called()

    def test_approve_mismatched_frontmatter_name_returns_400_without_side_effects(self, client):
        """Frontmatter name must match the draft name."""
        content = "---\nname: another-skill\ndescription: Use this skill for testing.\n---\n# Skill"
        draft = _make_draft("draft-mismatched-name", "expected-skill", content=content)

        mock_store = MagicMock()
        mock_store.get.return_value = draft
        mock_loader = MagicMock()

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ), patch(
            "backend.api.legacy_routes.get_skill_loader",
            return_value=mock_loader,
        ):
            response = client.post("/skill-drafts/draft-mismatched-name/approve")

        assert response.status_code == 400
        mock_loader.write.assert_not_called()
        mock_store.update_status.assert_not_called()

    def test_approve_not_found_returns_404(self, client):
        """Approving a non-existent draft returns 404."""
        mock_store = MagicMock()
        mock_store.get.return_value = None

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ):
            response = client.post("/skill-drafts/missing-id/approve")

        assert response.status_code == 404

    def test_approve_write_failure_does_not_expose_filesystem_details(self, client):
        """Filesystem diagnostics stay out of the client-facing error response."""
        content = "---\nname: fail-skill\ndescription: Use this skill for testing.\n---\n# Fail"
        draft = _make_draft("draft-os-error", "fail-skill", content=content)
        absolute_path = "/home/fz/private/skills/fail-skill/SKILL.md"
        raw_error = "[Errno 13] Permission denied: " + absolute_path

        mock_store = MagicMock()
        mock_store.get.return_value = draft
        mock_loader = MagicMock()
        mock_loader.write.side_effect = OSError(raw_error)

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ), patch(
            "backend.api.legacy_routes.get_skill_loader",
            return_value=mock_loader,
        ):
            response = client.post("/skill-drafts/draft-os-error/approve")

        assert response.status_code == 500
        assert response.json()["detail"] == {
            "code": "skill_write_failed",
            "message": "Failed to write skill",
        }
        assert absolute_path not in response.text
        assert raw_error not in response.text
        mock_store.update_status.assert_not_called()


# ------------------------------------------------------------------ #
# I-1 fix: invalid skill name → 400 (not 500)
# ------------------------------------------------------------------ #


class TestApproveSkillDraftNameValidation:
    """POST /skill-drafts/{id}/approve must return 400 for invalid skill names.

    Invalid names include path traversal sequences (``..``), directory
    separators (``/``, ``\\``), and empty strings. These would otherwise
    surface as opaque 500 errors from the OS / skill loader.
    """

    def _approve_with_name(self, client, name: str):
        """Helper: set up mocks for a draft with the given name, call approve."""
        draft = _make_draft("draft-xyz", name=name, content="# X")

        mock_store = MagicMock()
        mock_store.get.return_value = draft

        mock_loader = MagicMock()

        return client.post(
            "/skill-drafts/draft-xyz/approve",
            # patch only the stores; ReviewService._validate_skill_name is
            # the real static method — we want to exercise it.
            headers={},
            # We need to patch at call time, so we do it inside this helper.
        ), mock_store, mock_loader

    def test_approve_path_traversal_returns_400(self, client):
        """Skill name containing '..' is rejected with 400."""
        draft = _make_draft("draft-evil", name="../etc/passwd", content="# Evil")

        mock_store = MagicMock()
        mock_store.get.return_value = draft

        mock_loader = MagicMock()

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ), patch(
            "backend.api.legacy_routes.get_skill_loader",
            return_value=mock_loader,
        ):
            response = client.post("/skill-drafts/draft-evil/approve")

        assert response.status_code == 400
        # The draft must NOT be approved or written when name is invalid
        mock_loader.write.assert_not_called()
        mock_store.update_status.assert_not_called()

    def test_approve_directory_separator_returns_400(self, client):
        """Skill name containing '/' or '\\' is rejected with 400."""
        draft = _make_draft("draft-slash", name="foo/bar", content="# Slash")

        mock_store = MagicMock()
        mock_store.get.return_value = draft

        mock_loader = MagicMock()

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ), patch(
            "backend.api.legacy_routes.get_skill_loader",
            return_value=mock_loader,
        ):
            response = client.post("/skill-drafts/draft-slash/approve")

        assert response.status_code == 400
        mock_loader.write.assert_not_called()
        mock_store.update_status.assert_not_called()

    def test_approve_empty_name_returns_400(self, client):
        """Empty skill name is rejected with 400."""
        draft = _make_draft("draft-empty", name="", content="# Empty")

        mock_store = MagicMock()
        mock_store.get.return_value = draft

        mock_loader = MagicMock()

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ), patch(
            "backend.api.legacy_routes.get_skill_loader",
            return_value=mock_loader,
        ):
            response = client.post("/skill-drafts/draft-empty/approve")

        assert response.status_code == 400
        mock_loader.write.assert_not_called()
        mock_store.update_status.assert_not_called()

    def test_approve_invalid_name_detail_mentions_name(self, client):
        """400 response detail mentions the invalid name for debugging."""
        draft = _make_draft("draft-x", name="../bad", content="# X")

        mock_store = MagicMock()
        mock_store.get.return_value = draft

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ), patch(
            "backend.api.legacy_routes.get_skill_loader",
            return_value=MagicMock(),
        ):
            response = client.post("/skill-drafts/draft-x/approve")

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail == {
            "code": "invalid_skill_name",
            "message": "Invalid skill name",
        }


# ------------------------------------------------------------------ #
# POST /skill-drafts/{id}/reject  # noqa: ERA001
# ------------------------------------------------------------------ #


class TestRejectSkillDraft:
    """POST /skill-drafts/{id}/reject endpoint tests."""

    def test_reject_updates_status(self, client):
        """Rejecting a draft marks it as rejected."""
        mock_store = MagicMock()

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ):
            response = client.post("/skill-drafts/draft-7/reject")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"

        mock_store.update_status.assert_called_once_with("draft-7", "rejected")

    def test_reject_returns_draft_id(self, client):
        """Reject response includes the draft id."""
        mock_store = MagicMock()

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ):
            response = client.post("/skill-drafts/draft-abc/reject")

        assert response.status_code == 200
        data = response.json()
        assert "draft_id" in data
        assert data["draft_id"] == "draft-abc"

    def test_reject_not_found_returns_404(self, client):
        """Rejecting a non-existent draft returns 404."""
        mock_store = MagicMock()
        mock_store.get.return_value = None

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ):
            response = client.post("/skill-drafts/missing-id/reject")

        assert response.status_code == 404
