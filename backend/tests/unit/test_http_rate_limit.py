"""per-host 最小间隔限速器（spec §5.5）。"""

import pytest

from backend.services.http_rate_limit import (
    DEFAULT_MIN_INTERVAL_S,
    LITERATURE_FLOOR_S,
    HttpRateLimiter,
    get_default_limiter,
    reset_default_limiter,
)

pytestmark = pytest.mark.unit


def test_first_request_is_immediate() -> None:
    limiter = HttpRateLimiter(min_interval_s=2.0)
    assert limiter.reserve("example.org", now=100.0) == 0.0


def test_second_request_within_interval_waits() -> None:
    limiter = HttpRateLimiter(min_interval_s=2.0)
    limiter.reserve("example.org", now=100.0)
    wait = limiter.reserve("example.org", now=101.0)
    assert wait == pytest.approx(1.0)


def test_request_after_interval_is_immediate() -> None:
    limiter = HttpRateLimiter(min_interval_s=2.0)
    limiter.reserve("example.org", now=100.0)
    assert limiter.reserve("example.org", now=102.0) == 0.0


def test_different_hosts_are_independent() -> None:
    limiter = HttpRateLimiter(min_interval_s=2.0)
    limiter.reserve("a.example", now=100.0)
    assert limiter.reserve("b.example", now=100.5) == 0.0


def test_floor_is_enforced_even_when_profile_writes_zero() -> None:
    """profile 即使写 min_interval_s=0 也不放行 —— 文献层下限 3 秒。"""
    limiter = HttpRateLimiter(min_interval_s=0.0, floor_s=LITERATURE_FLOOR_S)
    assert limiter.effective_interval_s == pytest.approx(LITERATURE_FLOOR_S)
    limiter.reserve("example.org", now=100.0)
    assert limiter.reserve("example.org", now=100.1) > 0.0


def test_profile_interval_above_floor_wins() -> None:
    limiter = HttpRateLimiter(min_interval_s=10.0, floor_s=LITERATURE_FLOOR_S)
    assert limiter.effective_interval_s == pytest.approx(10.0)


def test_generic_default_interval() -> None:
    assert DEFAULT_MIN_INTERVAL_S == 1.0
    assert LITERATURE_FLOOR_S == 3.0


def test_reset_clears_state() -> None:
    limiter = HttpRateLimiter(min_interval_s=5.0)
    limiter.reserve("example.org", now=100.0)
    limiter.reset()
    assert limiter.reserve("example.org", now=100.1) == 0.0


def test_default_limiter_is_shared_and_resettable() -> None:
    reset_default_limiter()
    first = get_default_limiter()
    assert get_default_limiter() is first
    reset_default_limiter()
    assert get_default_limiter() is not first
