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
    return TestClient(app)


class TestLearnEndpoint:
    """POST /learn endpoint tests."""

    def test_learn_endpoint_enqueues_review(self, client):
        """POST /learn enqueues a review event with trigger_type=explicit_learn."""
        mock_queue = Mock()

        with patch(
            "backend.api.legacy_routes.get_review_queue",
            return_value=mock_queue,
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
        ):
            response = client.post(
                "/learn",
                json={"session_id": "session_3", "prompt": "test"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "message" in data
            assert isinstance(data["message"], str)
