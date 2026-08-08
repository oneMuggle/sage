"""Tests for backend.cli.checks.port_frontend.PortFrontendCheck."""
from __future__ import annotations

import socket

import pytest

from backend.cli.checks.port_frontend import PORT, PortFrontendCheck
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return PortFrontendCheck()


def _bind_1420():
    """Helper: bind 1420 to occupy it (calls ``listen()`` so the port is
    actually marked as in-use by the kernel)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", PORT))
    s.listen(1)
    return s


class TestPortFrontendCheck:
    def test_info_when_port_free(self, check):
        """When 1420 is free, expect INFO (vite not running)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", PORT))
            s.close()  # release for the check
            result = check.run()
        finally:
            s.close()
        assert result.severity == Severity.INFO
        assert "1420" in result.message
        assert "空闲" in result.message
        assert check.name == "port_frontend"

    def test_info_when_port_occupied(self, check):
        """When 1420 is occupied (vite running), expect INFO (not WARN)."""
        s = _bind_1420()
        try:
            result = check.run()
        finally:
            s.close()
        assert result.severity == Severity.INFO
        assert "已被占用" in result.message

    def test_check_attributes(self, check):
        assert check.name == "port_frontend"
        assert isinstance(check.description, str)
        assert check.description
