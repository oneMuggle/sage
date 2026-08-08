"""Tests for backend.cli.checks.port_backend.PortBackendCheck."""
from __future__ import annotations

import socket

import pytest

from backend.cli.checks.port_backend import PORT, PortBackendCheck
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return PortBackendCheck()


def _bind_8765():
    """Helper: bind 8765 to occupy it, return socket (caller closes).

    Calls ``listen()`` so the kernel marks the port as in-use; a bare
    ``bind()`` with ``SO_REUSEADDR`` would let the second bind succeed.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", PORT))
    s.listen(1)
    return s


class TestPortBackendCheck:
    def test_info_when_port_free(self, check):
        """When 8765 is free, expect INFO."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", PORT))
            s.close()  # release for the check
            result = check.run()
        finally:
            s.close()
        assert result.severity == Severity.INFO
        assert "8765" in result.message
        assert "空闲" in result.message
        assert check.name == "port_backend"

    def test_warn_when_port_occupied(self, check):
        """When 8765 is occupied, expect WARN (orphan backend)."""
        s = _bind_8765()
        try:
            result = check.run()
        finally:
            s.close()
        assert result.severity == Severity.WARN
        assert "被占用" in result.message
        assert result.fix_hint is not None
        assert "lsof" in result.fix_hint or "kill" in result.fix_hint

    def test_check_attributes(self, check):
        assert check.name == "port_backend"
        assert isinstance(check.description, str)
        assert check.description
