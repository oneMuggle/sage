"""Unit tests for backend/services/arena_proxy_relay.py.

Real sockets on 127.0.0.1 (system-assigned ports), fake chili-style upstream
proxy — no external network. The critical assertions mirror the P2
acceptance items: minimal CONNECT (NO Host header) and system-assigned ports.
"""

import contextlib
import socket
import threading

import pytest

from backend.services import arena_proxy_relay as apr


class FakeUpstream:
    """Chili-style fake proxy: records the CONNECT request, then tunnels.

    ``reject_host`` simulates the measured behaviour "CONNECT + Host →
    rejected"; the relay must never trigger it.
    """

    def __init__(self, reject_host=True, auth=None):
        self.reject_host = reject_host
        self.expect_auth = auth  # "user:pass" the upstream demands
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self.connect_requests = []
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            conn.settimeout(10)
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 8192:
                chunk = conn.recv(1024)
                if not chunk:
                    conn.close()
                    return
                data += chunk
            head, _, rest = data.partition(b"\r\n\r\n")
            self.connect_requests.append(head.decode("latin-1"))
            lines = head.decode("latin-1").split("\r\n")
            if self.reject_host and any(ln.lower().startswith("host:") for ln in lines[1:]):
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                conn.close()
                return
            if self.expect_auth:
                wanted = "Proxy-Authorization: Basic " + __import__("base64").b64encode(
                    self.expect_auth.encode()
                ).decode()
                if not any(ln == wanted for ln in lines[1:]):
                    conn.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
                    conn.close()
                    return
            conn.sendall(b"HTTP/1.0 200 Connection established\r\n\r\n")
            # tunnel: echo bytes back (acts as the "target server")
            conn.settimeout(None)
            while True:
                try:
                    piece = conn.recv(4096)
                except OSError:
                    break
                if not piece:
                    break
                conn.sendall(piece)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                conn.close()

    def url(self):
        base = f"127.0.0.1:{self.port}"
        if self.expect_auth:
            user, pw = self.expect_auth.split(":")
            return f"http://{user}:{pw}@{base}"
        return f"http://{base}"

    def close(self):
        self.server.close()


@pytest.fixture()
def upstream():
    fake = FakeUpstream()
    yield fake
    fake.close()


@pytest.fixture()
def relay():
    r = apr.Relay()
    yield r
    r.close_all()


def _connect_and_exchange(port, payload=b"PING", target="echo.example:443"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect(("127.0.0.1", port))
        sock.sendall(f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(1024)
        assert b" 200" in response.split(b"\r\n")[0]
        sock.sendall(payload)
        return sock.recv(4096)
    finally:
        sock.close()


def test_relay_sends_minimal_connect_without_host(upstream, relay):
    port = relay.add(upstream.url())
    got = _connect_and_exchange(port)
    assert got == b"PING"
    # the single critical protocol assertion
    assert upstream.connect_requests == ["CONNECT echo.example:443 HTTP/1.0"]


def test_relay_forwards_proxy_authorization():
    fake = FakeUpstream(auth="user:pw")
    try:
        relay = apr.Relay()
        try:
            port = relay.add(fake.url())
            got = _connect_and_exchange(port)
            assert got == b"PING"
            assert len(fake.connect_requests) == 1
            assert "Proxy-Authorization: Basic dXNlcjpwdw==" in fake.connect_requests[0]
        finally:
            relay.close_all()
    finally:
        fake.close()


def test_relay_bad_target_returns_502(relay):
    # upstream that always rejects CONNECT
    class Rejecting(FakeUpstream):
        def _handle(self, conn):
            try:
                conn.recv(1024)
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            except OSError:
                pass
            finally:
                conn.close()

    fake = Rejecting()
    try:
        port = relay.add(fake.url())
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        try:
            sock.connect(("127.0.0.1", port))
            sock.sendall(b"CONNECT x.example:443 HTTP/1.1\r\n\r\n")
            response = b""
            while b"\r\n\r\n" not in response:
                response += sock.recv(1024)
            assert b" 502" in response.split(b"\r\n")[0]
        finally:
            sock.close()
    finally:
        fake.close()


def test_relay_non_connect_returns_400(relay):
    port = relay.add("http://127.0.0.1:9")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect(("127.0.0.1", port))
        sock.sendall(b"GET http://x/ HTTP/1.1\r\n\r\n")
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(1024)
        assert b" 400" in response.split(b"\r\n")[0]
    finally:
        sock.close()


def test_ports_are_system_assigned_and_reused(upstream, relay):
    port1 = relay.add(upstream.url())
    assert port1 == relay.add(upstream.url())  # same upstream → same port
    relay2 = apr.Relay()
    try:
        port2 = relay2.add(upstream.url())
        assert port2 != port1  # different instance → different OS-assigned port
    finally:
        relay2.close_all()


def test_local_proxy_passthrough_and_mapping():
    assert apr.local_proxy("") == ""
    assert apr.local_proxy("http://127.0.0.1:3128") == "http://127.0.0.1:3128"
    # loopback upstream passes through unchanged (nothing to strip locally)
    loopback = "http://user:pw@127.0.0.1:3128"
    assert apr.local_proxy(loopback) == loopback
    # non-local upstream maps onto a system-assigned relay port
    mapped = apr.local_proxy("http://user:pw@gw.example.com:8080")
    assert mapped.startswith("http://127.0.0.1:")
    assert ":***@" not in mapped
    # mapping is stable (same upstream → same local port)
    assert apr.local_proxy("http://user:pw@gw.example.com:8080") == mapped
    # different upstream → different port
    other = apr.local_proxy("http://user:pw@gw2.example.com:8080")
    assert other != mapped
    apr.shutdown_relay()


def test_local_proxy_falls_back_on_unreachable_upstream():
    # connection refused upstream — local_proxy must still return a URL
    # (the failure only surfaces when a client actually connects)
    mapped = apr.local_proxy("http://10.255.255.1:9")
    assert mapped.startswith("http://127.0.0.1:") or mapped == "http://10.255.255.1:9"
    apr.shutdown_relay()


def test_relay_handles_concurrent_clients(upstream, relay):
    port = relay.add(upstream.url())
    results = []
    errors = []

    def worker(i):
        try:
            results.append(_connect_and_exchange(port, payload=f"msg{i}".encode()))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert not errors
    assert sorted(results) == sorted(f"msg{i}".encode() for i in range(8))
