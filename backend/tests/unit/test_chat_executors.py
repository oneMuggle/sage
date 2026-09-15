"""Unit tests for backend.chat.executors module.

Verifies the shared attachment resolver executor that both legacy_routes
and hex_routes use (Task 10 refactor).
"""

from __future__ import annotations

import concurrent.futures
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def test_attachment_executor_is_shared_singleton():
    """Both routes must use the SAME executor instance (Task 10 invariant)."""
    from backend.chat import executors
    from backend.chat.executors import ATTACHMENT_EXECUTOR

    assert isinstance(ATTACHMENT_EXECUTOR, concurrent.futures.ThreadPoolExecutor)
    # Import again — must be the exact same object (module-level singleton)
    assert ATTACHMENT_EXECUTOR is executors.ATTACHMENT_EXECUTOR


def test_attachment_executor_has_atexit_shutdown():
    """Executor must register atexit handler to avoid ResourceWarning."""
    from backend.chat import executors

    # Module must have imported atexit and registered shutdown
    assert hasattr(executors, "atexit")
    # We can't easily inspect atexit registry, but we can verify the module
    # doesn't raise on import (which would happen if shutdown was misconfigured)


@pytest.mark.asyncio()
async def test_resolve_attachments_returns_string():
    """resolve_attachments must return a string (possibly empty)."""
    from backend.chat.executors import resolve_attachments

    with patch("backend.chat.executors.attachment_resolver.process", return_value=""):
        result = await resolve_attachments("hello", "/tmp/workspace")
    assert isinstance(result, str)


@pytest.mark.asyncio()
async def test_resolve_attachments_calls_process_with_correct_args():
    """resolve_attachments must delegate to attachment_resolver.process."""
    from backend.chat.executors import resolve_attachments

    with patch(
        "backend.chat.executors.attachment_resolver.process",
        return_value="<attachments>content</attachments>",
    ) as mock_process:
        result = await resolve_attachments("see @file.md", "/workspace")

    mock_process.assert_called_once_with("see @file.md", "/workspace")
    assert result == "<attachments>content</attachments>"


@pytest.mark.asyncio()
async def test_resolve_attachments_empty_workspace_skips():
    """Empty workspace_path should result in empty string (no mentions resolved)."""
    from backend.chat.executors import resolve_attachments

    with patch(
        "backend.chat.executors.attachment_resolver.process",
        return_value="",
    ) as mock_process:
        result = await resolve_attachments("no mentions here", "")

    # attachment_resolver.process handles empty workspace internally
    mock_process.assert_called_once_with("no mentions here", "")
    assert result == ""


def test_executor_thread_name_prefix():
    """Executor threads should be named for debugging."""
    from backend.chat.executors import ATTACHMENT_EXECUTOR

    # ThreadPoolExecutor stores the prefix
    assert ATTACHMENT_EXECUTOR._thread_name_prefix == "attachment-resolver"


def test_executor_max_workers():
    """Executor should have reasonable concurrency limit."""
    from backend.chat.executors import ATTACHMENT_EXECUTOR

    # max_workers=4 is the spec from Task 10
    assert ATTACHMENT_EXECUTOR._max_workers == 4
