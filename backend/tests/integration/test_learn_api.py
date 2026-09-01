"""Integration tests for POST /learn endpoint.

Tests that the endpoint correctly enqueues a review event with
trigger_type="explicit_learn" and returns the expected response.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.legacy_routes import router


@pytest.fixture()
def client():
    """Create a TestClient with the legacy router mounted."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})


def _mock_session_exists(session_id: str):
    """Return a mock SessionRepository whose .get() returns a session
    for the given id (or None if session_id is ``"nonexistent"``)."""
    mock_repo = Mock()
    mock_session = Mock()
    mock_session.id = session_id

    def _get(sid: str):
        if sid == "nonexistent":
            return None
        return mock_session

    mock_repo.get.side_effect = _get
    return mock_repo


class TestLearnEndpoint:
    """POST /learn endpoint tests."""

    def test_learn_endpoint_enqueues_review(self, client):
        """POST /learn enqueues a review event with trigger_type=explicit_learn."""
        mock_queue = Mock()

        with patch(
            "backend.api.legacy_routes.get_review_queue",
            return_value=mock_queue,
        ), patch(
            "backend.api.legacy_routes.SessionRepository",
            return_value=_mock_session_exists("session_1"),
        ):
            response = client.post(
                "/learn",
                json={
                    "session_id": "session_1",
                    "prompt": "Learn from this conversation",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "queued"

            # Verify enqueue was called with correct arguments
            mock_queue.enqueue.assert_called_once()
            call_kwargs = mock_queue.enqueue.call_args.kwargs
            assert call_kwargs["trigger_type"] == "explicit_learn"
            assert call_kwargs["session_id"] == "session_1"
            assert "context" in call_kwargs
            context = call_kwargs["context"]
            assert context["user_prompt"] == "Learn from this conversation"

    def test_learn_endpoint_with_empty_prompt(self, client):
        """POST /learn works with an empty/missing prompt (optional field)."""
        mock_queue = Mock()

        with patch(
            "backend.api.legacy_routes.get_review_queue",
            return_value=mock_queue,
        ), patch(
            "backend.api.legacy_routes.SessionRepository",
            return_value=_mock_session_exists("session_2"),
        ):
            response = client.post(
                "/learn",
                json={"session_id": "session_2"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "queued"

            mock_queue.enqueue.assert_called_once()
            call_kwargs = mock_queue.enqueue.call_args.kwargs
            assert call_kwargs["trigger_type"] == "explicit_learn"
            assert call_kwargs["session_id"] == "session_2"
            context = call_kwargs["context"]
            assert context["user_prompt"] == ""

    def test_learn_endpoint_missing_session_id_returns_422(self, client):
        """POST /learn returns 422 when session_id is missing (required field)."""
        mock_queue = Mock()

        with patch(
            "backend.api.legacy_routes.get_review_queue",
            return_value=mock_queue,
        ):
            response = client.post(
                "/learn",
                json={"prompt": "Learn something"},
            )

            assert response.status_code == 422
            # Enqueue should NOT be called
            mock_queue.enqueue.assert_not_called()

    def test_learn_endpoint_returns_message(self, client):
        """POST /learn response includes a message field."""
        mock_queue = Mock()

        with patch(
            "backend.api.legacy_routes.get_review_queue",
            return_value=mock_queue,
        ), patch(
            "backend.api.legacy_routes.SessionRepository",
            return_value=_mock_session_exists("session_3"),
        ):
            response = client.post(
                "/learn",
                json={"session_id": "session_3", "prompt": "test"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "message" in data
            assert isinstance(data["message"], str)


# ------------------------------------------------------------------ #
# I-2 fix: session existence check
# ------------------------------------------------------------------ #


class TestLearnEndpointSessionValidation:
    """POST /learn must return 404 for non-existent sessions."""

    def test_learn_nonexistent_session_returns_404(self, client):
        """POST /learn returns 404 when session_id doesn't exist in DB."""
        mock_queue = Mock()

        with patch(
            "backend.api.legacy_routes.get_review_queue",
            return_value=mock_queue,
        ), patch(
            "backend.api.legacy_routes.SessionRepository",
            return_value=_mock_session_exists("nonexistent"),
        ):
            response = client.post(
                "/learn",
                json={"session_id": "nonexistent", "prompt": "test"},
            )

        assert response.status_code == 404
        # Enqueue must NOT be called for non-existent sessions
        mock_queue.enqueue.assert_not_called()

    def test_learn_404_response_includes_session_id(self, client):
        """404 detail message mentions the missing session_id."""
        with patch(
            "backend.api.legacy_routes.SessionRepository",
            return_value=_mock_session_exists("nonexistent"),
        ):
            response = client.post(
                "/learn",
                json={"session_id": "nonexistent"},
            )

        assert response.status_code == 404
        assert "nonexistent" in response.json()["detail"]
