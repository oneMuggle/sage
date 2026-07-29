"""M3 — integration fault drill with REAL stdio MCP subprocesses.

Two genuine Python subprocess mock servers (tests/fixtures/
mcp_mock_server.py speaking newline-delimited JSON-RPC) are discovered
by the real McpClient through the pool. One server is killed
mid-session; the drill asserts:

- the survivor keeps answering tools/call,
- the killed server's tool fails with a clean per-server error,
- status shows one FAILED + one READY (degraded report),
- reconnection after the server is restarted brings it back to READY.
"""

import sys
import time
from pathlib import Path

import pytest

from backend.mcp.config import validate_server_config
from backend.mcp.pool import McpServerPool
from backend.mcp.tool import McpTool

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "mcp_mock_server.py"


def _cfg(name: str, marker: Path, required: bool = False):
    return validate_server_config(
        name=name,
        command=sys.executable,
        args=(str(FIXTURE),),
        env={
            "MOCK_FAIL_MARKER": str(marker),
            "MOCK_TOOL_NAME": "echo",
            "MOCK_SERVER_NAME": name,
        },
        timeout_seconds=10,
        required=required,
    )


@pytest.fixture()
def drill(tmp_path):
    """Pool + two live stdio servers (alpha, bravo) + kill marker path."""
    marker = tmp_path / "kill.marker"
    pool = McpServerPool(rediscovery_cooldown=1.0)
    pool.sync_configs([_cfg("alpha", marker), _cfg("bravo", marker)])
    report = pool.discover_all()
    states = {s.name: s.state for s in report.servers}
    assert states == {"alpha": "ready", "bravo": "ready"}, states

    yield pool, marker

    pool.shutdown_all()


def _kill(pool, name):
    """Terminate a server's subprocess and wait until it registers dead."""
    record = pool.get_record(name)
    record.client._process.terminate()
    deadline = time.time() + 5
    while time.time() < deadline:
        if not record.client.is_running:
            return
        time.sleep(0.02)
    raise AssertionError(f"server {name} did not die in time")


def _tool(pool, server):
    record = pool.get_record(server)
    return McpTool(pool, server, record.tool_specs[0])


class TestFaultDrill:
    def test_both_servers_answer_independently(self, drill):
        pool, _ = drill
        for server in ("alpha", "bravo"):
            result = _tool(pool, server).execute(text="ping")
            assert result.success, result.error
            assert f'"server": "{server}"' in result.content

    def test_kill_one_isolates_failure(self, drill):
        pool, marker = drill
        marker.write_text("kill alpha", encoding="utf-8")  # make restart fail too
        _kill(pool, "alpha")

        # killed server: clean per-server error, no crash
        dead_result = _tool(pool, "alpha").execute(text="x")
        assert dead_result.success is False
        assert "不可用" in dead_result.error

        # survivor keeps working
        alive_result = _tool(pool, "bravo").execute(text="y")
        assert alive_result.success
        assert '"server": "bravo"' in alive_result.content

    def test_status_report_degraded_after_kill(self, drill):
        pool, marker = drill
        marker.write_text("kill", encoding="utf-8")
        _kill(pool, "alpha")
        # trigger the failure path so state flips READY → FAILED
        _tool(pool, "alpha").execute(text="x")

        report = pool.status_report()
        states = {s.name: s.state for s in report.servers}
        assert states == {"alpha": "failed", "bravo": "ready"}
        assert report.degraded
        assert not report.all_ready
        assert not report.failed_required  # neither server is required

    def test_reconnect_after_restart(self, drill):
        pool, marker = drill
        marker.write_text("kill", encoding="utf-8")
        _kill(pool, "alpha")
        failed = _tool(pool, "alpha").execute(text="x")
        assert "不可用" in failed.error
        assert pool.get_record("alpha").state.value == "failed"

        # server "fixed": remove marker and re-discover
        marker.unlink()
        pool.discover_one("alpha")

        assert pool.get_record("alpha").state.value == "ready"
        result = _tool(pool, "alpha").execute(text="back")
        assert result.success
        assert '"server": "alpha"' in result.content

    def test_required_server_failure_flagged(self, tmp_path):
        marker = tmp_path / "kill.marker"
        pool = McpServerPool(rediscovery_cooldown=60.0)
        pool.sync_configs([_cfg("alpha", marker, required=True)])
        pool.discover_all()
        marker.write_text("kill", encoding="utf-8")
        _kill(pool, "alpha")
        _tool(pool, "alpha").execute(text="x")

        report = pool.status_report()
        assert report.failed_required
        pool.shutdown_all()
