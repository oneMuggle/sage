"""HTTP retry helper for Arena adapter.

Mirrors the retry pattern from backend/core/legacy/llm_client.py:69-96 but
exposes a small, dependency-free utility usable from any service layer.
"""
from __future__ import annotations

import logging
import time as _time
from typing import Callable, Iterable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY_S = 1.0
DEFAULT_MAX_DELAY_S = 30.0


def compute_backoff_seconds(
    attempt: int,
    *,
    base_delay: float = DEFAULT_BASE_DELAY_S,
    max_delay: float = DEFAULT_MAX_DELAY_S,
) -> float:
    """Exponential backoff: base_delay * 2^(attempt-1), capped at max_delay."""
    return min(base_delay * (2 ** (attempt - 1)), max_delay)


def retry_on_status(
    fn: Callable[[], T],
    *,
    retry_statuses: Iterable[int] = (429,),
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY_S,
    max_delay: float = DEFAULT_MAX_DELAY_S,
    retry_after_extractor: Optional[Callable[[T], Optional[int]]] = None,
) -> T:
    """Retry fn when it raises an error containing a matching status.

    The error is expected to be an exception with a .status_code or .status
    attribute (e.g. an httpx.HTTPStatusError or our CDPCommandError). 429
    responses are honored if retry_after_extractor returns seconds from
    the return value.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = fn()
            if retry_after_extractor is not None:
                retry_after = retry_after_extractor(result)
                if retry_after and attempt < max_attempts:
                    logger.info(
                        "retry_on_status attempt=%d honor retry_after=%ds",
                        attempt, retry_after,
                    )
                    _time.sleep(min(retry_after, max_delay))
                    continue
            return result
        except Exception as exc:
            last_exc = exc
            status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
            if status not in retry_statuses or attempt >= max_attempts:
                raise
            delay = compute_backoff_seconds(attempt, base_delay=base_delay, max_delay=max_delay)
            logger.warning(
                "retry_on_status attempt=%d/%d status=%s delay=%.1fs",
                attempt, max_attempts, status, delay,
            )
            _time.sleep(delay)
    raise last_exc  # pragma: no cover
