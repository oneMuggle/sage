"""Shared attachment resolver executor for chat routes.

Task 10 refactor: both legacy_routes and hex_routes use the SAME
ThreadPoolExecutor to resolve @-mention attachments, avoiding duplicate
executors and ensuring consistent resource management.

The executor runs attachment_resolver.process() off the event loop
(since it does synchronous I/O: file reads + LLM calls for digest).
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures

from backend.chat import attachment_resolver

# Shared executor for attachment resolution across all chat routes.
# max_workers=4 balances concurrency with resource usage (attachment
# resolution is I/O-bound but involves LLM calls which can be slow).
ATTACHMENT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="attachment-resolver",
)

# pytest session teardown triggers ResourceWarning if ThreadPoolExecutor
# is not explicitly closed; register atexit handler to shut it down.
# wait=False means don't wait for in-flight tasks (shutdown hook, not
# graceful shutdown — tasks will be interrupted if still running).
atexit.register(ATTACHMENT_EXECUTOR.shutdown, wait=False)


async def resolve_attachments(text: str, workspace_path: str) -> str:
    """Resolve @-mention attachments in text and return formatted block.

    This async wrapper runs the synchronous attachment_resolver.process()
    in a thread pool executor to avoid blocking the event loop.

    Args:
        text: User message containing @-mentions (e.g., "see @file.md")
        workspace_path: Root path for resolving relative file references

    Returns:
        Formatted attachment block (XML-ish string) or empty string if
        no mentions resolved successfully.
    """
    return await asyncio.get_running_loop().run_in_executor(
        ATTACHMENT_EXECUTOR,
        attachment_resolver.process,
        text,
        workspace_path,
    )
