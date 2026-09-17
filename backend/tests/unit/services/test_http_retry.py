"""Tests for the http_retry helper."""
from unittest.mock import patch
import pytest

from backend.services.http_retry import (
    compute_backoff_seconds,
    retry_on_status,
)


class FakeStatusError(Exception):
    def __init__(self, status, message=""):
        super().__init__(message)
        self.status_code = status


def test_compute_backoff_seconds_exponential():
    assert compute_backoff_seconds(1, base_delay=1.0) == 1.0
    assert compute_backoff_seconds(2, base_delay=1.0) == 2.0
    assert compute_backoff_seconds(3, base_delay=1.0) == 4.0
    assert compute_backoff_seconds(4, base_delay=1.0) == 8.0


def test_compute_backoff_seconds_caps_at_max():
    assert compute_backoff_seconds(10, base_delay=1.0, max_delay=10.0) == 10.0


def test_retry_on_status_succeeds_first_try():
    calls = []
    def fn():
        calls.append(1)
        return "ok"
    assert retry_on_status(fn, retry_statuses=(429,)) == "ok"
    assert len(calls) == 1


def test_retry_on_status_retries_then_succeeds():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise FakeStatusError(429, "rate limited")
        return "ok"

    with patch("backend.services.http_retry._time.sleep") as mock_sleep:
        result = retry_on_status(fn, retry_statuses=(429,), max_attempts=3, base_delay=0.1)
    assert result == "ok"
    assert len(calls) == 3
    assert mock_sleep.call_count == 2


def test_retry_on_status_exhausts_attempts():
    calls = []

    def fn():
        calls.append(1)
        raise FakeStatusError(429, "still rate limited")

    with patch("backend.services.http_retry._time.sleep"):
        with pytest.raises(FakeStatusError):
            retry_on_status(fn, retry_statuses=(429,), max_attempts=3, base_delay=0.1)
    assert len(calls) == 3


def test_retry_on_status_does_not_retry_non_matching():
    calls = []

    def fn():
        calls.append(1)
        raise FakeStatusError(500, "internal error")

    with pytest.raises(FakeStatusError):
        retry_on_status(fn, retry_statuses=(429,), max_attempts=3)
    assert len(calls) == 1
