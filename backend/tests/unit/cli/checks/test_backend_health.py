"""Tests for backend.cli.checks.backend_health.BackendHealthCheck."""
from __future__ import annotations

import json
import os
import urllib.error
from unittest import mock

import pytest

from backend.cli.checks.backend_health import BackendHealthCheck
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return BackendHealthCheck()


class _FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestBackendHealthCheck:
    def test_info_when_health_ok(self, check):
        body = json.dumps({"status": "ok", "version": "0.5.0"})
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _FakeResponse(200, body)
            result = check.run()
        assert result.severity == Severity.INFO
        assert "ok" in result.message
        assert check.name == "backend_health"

    def test_warn_when_status_500(self, check):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _FakeResponse(500, "internal error")
            result = check.run()
        assert result.severity == Severity.WARN
        assert "500" in result.message
        assert result.fix_hint is not None

    def test_warn_when_non_json_response(self, check):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _FakeResponse(200, "<html>not json</html>")
            result = check.run()
        assert result.severity == Severity.WARN
        assert "非 JSON" in result.message

    def test_warn_when_status_field_not_ok(self, check):
        body = json.dumps({"status": "degraded"})
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value = _FakeResponse(200, body)
            result = check.run()
        assert result.severity == Severity.WARN
        assert "degraded" in result.message

    def test_warn_when_urlerror(self, check):
        with mock.patch("urllib.request.urlopen") as m:
            m.side_effect = urllib.error.URLError("Connection refused")
            result = check.run()
        assert result.severity == Severity.WARN
        assert "python backend/main.py" in result.fix_hint

    def test_warn_when_timeout(self, check):
        with mock.patch("urllib.request.urlopen") as m:
            m.side_effect = TimeoutError("timed out")
            result = check.run()
        assert result.severity == Severity.WARN

    def test_uses_default_port_8765(self, check):
        with mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("PYTHON_BACKEND_PORT", None)
            with mock.patch("urllib.request.urlopen") as m:
                captured_url = []

                def fake_urlopen(req, timeout=None):
                    captured_url.append(req.full_url)
                    raise urllib.error.URLError("nope")

                m.side_effect = fake_urlopen
                check.run()
        assert "8765" in captured_url[0]

    def test_uses_custom_port_from_env(self, check):
        with mock.patch.dict("os.environ", {"PYTHON_BACKEND_PORT": "9999"}):
            with mock.patch("urllib.request.urlopen") as m:
                captured_url = []

                def fake_urlopen(req, timeout=None):
                    captured_url.append(req.full_url)
                    raise urllib.error.URLError("nope")

                m.side_effect = fake_urlopen
                check.run()
        assert "9999" in captured_url[0]

    def test_check_attributes(self, check):
        assert check.name == "backend_health"
        assert isinstance(check.description, str)
