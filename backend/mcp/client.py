"""
Synchronous MCP client using subprocess + JSON-RPC 2.0 over stdio.

Communicates with MCP servers (like drawio-mcp-server) via stdin/stdout.
Implements the MCP handshake (initialize -> initialized -> tools/list -> tools/call).

M3 hardening: the stdout reader lives on a daemon thread feeding a
queue, so :meth:`McpClient._read_response` is bounded by a real
deadline (``queue.get(timeout=remaining)``). A live-but-silent server
can no longer wedge a blocking ``readline()`` forever and hang pool
discovery / app startup — the request fails at exactly
``timeout_seconds`` and the caller's ``stop()`` kills the process,
which unblocks the daemon reader via EOF. Windows-safe (no ``select``
on pipes).
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

from backend.mcp.config import McpServerConfig

logger = logging.getLogger(__name__)

#: Sentinel posted by the stdout reader thread on EOF (server exited or
#: closed its stdout). Distinct from any real line of bytes.
_STDOUT_EOF = object()


class McpClientError(Exception):
    """Raised when MCP communication fails."""


class McpClient:
    """
    Synchronous MCP client that manages a single MCP server subprocess.

    Usage:
        client = McpClient(config)
        client.start()
        tools = client.list_tools()
        result = client.call_tool("render_diagram", {"xml": "..."})
        client.stop()
    """

    def __init__(self, config: McpServerConfig):
        self._config = config
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._initialized = False
        self._stderr_lines: List[str] = []
        self._stderr_thread: Optional[threading.Thread] = None
        self._stdout_queue: Optional[queue.Queue] = None
        self._stdout_thread: Optional[threading.Thread] = None
        # M3: per-server response timeout from config (previously a
        # hardcoded 60s). Falls back to 60s for configs without the field.
        self._timeout = float(getattr(config, "timeout_seconds", 60.0) or 60.0)

    @property
    def server_name(self) -> str:
        return self._config.name

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """Start the MCP server subprocess and perform the initialize handshake."""
        if self.is_running:
            return

        import os

        env = {**dict(os.environ), **self._config.env}

        try:
            self._process = subprocess.Popen(
                [self._config.command, *self._config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                bufsize=0,  # unbuffered
            )
        except FileNotFoundError:
            raise McpClientError(
                f"Command not found: {self._config.command}. "
                f"Is {self._config.command} installed?"
            )
        except OSError as exc:
            raise McpClientError(f"Failed to start MCP server: {exc}")

        # Start stderr reader thread
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()

        # Stdout reader thread + queue: the request path must stay
        # deadline-bounded even if the server goes silent — a blocking
        # readline() there would hang forever (no select() on Windows
        # pipes, so a daemon thread + queue is the portable fix).
        self._stdout_queue = queue.Queue()
        self._stdout_thread = threading.Thread(target=self._read_stdout_lines, daemon=True)
        self._stdout_thread.start()

        logger.info(
            f"[MCP:{self._config.name}] Started: {self._config.command} {' '.join(self._config.args)}"
        )

        # Perform MCP handshake
        self._initialize()

    def _read_stdout_lines(self) -> None:
        """Feed stdout lines to the response queue until EOF/error.

        Daemon-threaded: the only way out is EOF (stop() kills the
        process, closing the pipe). Callers never join this thread —
        they kill the process instead, which releases the readline().
        """
        assert self._process is not None
        assert self._process.stdout is not None
        assert self._stdout_queue is not None
        try:
            while True:
                line = self._process.stdout.readline()
                if not line:
                    break
                self._stdout_queue.put(line)
        except (ValueError, OSError):
            pass  # pipe closed under us (stop() racing) — treat as EOF
        finally:
            self._stdout_queue.put(_STDOUT_EOF)

    def _read_stderr(self) -> None:
        """Read stderr from the subprocess in a background thread."""
        assert self._process is not None
        assert self._process.stderr is not None
        try:
            for line in self._process.stderr:
                text = line.decode("utf-8", errors="replace").rstrip()
                self._stderr_lines.append(text)
                if text:
                    logger.debug(f"[MCP:{self._config.name}] {text}")
        except (ValueError, OSError):
            pass

    def _initialize(self) -> None:
        """Perform the MCP initialize handshake."""
        # Send initialize request
        result = self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "sage",
                    "version": "0.1.0",
                },
            },
        )
        logger.info(f"[MCP:{self._config.name}] Server initialized: {result.get('serverInfo', {})}")

        # Send initialized notification
        self._send_notification("notifications/initialized", {})
        self._initialized = True

    def stop(self) -> None:
        """Stop the MCP server subprocess (terminate → kill → reap).

        After kill() the process is waited on: an unreaped kill leaves
        a zombie until this Python process exits. Killing also closes
        the child's stdout, which unblocks the daemon reader thread
        (it posts EOF and terminates).
        """
        if self._process:
            try:
                self._process.stdin.close()  # type: ignore[union-attr]
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                with contextlib.suppress(Exception):
                    self._process.kill()
                with contextlib.suppress(Exception):
                    self._process.wait(timeout=5)
            finally:
                self._process = None
                self._initialized = False
            logger.info(f"[MCP:{self._config.name}] Stopped")

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        List available tools from the MCP server.

        Returns list of tool specs:
        [{"name": str, "description": str, "inputSchema": dict}, ...]
        """
        self._ensure_started()
        result = self._send_request("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a tool on the MCP server.

        Returns the full MCP response:
        {"content": [...], "isError": bool, "metadata": {...}}
        """
        self._ensure_started()
        return self._send_request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )

    def _ensure_started(self) -> None:
        if not self.is_running:
            raise McpClientError(f"MCP server '{self._config.name}' is not running")
        if not self._initialized:
            raise McpClientError(f"MCP server '{self._config.name}' is not initialized")

    def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON-RPC request and wait for the response."""
        with self._lock:
            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            }
            self._write_message(request)
            response = self._read_response(request["id"])

        if "error" in response:
            err = response["error"]
            raise McpClientError(
                f"MCP error {err.get('code', '?')}: {err.get('message', 'unknown')}"
            )
        return response.get("result", {})

    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._write_message(notification)

    def _write_message(self, message: Dict[str, Any]) -> None:
        """Write a JSON-RPC message to the server's stdin."""
        assert self._process is not None
        assert self._process.stdin is not None
        data = json.dumps(message) + "\n"
        try:
            self._process.stdin.write(data.encode("utf-8"))
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpClientError(f"Failed to write to MCP server: {exc}")

    def _read_response(self, expected_id: int) -> Dict[str, Any]:
        """Read JSON-RPC messages until the response for expected_id.

        Deadline-bounded: lines arrive via the daemon reader thread's
        queue and the wait honors the remaining deadline, so a silent
        server raises McpClientError at exactly ``timeout_seconds``
        instead of blocking in readline() forever.
        """
        assert self._stdout_queue is not None
        max_wait = self._timeout  # per-server, from ServerConfig.timeout_seconds
        deadline = time.monotonic() + max_wait

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpClientError(
                    f"MCP server '{self._config.name}' timed out after {max_wait}s"
                )
            try:
                item = self._stdout_queue.get(timeout=remaining)
            except queue.Empty:
                raise McpClientError(
                    f"MCP server '{self._config.name}' timed out after {max_wait}s"
                )

            if item is _STDOUT_EOF:
                # Server exited (or closed stdout). Re-post the sentinel
                # so any later read also sees EOF, then fail cleanly.
                self._stdout_queue.put(_STDOUT_EOF)
                returncode = self._process.poll() if self._process else None
                stderr_tail = "\n".join(self._stderr_lines[-10:])
                if returncode is not None:
                    raise McpClientError(
                        f"MCP server '{self._config.name}' exited with code {returncode}.\n"
                        f"Stderr: {stderr_tail}"
                    )
                raise McpClientError(
                    f"MCP server '{self._config.name}' closed stdout unexpectedly"
                )

            text = item.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                logger.warning(f"[MCP:{self._config.name}] Invalid JSON: {text[:200]}")
                continue

            # Skip notifications (no id field)
            if "id" not in message:
                continue

            # Return the matching response
            if message["id"] == expected_id:
                return message

            # Not our response, skip (shouldn't happen with sync client)
            logger.warning(
                f"[MCP:{self._config.name}] Unexpected response id={message['id']}, expected={expected_id}"
            )
