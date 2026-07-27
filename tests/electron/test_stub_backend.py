"""Unit tests for the stdlib stub backend.

Verifies that the stub correctly implements the API contracts from Tasks 1-10
so that Electron Playwright E2E tests can run without a real FastAPI backend.

Run:
    /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
        tests/electron/test_stub_backend.py -v
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request

import pytest

# Ensure the stub_backend module is importable
sys.path.insert(0, os.path.dirname(__file__))

from stub_backend import StubBackend


class _HTTPHelper:
    """Thin HTTP client helper (stdlib only, no requests dependency)."""

    def __init__(self, base_url):
        # type: (str) -> None
        self.base = base_url

    def get(self, path, expected_status=200):
        # type: (str, int) -> dict
        url = self.base + path
        try:
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            body = resp.read().decode("utf-8")
            assert resp.status == expected_status, \
                "GET {} expected {} got {}".format(path, expected_status, resp.status)
            return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            assert e.code == expected_status, \
                "GET {} expected {} got {}".format(path, expected_status, e.code)
            return json.loads(body) if body else {}

    def post(self, path, data=None, expected_status=200):
        # type: (str, dict, int) -> dict
        url = self.base + path
        body = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            rbody = resp.read().decode("utf-8")
            assert resp.status == expected_status, \
                "POST {} expected {} got {}".format(path, expected_status, resp.status)
            return json.loads(rbody) if rbody else {}
        except urllib.error.HTTPError as e:
            rbody = e.read().decode("utf-8")
            assert e.code == expected_status, \
                "POST {} expected {} got {}".format(path, expected_status, e.code)
            return json.loads(rbody) if rbody else {}

    def put(self, path, data=None, expected_status=200):
        # type: (str, dict, int) -> dict
        url = self.base + path
        body = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="PUT",
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            rbody = resp.read().decode("utf-8")
            assert resp.status == expected_status, \
                "PUT {} expected {} got {}".format(path, expected_status, resp.status)
            return json.loads(rbody) if rbody else {}
        except urllib.error.HTTPError as e:
            rbody = e.read().decode("utf-8")
            assert e.code == expected_status, \
                "PUT {} expected {} got {}".format(path, expected_status, e.code)
            return json.loads(rbody) if rbody else {}

    def delete(self, path, expected_status=200):
        # type: (str, int) -> dict
        url = self.base + path
        req = urllib.request.Request(url, method="DELETE")
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            body = resp.read().decode("utf-8")
            assert resp.status == expected_status, \
                "DELETE {} expected {} got {}".format(path, expected_status, resp.status)
            return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            assert e.code == expected_status, \
                "DELETE {} expected {} got {}".format(path, expected_status, e.code)
            return json.loads(body) if body else {}

    def get_ndjson(self, path):
        # type: (str) -> list
        url = self.base + path
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        assert resp.status == 200
        lines = resp.read().decode("utf-8").strip().split("\n")
        return [json.loads(line) for line in lines if line.strip()]


# ---- Test classes ----


class TestHealthEndpoint:
    """GET /health returns status ok."""

    def test_health_returns_ok(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        resp = http.get("/health")
        assert resp["status"] == "ok"
        assert "version" in resp


class TestSessionCRUD:
    """POST/GET /api/v1/sessions creates and retrieves sessions."""

    def test_create_session(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        resp = http.post("/api/v1/sessions", {"title": "Test Session"})
        assert "id" in resp
        assert resp["title"] == "Test Session"
        assert "created_at" in resp
        assert resp["message_count"] == 0
        assert resp["is_pinned"] is False

    def test_create_session_default_title(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        resp = http.post("/api/v1/sessions", {})
        assert resp["title"] == "新对话"

    def test_get_session(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        created = http.post("/api/v1/sessions", {"title": "Get Me"})
        fetched = http.get("/api/v1/sessions/{}".format(created["id"]))
        assert fetched["id"] == created["id"]
        assert fetched["title"] == "Get Me"

    def test_get_session_not_found(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        resp = http.get("/api/v1/sessions/nonexistent-id", expected_status=404)
        assert "detail" in resp

    def test_list_sessions(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        http.post("/api/v1/sessions", {"title": "First"})
        http.post("/api/v1/sessions", {"title": "Second"})
        resp = http.get("/api/v1/sessions")
        assert isinstance(resp, list)
        assert len(resp) >= 2


class TestWorkspaceBinding:
    """PUT/GET/DELETE /api/v1/sessions/{id}/workspace bind lifecycle."""

    def _create_session(self, http):
        # type: (_HTTPHelper) -> str
        resp = http.post("/api/v1/sessions", {"title": "WS Test"})
        return resp["id"]

    def test_get_workspace_no_binding(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        sid = self._create_session(http)
        resp = http.get("/api/v1/sessions/{}/workspace".format(sid))
        assert resp["binding"] is None

    def test_bind_workspace(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        sid = self._create_session(http)
        resp = http.put(
            "/api/v1/sessions/{}/workspace".format(sid),
            {"workspace_path": "/tmp/test-workspace"},
        )
        assert resp["binding"] is not None
        assert resp["binding"]["session_id"] == sid
        assert resp["binding"]["workspace_path"] == "/tmp/test-workspace"
        assert resp["binding"]["generation"] == 1
        assert resp["binding"]["revoked_at"] is None

    def test_get_workspace_after_bind(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        sid = self._create_session(http)
        http.put(
            "/api/v1/sessions/{}/workspace".format(sid),
            {"workspace_path": "/tmp/ws"},
        )
        resp = http.get("/api/v1/sessions/{}/workspace".format(sid))
        assert resp["binding"] is not None
        assert resp["binding"]["workspace_path"] == "/tmp/ws"

    def test_rebind_increments_generation(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        sid = self._create_session(http)
        r1 = http.put(
            "/api/v1/sessions/{}/workspace".format(sid),
            {"workspace_path": "/tmp/ws1"},
        )
        r2 = http.put(
            "/api/v1/sessions/{}/workspace".format(sid),
            {"workspace_path": "/tmp/ws2"},
        )
        assert r1["binding"]["generation"] == 1
        assert r2["binding"]["generation"] == 2
        assert r2["binding"]["workspace_path"] == "/tmp/ws2"

    def test_revoke_workspace(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        sid = self._create_session(http)
        http.put(
            "/api/v1/sessions/{}/workspace".format(sid),
            {"workspace_path": "/tmp/ws"},
        )
        resp = http.delete("/api/v1/sessions/{}/workspace".format(sid))
        assert resp["revoked"] is True
        assert resp["generation"] == 1
        # After revoke, get returns null binding
        get_resp = http.get("/api/v1/sessions/{}/workspace".format(sid))
        assert get_resp["binding"] is None

    def test_bind_empty_path_rejected(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        sid = self._create_session(http)
        http.put(
            "/api/v1/sessions/{}/workspace".format(sid),
            {"workspace_path": ""},
            expected_status=400,
        )

    def test_workspace_session_not_found(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        http.put(
            "/api/v1/sessions/fake-id/workspace",
            {"workspace_path": "/tmp/ws"},
            expected_status=404,
        )

    def test_revoke_no_binding(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        sid = self._create_session(http)
        http.delete(
            "/api/v1/sessions/{}/workspace".format(sid),
            expected_status=403,
        )

    def test_post_bind_also_works(self, stub_backend):
        """POST is accepted as alias for PUT (backward compat)."""
        http = _HTTPHelper(stub_backend.url)
        sid = self._create_session(http)
        resp = http.post(
            "/api/v1/sessions/{}/workspace".format(sid),
            {"workspace_path": "/tmp/post-bind"},
        )
        assert resp["binding"]["workspace_path"] == "/tmp/post-bind"


class TestWorkspaceSearch:
    """GET /api/v1/sessions/{id}/workspace/files."""

    def test_search_no_binding(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        resp_post = http.post("/api/v1/sessions", {"title": "Search Test"})
        sid = resp_post["id"]
        http.get(
            "/api/v1/sessions/{}/workspace/files?q=test".format(sid),
            expected_status=403,
        )

    def test_search_with_binding(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        resp_post = http.post("/api/v1/sessions", {"title": "Search Test"})
        sid = resp_post["id"]
        http.put(
            "/api/v1/sessions/{}/workspace".format(sid),
            {"workspace_path": "/tmp/ws"},
        )
        resp = http.get(
            "/api/v1/sessions/{}/workspace/files?q=test".format(sid),
        )
        assert "results" in resp
        assert "total" in resp
        assert isinstance(resp["results"], list)

    def test_search_session_not_found(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        http.get(
            "/api/v1/sessions/fake-id/workspace/files?q=test",
            expected_status=404,
        )


class TestChatStream:
    """POST /api/v1/chat/stream and GET /api/v1/chat/stream/{id}."""

    def test_create_stream(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        session = http.post("/api/v1/sessions", {"title": "Chat Test"})
        sid = session["id"]
        resp = http.post(
            "/api/v1/chat/stream",
            {"session_id": sid, "message": "Hello"},
        )
        assert "streamId" in resp
        assert len(resp["streamId"]) > 0

    def test_attach_stream(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        session = http.post("/api/v1/sessions", {"title": "Chat Test"})
        sid = session["id"]
        create_resp = http.post(
            "/api/v1/chat/stream",
            {"session_id": sid, "message": "Hello"},
        )
        stream_id = create_resp["streamId"]
        events = http.get_ndjson("/api/v1/chat/stream/{}".format(stream_id))
        assert len(events) >= 1
        states = [e["state"] for e in events]
        assert "done" in states

    def test_stream_session_not_found(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        http.post(
            "/api/v1/chat/stream",
            {"session_id": "nonexistent", "message": "Hello"},
            expected_status=404,
        )


class TestOfficeRefsAuthorization:
    """Task 6: office_refs authorization in POST /api/v1/chat/stream."""

    def test_empty_refs_no_binding_succeeds(self, stub_backend):
        """Empty office_refs with no binding should succeed (legacy path)."""
        http = _HTTPHelper(stub_backend.url)
        session = http.post("/api/v1/sessions", {"title": "Office Test"})
        sid = session["id"]
        resp = http.post(
            "/api/v1/chat/stream",
            {"session_id": sid, "message": "Hello", "office_refs": []},
        )
        assert "streamId" in resp

    def test_refs_with_binding_succeeds(self, stub_backend):
        """Valid office_refs with matching binding should succeed."""
        http = _HTTPHelper(stub_backend.url)
        session = http.post("/api/v1/sessions", {"title": "Office Test"})
        sid = session["id"]
        http.put(
            "/api/v1/sessions/{}/workspace".format(sid),
            {"workspace_path": "/tmp/ws"},
        )
        resp = http.post(
            "/api/v1/chat/stream",
            {
                "session_id": sid,
                "message": "Hello",
                "workspace_path": "/tmp/ws",
                "office_refs": [
                    {"doc_id": "doc-1", "doc_type": "ppt", "filename": "test.pptx"}
                ],
            },
        )
        assert "streamId" in resp

    def test_refs_no_binding_fails(self, stub_backend):
        """Non-empty office_refs with no binding should fail 403."""
        http = _HTTPHelper(stub_backend.url)
        session = http.post("/api/v1/sessions", {"title": "Office Test"})
        sid = session["id"]
        http.post(
            "/api/v1/chat/stream",
            {
                "session_id": sid,
                "message": "Hello",
                "office_refs": [
                    {"doc_id": "doc-1", "doc_type": "ppt", "filename": "test.pptx"}
                ],
            },
            expected_status=403,
        )

    def test_refs_path_mismatch_fails(self, stub_backend):
        """office_refs with workspace_path mismatch should fail 400."""
        http = _HTTPHelper(stub_backend.url)
        session = http.post("/api/v1/sessions", {"title": "Office Test"})
        sid = session["id"]
        http.put(
            "/api/v1/sessions/{}/workspace".format(sid),
            {"workspace_path": "/tmp/ws"},
        )
        http.post(
            "/api/v1/chat/stream",
            {
                "session_id": sid,
                "message": "Hello",
                "workspace_path": "/tmp/different-ws",
                "office_refs": [
                    {"doc_id": "doc-1", "doc_type": "ppt", "filename": "test.pptx"}
                ],
            },
            expected_status=400,
        )


class TestStubBackendLifecycle:
    """StubBackend start/stop/url properties."""

    def test_url_property(self):
        stub = StubBackend(host="127.0.0.1", port=0)
        stub.start()
        try:
            assert stub.url.startswith("http://127.0.0.1:")
            port = int(stub.url.split(":")[-1])
            assert port > 0
        finally:
            stub.stop()

    def test_db_property(self):
        stub = StubBackend(host="127.0.0.1", port=0)
        stub.start()
        try:
            assert stub.db is not None
        finally:
            stub.stop()

    def test_stop_idempotent(self):
        stub = StubBackend(host="127.0.0.1", port=0)
        stub.start()
        stub.stop()
        stub.stop()  # Should not raise

    def test_conftest_fixture_sets_env(self, stub_backend):
        """conftest fixture sets SAGE_BACKEND_URL."""
        assert os.environ.get("SAGE_BACKEND_URL") == stub_backend.url
        assert stub_backend.url.startswith("http://127.0.0.1:")
