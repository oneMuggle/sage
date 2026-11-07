"""后台 shell 列表与输出流路由测试（2026-11-06 Phase 3）。"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import shell_routes
from backend.tools.bash_session import STATUS_EXITED, STATUS_RUNNING

pytestmark = pytest.mark.unit


class FakeSession:
    def __init__(self, shell_id: str = "sh-1") -> None:
        self.shell_id = shell_id
        self.command = "pytest -q"
        self.process = SimpleNamespace(pid=4242)
        self.started_at = time.monotonic() - 10
        self.status_value = STATUS_RUNNING

    def status(self) -> str:
        return self.status_value


class FakeRegistry:
    def __init__(self) -> None:
        self.sessions = {"sh-1": FakeSession()}
        self.chunks = []

    def list_sessions(self):
        return list(self.sessions.values())

    def get(self, shell_id):
        return self.sessions.get(shell_id)

    def read_increment(self, shell_id, cap):
        if shell_id not in self.sessions:
            return None
        if self.chunks:
            return self.chunks.pop(0)
        return {
            "status": self.sessions[shell_id].status(),
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "truncated": False,
        }


@pytest.fixture()
def client(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr(shell_routes, "get_registry", lambda: registry)
    app = FastAPI()
    app.include_router(shell_routes.router, prefix="/api/v1")
    return TestClient(app), registry


def test_list_shells(client) -> None:
    http, registry = client
    resp = http.get("/api/v1/shells")
    assert resp.status_code == 200
    shells = resp.json()["shells"]
    assert len(shells) == 1
    item = shells[0]
    assert item["shell_id"] == "sh-1"
    assert item["command"] == "pytest -q"
    assert item["status"] == STATUS_RUNNING
    assert item["pid"] == 4242
    assert item["age_seconds"] >= 10


def test_stream_unknown_shell_returns_404(client) -> None:
    http, _ = client
    resp = http.get("/api/v1/shells/missing/stream")
    assert resp.status_code == 404


def test_kill_shell(client) -> None:
    http, registry = client
    # FakeRegistry needs a terminate method
    registry.terminate = lambda shell_id, cap: {
        "shell_id": shell_id,
        "status": STATUS_EXITED,
        "exit_code": 0,
        "stdout": "final\n",
        "stderr": "",
        "killed": True,
    }
    resp = http.delete("/api/v1/shells/sh-1")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["shell_id"] == "sh-1"
    assert payload["killed"] is True


def test_kill_unknown_shell_returns_404(client) -> None:
    http, registry = client
    registry.terminate = lambda shell_id, cap: None
    resp = http.delete("/api/v1/shells/missing")
    assert resp.status_code == 404


def test_stream_outputs_then_exit(client) -> None:
    http, registry = client
    registry.chunks = [
        {
            "status": STATUS_RUNNING,
            "exit_code": None,
            "stdout": "hello\n",
            "stderr": "warn\n",
            "truncated": False,
        },
        {
            "status": STATUS_EXITED,
            "exit_code": 0,
            "stdout": "done\n",
            "stderr": "",
            "truncated": False,
        },
    ]
    resp = http.get("/api/v1/shells/sh-1/stream")
    assert resp.status_code == 200
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert {"type": "output", "stream": "stdout", "data": "hello\n"} in lines
    assert {"type": "output", "stream": "stderr", "data": "warn\n"} in lines
    assert {"type": "output", "stream": "stdout", "data": "done\n"} in lines
    assert lines[-1] == {"type": "exit", "exit_code": 0}


def test_stream_exits_when_session_disappears(client) -> None:
    http, registry = client
    registry.chunks = []
    original = registry.read_increment

    def read_then_remove(shell_id, cap):
        registry.sessions.pop(shell_id, None)
        return original(shell_id, cap)

    registry.read_increment = read_then_remove  # type: ignore[assignment]
    resp = http.get("/api/v1/shells/sh-1/stream")
    assert resp.status_code == 200
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert lines[-1] == {"type": "exit", "exit_code": None}
