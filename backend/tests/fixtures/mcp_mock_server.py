#!/usr/bin/env python
"""Tiny MCP JSON-RPC stdio mock server for integration fault drills.

Protocol: newline-delimited JSON-RPC 2.0 over stdin/stdout.

Supported methods:
- ``initialize``   → {protocolVersion, capabilities, serverInfo}
- ``tools/list``   → one tool named ``$MOCK_TOOL_NAME`` (default "echo")
- ``tools/call``   → echoes {"tool": ..., "args": ...} as text content

Fault injection:
- ``$MOCK_FAIL_MARKER`` pointing to an existing file → exit 1
  immediately (server refuses to start; makes reconnect fail
  deterministically).
- ``$MOCK_HANG`` set → the server stays alive but NEVER responds
  (live-but-silent; exercises the client's deadline-bounded read
  path). It self-terminates after ``$MOCK_HANG_MAX_SECS`` (default 30)
  so a failed test cannot leave a lingering process.
"""

import json
import os
import sys
import time


def _send(message: dict) -> None:
    """Write one JSON-RPC message to stdout (the stdio transport)."""
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
    fail_marker = os.environ.get("MOCK_FAIL_MARKER")
    if fail_marker and os.path.exists(fail_marker):
        sys.stderr.write("mock server refusing to start (marker present)\n")
        sys.stderr.flush()
        sys.exit(1)

    if os.environ.get("MOCK_HANG"):
        sys.stderr.write("mock server hanging (accepts connection, never replies)\n")
        sys.stderr.flush()
        # Self-destruct so a failed test cannot leak this process.
        deadline = time.monotonic() + float(os.environ.get("MOCK_HANG_MAX_SECS", "30"))
        while time.monotonic() < deadline:
            time.sleep(0.1)
        sys.exit(0)

    tool_name = os.environ.get("MOCK_TOOL_NAME", "echo")
    server_name = os.environ.get("MOCK_SERVER_NAME", "mock")

    for raw in sys.stdin:
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            msg = json.loads(stripped)
        except json.JSONDecodeError:
            continue

        # notifications (no id) get no response
        if "id" not in msg:
            continue

        method = msg.get("method")
        params = msg.get("params", {})
        msg_id = msg["id"]

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": server_name, "version": "0.0.1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": tool_name,
                        "description": "echo arguments back as text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                    }
                ]
            }
        elif method == "tools/call":
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"server": server_name, "tool": params.get("name"), "args": params.get("arguments", {})},
                            ensure_ascii=False,
                        ),
                    }
                ],
                "isError": False,
            }
        else:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": "method not found"},
                }
            )
            continue

        _send({"jsonrpc": "2.0", "id": msg_id, "result": result})


if __name__ == "__main__":
    main()
