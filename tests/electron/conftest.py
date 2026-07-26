"""Pytest fixtures for Electron E2E stub backend tests.

Provides two environment variables so both stdlib HTTP clients and the Electron
main process can reach the stub backend:

- ``SAGE_BACKEND_URL``: full base URL (e.g. ``http://127.0.0.1:54321``)
- ``PYTHON_BACKEND_PORT``: port number only — consumed by Electron main
  (``electron/main.ts`` reads ``process.env.PYTHON_BACKEND_PORT ?? 8765``)

Both variables are restored (or unset) on teardown so fixtures don't leak.
"""
from __future__ import annotations

import os
import sys

import pytest

# Ensure the stub_backend module is importable from tests/electron/
sys.path.insert(0, os.path.dirname(__file__))

from stub_backend import StubBackend


@pytest.fixture()
def stub_backend():
    """Start a stub backend on a random port, yield, stop.

    The stub backend runs in a background daemon thread and uses an in-memory
    SQLite database. Each test gets a fresh instance (no state leakage).
    """
    stub = StubBackend(host="127.0.0.1", port=0)
    stub.start()
    port = int(stub.url.rsplit(":", 1)[-1])

    old_url = os.environ.get("SAGE_BACKEND_URL")
    old_port = os.environ.get("PYTHON_BACKEND_PORT")
    os.environ["SAGE_BACKEND_URL"] = stub.url
    os.environ["PYTHON_BACKEND_PORT"] = str(port)
    try:
        yield stub
    finally:
        stub.stop()
        if old_url is not None:
            os.environ["SAGE_BACKEND_URL"] = old_url
        else:
            os.environ.pop("SAGE_BACKEND_URL", None)
        if old_port is not None:
            os.environ["PYTHON_BACKEND_PORT"] = old_port
        else:
            os.environ.pop("PYTHON_BACKEND_PORT", None)
