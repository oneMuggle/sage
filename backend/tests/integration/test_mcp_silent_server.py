"""HIGH-5 regression — a live-but-silent MCP server must not hang startup.

A real subprocess (tests/fixtures/mcp_mock_server.py with MOCK_HANG=1)
accepts the connection but never replies. Pre-fix, stdout.readline()
blocked forever so discover_all's executor join wedged
register_mcp_tools at app startup. Post-fix the read path is
deadline-bounded (daemon reader + queue), discovery fails within
timeout + margin, and the abandoned subprocess is killed.
"""

import sys
import time
from pathlib import Path

from backend.mcp.client import McpClient
from backend.mcp.config import validate_server_config
from backend.mcp.pool import McpServerPool

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "mcp_mock_server.py"

HANG_TIMEOUT_SECONDS = 2.0


class SpyClient(McpClient):
    """McpClient that remembers the Popen it spawned.

    stop() nulls the client's own _process reference, so to assert the
    subprocess is actually dead afterwards we must hold the Popen
    object separately.
    """

    def __init__(self, config, spawned):
        super().__init__(config)
        self._spawned = spawned

    def start(self):
        try:
            super().start()
        finally:
            self._spawned.append(self._process)


def test_silent_server_discovery_is_deadline_bounded_and_killed():
    spawned = []

    def factory(config):
        return SpyClient(config, spawned)

    config = validate_server_config(
        name="silent",
        command=sys.executable,
        args=(str(FIXTURE),),
        env={
            "MOCK_HANG": "1",
            "MOCK_HANG_MAX_SECS": "30",  # fixture self-destruct safety net
            "MOCK_SERVER_NAME": "silent",
        },
        timeout_seconds=HANG_TIMEOUT_SECONDS,
    )

    pool = McpServerPool(client_factory=factory)
    pool.sync_configs([config])
    try:
        start = time.monotonic()
        report = pool.discover_all()
        elapsed = time.monotonic() - start

        # Bounded: completes at the configured timeout, well inside the
        # timeout + 2s margin (the docstring promise is now true).
        assert elapsed < HANG_TIMEOUT_SECONDS + 2.0, f"discovery took {elapsed:.1f}s"

        (entry,) = report.servers
        assert entry.state == "failed"
        assert "timed out" in (entry.last_error or "")
        assert report.degraded
    finally:
        pool.shutdown_all()

    # The discarded client was stopped → subprocess killed (no orphan).
    assert len(spawned) == 1
    process = spawned[0]
    assert process is not None  # spawn succeeded; only the handshake hung
    deadline = time.monotonic() + 5.0
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process.poll() is not None, "silent server subprocess still alive"
