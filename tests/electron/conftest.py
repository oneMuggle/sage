"""Pytest fixtures for Electron E2E stub backend tests."""
from __future__ import annotations

import os
import sys

import pytest

# Ensure the stub_backend module is importable from tests/electron/
sys.path.insert(0, os.path.dirname(__file__))

from stub_backend import StubBackend


@pytest.fixture()
def stub_backend():
    """Start a stub backend on a random port, set SAGE_BACKEND_URL, yield, stop.

    The stub backend runs in a background daemon thread and uses an in-memory
    SQLite database. Each test gets a fresh instance (no state leakage).
    """
    stub = StubBackend(host="127.0.0.1", port=0)
    stub.start()
    old_url = os.environ.get("SAGE_BACKEND_URL")
    os.environ["SAGE_BACKEND_URL"] = stub.url
    try:
        yield stub
    finally:
        stub.stop()
        if old_url is not None:
            os.environ["SAGE_BACKEND_URL"] = old_url
        else:
            os.environ.pop("SAGE_BACKEND_URL", None)
