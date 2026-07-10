"""Tests for common API envelope schemas (pydantic 2.x compatible)."""

from backend.schemas.common import ApiError, ApiResponse


def test_api_error_default_success_is_false():
    """ApiError.success must default to False."""
    err = ApiError(error="something failed")
    assert err.success is False
    assert err.error == "something failed"
    assert err.code is None
    assert err.details is None


def test_api_error_with_code_and_details():
    """ApiError accepts code and details for structured errors."""
    err = ApiError(error="not found", code="NOT_FOUND", details={"id": "x"})
    assert err.code == "NOT_FOUND"
    assert err.details == {"id": "x"}


def test_api_response_success_carries_data():
    """ApiResponse success=true carries data payload."""
    resp = ApiResponse(success=True, data={"id": "light"})
    assert resp.success is True
    assert resp.data == {"id": "light"}


def test_api_response_failure_carries_error():
    """ApiResponse success=false carries error message."""
    resp = ApiResponse(success=False, error="boom", code="BOOM")
    assert resp.success is False
    assert resp.error == "boom"
    assert resp.code == "BOOM"


def test_api_response_data_optional():
    """ApiResponse.data is optional (None by default)."""
    resp = ApiResponse(success=True)
    assert resp.data is None
