"""Local CONNECT relay for arena proxy traffic (plan §5.6, P2).

Why this exists (measured in the reference project, proxy_relay.py header):

    Chili-style proxies reject any CONNECT request that carries a ``Host``
    header:

        minimal CONNECT            -> 200 OK
        + Host                     -> rejected
        + User-Agent               -> 200 OK
        + Proxy-Connection         -> 200 OK

    libcurl / curl_cffi ALWAYS send Host on CONNECT, so pointing them at such
    a proxy directly fails. The relay terminates that problem:

        http client --CONNECT--> 127.0.0.1:<local port>  (this relay)
                                      |
                 minimal CONNECT (no Host) + optional Proxy-Authorization
                                      |
                                 upstream proxy -> arena.ai (TLS end-to-end,
                                 fingerprint preserved)

Port assignment MUST be left to the OS (``bind(("127.0.0.1", 0))``).
Windows SO_REUSEADDR lets *multiple processes* bind the same fixed port —
the reference measured 11 processes all listening on 20000 with only the
oldest actually accepting, silently destroying per-instance IP isolation.

Pure stdlib on purpose: this runs next to the Electron token windows and
must not gain heavyweight dependencies.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import re
import socket
import threading
from typing import Dict, Optional
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

_CONNECT_RE = re.compile(r"CONNECT\s+([^\s:]+):(\d+)", re.I)


class Relay:
    """One local listening port per upstream proxy URL (reused per upstream)."""

    def __init__(self, log=None):
        self._log = log or (lambda _msg: None)
        self._lock = threading.Lock()
        self._ports: Dict[str, int] = {}    # upstream url -> local port
        self._servers: Dict[int, socket.socket] = {}  # local port -> listener

    # -- public -----------------------------------------------------------

    def add(self, upstream: str) -> int:
        """Allocate a local port for ``upstream`` (same upstream → same port).

        The port is system-assigned — see module docstring for the Windows
        SO_REUSEADDR incident that forbids fixed port bases.
        """
        upstream = str(upstream or "").strip()
        with self._lock:
            if upstream in self._ports:
                return self._ports[upstream]
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        port = int(server.getsockname()[1])
        server.listen(64)
        with self._lock:
            self._servers[port] = server
            self._ports[upstream] = port
        threading.Thread(
            target=self._accept_loop, args=(server, upstream), daemon=True
        ).start()
        return port

    def local_url(self, upstream: str) -> str:
        """The http://127.0.0.1:<port> URL clients should use as proxy."""
        return "http://127.0.0.1:%d" % self.add(upstream)

    def close_all(self) -> None:
        with self._lock:
            servers = list(self._servers.values())
            self._servers.clear()
            self._ports.clear()
        for server in servers:
            with contextlib.suppress(OSError):
                server.close()

    # -- internals ----------------------------------------------------------

    def _accept_loop(self, server: socket.socket, upstream: str) -> None:
        while True:
            try:
                client, _ = server.accept()
            except OSError:
                return  # listener closed
            threading.Thread(
                target=self._handle, args=(client, upstream), daemon=True
            ).start()

    def _handle(self, client: socket.socket, upstream: str) -> None:
        upstream_sock: Optional[socket.socket] = None
        try:
            client.settimeout(30)
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 8192:
                chunk = client.recv(1024)
                if not chunk:
                    client.close()
                    return
                data += chunk
            head = data.split(b"\r\n", 1)[0].decode("latin-1")
            match = _CONNECT_RE.search(head)
            if not match:
                client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                client.close()
                return
            host, port = match.group(1), int(match.group(2))

            up = urlparse(upstream if "://" in upstream else "http://" + upstream)
            upstream_sock = socket.create_connection(
                (up.hostname, up.port or 80), timeout=20
            )
            upstream_sock.settimeout(30)

            auth = b""
            if up.username:
                raw = unquote(up.username) + ":" + unquote(up.password or "")
                auth = (
                    "Proxy-Authorization: Basic "
                    + base64.b64encode(raw.encode("utf-8")).decode("ascii")
                    + "\r\n"
                ).encode("latin-1")
            # ★ the whole point: minimal CONNECT, NEVER a Host header.
            request = (
                "CONNECT %s:%d HTTP/1.0\r\n" % (host, port)
            ).encode("latin-1") + auth + b"\r\n"
            upstream_sock.sendall(request)

            response = b""
            while b"\r\n\r\n" not in response and len(response) < 4096:
                piece = upstream_sock.recv(512)
                if not piece:
                    break
                response += piece
            first = response.split(b"\r\n", 1)[0] if response else b""
            if b" 200" not in first:
                with contextlib.suppress(OSError):
                    client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                client.close()
                upstream_sock.close()
                return
            client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            client.settimeout(None)
            upstream_sock.settimeout(None)
            self._pipe(client, upstream_sock)
        except OSError as exc:
            self._log(f"[relay] connection failed: {exc}")
            with contextlib.suppress(OSError):
                client.close()
            if upstream_sock is not None:
                with contextlib.suppress(OSError):
                    upstream_sock.close()

    @staticmethod
    def _pipe(a: socket.socket, b: socket.socket) -> None:
        def forward(src: socket.socket, dst: socket.socket) -> None:
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                for sock in (src, dst):
                    with contextlib.suppress(OSError):
                        sock.shutdown(socket.SHUT_RDWR)
                    with contextlib.suppress(OSError):
                        sock.close()

        threading.Thread(target=forward, args=(a, b), daemon=True).start()
        forward(b, a)


#: Module-level singleton (one relay process-wide; ports are per-upstream).
_relay: Optional[Relay] = None
_relay_lock = threading.Lock()


def _get_relay() -> Relay:
    global _relay
    with _relay_lock:
        if _relay is None:
            _relay = Relay(log=lambda msg: logger.debug("%s", msg))
        return _relay


def _is_local(url: str) -> bool:
    parsed = urlparse(url if "://" in url else "http://" + url)
    host = (parsed.hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def local_proxy(upstream: str) -> str:
    """Map an upstream proxy URL onto the local relay.

    Empty input and already-local proxies pass through unchanged; any relay
    failure falls back to the original URL (the relay is an optimization for
    chili-style proxies, never a hard dependency). Callers therefore never
    need to handle relay errors.
    """
    upstream = str(upstream or "").strip()
    if not upstream or _is_local(upstream):
        return upstream
    try:
        return _get_relay().local_url(upstream)
    except OSError as exc:
        logger.warning("arena proxy relay unavailable, using direct URL: %s", exc)
        return upstream


def shutdown_relay() -> None:
    """Close all relay listeners (backend shutdown / tests)."""
    global _relay
    with _relay_lock:
        relay, _relay = _relay, None
    if relay is not None:
        relay.close_all()
