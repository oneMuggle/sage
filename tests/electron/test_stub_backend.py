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


class TestPermissionGate:
    """M1: permission_request gated stream + /permissions REST contract.

    The attach stream blocks (up to 25s) between permission_request and
    observing until POST /permissions/{id}/answer resolves the gate —
    these tests drive both sides from threads.
    """

    MARKER_MSG = "please run __PERM_TEST__ ls -la"

    def _create_marker_stream(self, http):
        session = http.post("/api/v1/sessions", {"title": "Perm Test"})
        create_resp = http.post(
            "/api/v1/chat/stream",
            {"session_id": session["id"], "message": self.MARKER_MSG},
        )
        return create_resp["streamId"]

    def _wait_pending_one(self, http, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            pending = http.get("/api/v1/permissions/pending")
            if len(pending) == 1:
                return pending[0]
            time.sleep(0.05)
        raise AssertionError("permission request did not become pending")

    def test_pending_empty_initially(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        assert http.get("/api/v1/permissions/pending") == []

    def test_answer_unknown_id_returns_not_ok(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        resp = http.post(
            "/api/v1/permissions/nope/answer", {"approved": True, "remember": False}
        )
        assert resp == {"ok": False, "error": "unknown_or_expired"}

    def test_answer_rejects_extra_body_fields_with_422(self, stub_backend):
        http = _HTTPHelper(stub_backend.url)
        http.post(
            "/api/v1/permissions/nope/answer",
            {"approved": True, "remember": False, "evil": 1},
            expected_status=422,
        )

    def test_gated_stream_approve_flow(self, stub_backend):
        import threading

        http = _HTTPHelper(stub_backend.url)
        stream_id = self._create_marker_stream(http)

        events_box = {}

        def attach():
            events_box["events"] = http.get_ndjson(
                "/api/v1/chat/stream/{}".format(stream_id)
            )

        t = threading.Thread(target=attach)
        t.start()
        try:
            perm = self._wait_pending_one(http)
            assert perm["tool_name"] == "terminal"
            assert perm["risk"] == "suspicious"
            assert "request_id" in perm and "args_summary" in perm

            resp = http.post(
                "/api/v1/permissions/{}/answer".format(perm["request_id"]),
                {"approved": True, "remember": True},
            )
            assert resp == {"ok": True}
            t.join(timeout=30)
            assert not t.is_alive(), "attach stream did not complete after answer"
        finally:
            if t.is_alive():
                t.join(timeout=1)

        states = [e["state"] for e in events_box["events"]]
        assert states == ["acting", "permission_request", "observing", "content_delta", "done"]
        perm_evt = events_box["events"][1]
        assert perm_evt["permission_request"]["tool_name"] == "terminal"
        done_evt = events_box["events"][-1]
        assert "已执行" in done_evt["content"]

        inspection = http.get("/api/v1/_test/permission_answers")
        assert inspection["answers"] == [
            {"request_id": perm["request_id"], "approved": True, "remember": True}
        ]
        # 应答后 pending 清空
        assert http.get("/api/v1/permissions/pending") == []

    def test_gated_stream_deny_flow(self, stub_backend):
        import threading

        http = _HTTPHelper(stub_backend.url)
        stream_id = self._create_marker_stream(http)

        events_box = {}

        def attach():
            events_box["events"] = http.get_ndjson(
                "/api/v1/chat/stream/{}".format(stream_id)
            )

        t = threading.Thread(target=attach)
        t.start()
        try:
            perm = self._wait_pending_one(http)
            resp = http.post(
                "/api/v1/permissions/{}/answer".format(perm["request_id"]),
                {"approved": False},
            )
            assert resp == {"ok": True}
            t.join(timeout=30)
            assert not t.is_alive()
        finally:
            if t.is_alive():
                t.join(timeout=1)

        done_evt = events_box["events"][-1]
        assert done_evt["state"] == "done"
        assert "跳过" in done_evt["content"]
        observing = events_box["events"][2]
        assert "权限拒绝" in observing["tool_result"]["content"]


# ---- Task 3: orchestration endpoint tests ----
#
# Note: the Task 3 brief wrote these against the ``requests`` library, but the
# sage-backend env intentionally has no ``requests`` installed (this file's
# _HTTPHelper exists precisely for "stdlib only, no requests dependency"), so
# they are transcribed with identical names/assertions on top of _HTTPHelper
# (and raw urllib for the NDJSON header check).


def test_orchestration_create_run_returns_3_lanes():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        http = _HTTPHelper(server.url)
        data = http.post(
            "/api/v1/orchestration/runs",
            {"session_id": "sess1", "plan": "test plan"},
        )
        assert data["run_id"].startswith("run_")
        assert data["status"] == "running"
        assert len(data["lanes"]) == 3
        assert {lane["name"] for lane in data["lanes"]} == {"planner", "executor", "reviewer"}
    finally:
        server.stop()


def test_orchestration_get_run_after_create():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        http = _HTTPHelper(server.url)
        created = http.post(
            "/api/v1/orchestration/runs", {"session_id": "s1", "plan": "p"}
        )
        rid = created["run_id"]
        fetched = http.get("/api/v1/orchestration/runs/{}".format(rid))
        assert fetched["run_id"] == rid
    finally:
        server.stop()


def test_orchestration_cancel_sets_flag():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        http = _HTTPHelper(server.url)
        created = http.post(
            "/api/v1/orchestration/runs", {"session_id": "s1", "plan": "p"}
        )
        rid = created["run_id"]
        http.post("/api/v1/orchestration/runs/{}/cancel".format(rid))
        fetched = http.get("/api/v1/orchestration/runs/{}".format(rid))
        assert fetched["cancelled"] is True
    finally:
        server.stop()


def test_orchestration_approve_records_token():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        http = _HTTPHelper(server.url)
        created = http.post(
            "/api/v1/orchestration/runs", {"session_id": "s1", "plan": "p"}
        )
        rid = created["run_id"]
        resp = http.post(
            "/api/v1/orchestration/runs/{}/approve".format(rid),
            {"token": "user_token_1"},
        )
        assert resp["approval_token"] == "user_token_1"
    finally:
        server.stop()


def test_orchestration_events_sse_stream():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        http = _HTTPHelper(server.url)
        created = http.post(
            "/api/v1/orchestration/runs", {"session_id": "s1", "plan": "p"}
        )
        rid = created["run_id"]
        req = urllib.request.Request(
            server.url + "/api/v1/orchestration/runs/{}/events".format(rid),
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            assert "application/x-ndjson" in resp.headers["Content-Type"]
            first_line = resp.readline().decode("utf-8")
            event = json.loads(first_line)
            assert event["run_id"] == rid
    finally:
        server.stop()


# ---- Task 4: wiki endpoint tests ----
#
# Note: the Task 4 brief wrote these against the ``requests`` library, but the
# sage-backend env intentionally has no ``requests`` installed (this file's
# _HTTPHelper exists precisely for "stdlib only, no requests dependency"), so
# they are transcribed with identical names/assertions on top of _HTTPHelper
# (same adaptation as the Task 3 orchestration tests above).


def test_wiki_ingest_then_search_returns_ranked_results():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        http = _HTTPHelper(server.url)
        r1 = http.post(
            "/api/v1/wiki/ingest",
            {"title": "Sage Memory", "content": "Sage has 3-tier memory"},
        )
        doc_id = r1["doc_id"]
        assert r1["chunks"] >= 1

        r2 = http.post(
            "/api/v1/wiki/search",
            {"query": "memory", "limit": 5},
        )
        assert r2["total"] >= 1
        assert r2["items"][0]["doc_id"] == doc_id
        assert 0.0 <= r2["items"][0]["score"] <= 1.0
    finally:
        server.stop()


def test_wiki_extract_returns_title_and_body():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        http = _HTTPHelper(server.url)
        data = http.post(
            "/api/v1/wiki/extract",
            {"content": "Sage is great. It supports E2E."},
        )
        assert "title" in data
        assert "body" in data
        assert isinstance(data.get("links", []), list)
    finally:
        server.stop()


def test_wiki_insights_returns_summary_and_tags():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        http = _HTTPHelper(server.url)
        r1 = http.post(
            "/api/v1/wiki/ingest",
            {"title": "Foo", "content": "Sage memory works."},
        )
        doc_id = r1["doc_id"]
        r2 = http.get("/api/v1/wiki/insights/{}".format(doc_id))
        assert "summary" in r2
        assert isinstance(r2.get("tags", []), list)
    finally:
        server.stop()


def test_wiki_deep_research_returns_plan():
    server = StubBackend(host="127.0.0.1", port=0)
    server.start()
    try:
        http = _HTTPHelper(server.url)
        data = http.post(
            "/api/v1/wiki/deep-research",
            {"topic": "Sage memory tiers"},
        )
        assert "steps" in data
        assert data["status"] in ("pending", "running", "done")
    finally:
        server.stop()
