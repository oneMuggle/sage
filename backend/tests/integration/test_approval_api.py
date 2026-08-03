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
    return TestClient(app)


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
# POST /skill-drafts/{id}/approve
# ------------------------------------------------------------------ #


class TestApproveSkillDraft:
    """POST /skill-drafts/{id}/approve endpoint tests."""

    def test_approve_writes_to_disk_and_updates_status(self, client):
        """Approving a draft writes SKILL.md and marks it approved."""
        draft = _make_draft("draft-42", "cool-skill", content="# Cool\n\nContent here.")

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
            response = client.post("/skill-drafts/draft-42/approve")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["skill_name"] == "cool-skill"

        # Verify write was called with draft name and content
        mock_loader.write.assert_called_once_with("cool-skill", "# Cool\n\nContent here.")

        # Verify status was updated
        mock_store.update_status.assert_called_once_with("draft-42", "approved")

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

    def test_approve_write_failure_returns_500(self, client):
        """If writing to disk fails, return 500 and don't update status."""
        draft = _make_draft("draft-99", "fail-skill", content="# Fail")

        mock_store = MagicMock()
        mock_store.get.return_value = draft

        mock_loader = MagicMock()
        mock_loader.write.side_effect = OSError("Disk full")

        with patch(
            "backend.api.legacy_routes.get_skill_draft_store",
            return_value=mock_store,
        ), patch(
            "backend.api.legacy_routes.get_skill_loader",
            return_value=mock_loader,
        ):
            response = client.post("/skill-drafts/draft-99/approve")

        assert response.status_code == 500
        # Status should NOT be updated when write fails
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
        assert "../bad" in detail or "Invalid skill name" in detail


# ------------------------------------------------------------------ #
# POST /skill-drafts/{id}/reject
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
