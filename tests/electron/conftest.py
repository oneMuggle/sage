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
import subprocess
import sys

import pytest

# Ensure the stub_backend module is importable from tests/electron/
sys.path.insert(0, os.path.dirname(__file__))

from _real_backend import RealBackend
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


def _conda_env_available(env_name: str) -> bool:
    try:
        subprocess.run(
            ["conda", "run", "-n", env_name, "python", "-c", "pass"],
            check=True, capture_output=True, timeout=10,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


@pytest.fixture()
def real_backend():
    """启动真实 conda sage-backend。环境不可用时 skip。"""
    if not _conda_env_available("sage-backend"):
        pytest.skip("sage-backend conda env not available")

    backend = RealBackend()
    backend.start()
    old_port = os.environ.get("PYTHON_BACKEND_PORT")
    os.environ["PYTHON_BACKEND_PORT"] = str(backend.port)
    try:
        yield backend
    finally:
        # Q3 fix: wrap stop() so PYTHON_BACKEND_PORT restoration runs even if stop() raises.
        # stop() may swallow a benign error from SIGKILL escalation; we don't want that to
        # leak the test's stub port into the parent process env.
        try:
            backend.stop()
        except Exception:
            pass
        if old_port is not None:
            os.environ["PYTHON_BACKEND_PORT"] = old_port
        else:
            os.environ.pop("PYTHON_BACKEND_PORT", None)
