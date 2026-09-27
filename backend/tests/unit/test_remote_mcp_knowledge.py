"""M5b：远程 Office 只读 / 记忆 / Wiki 检索工具。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.remote_mcp import knowledge
from backend.remote_mcp.approval import needs_approval
from backend.remote_mcp.audit import AuditLog
from backend.remote_mcp.protocol import RemoteMcpService
from backend.remote_mcp.store import WorkspaceStore


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "userdata"))
    root = tmp_path / "proj"
    (root / "docs").mkdir(parents=True)
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_heading("Title", level=1)
    doc.add_paragraph("hello remote office")
    doc.save(str(root / "docs" / "a.docx"))
    (root / "docs" / "notes.txt").write_text("x", encoding="utf-8")
    store = WorkspaceStore(str(tmp_path / "userdata" / "remote_workspaces.json"))
    ws = store.create("proj", str(root))
    service = RemoteMcpService(store, AuditLog(str(tmp_path / "userdata" / "audit.jsonl")))
    token = store.connection_token(ws["id"])
    yield service, store, ws, token, root
    service.pause()


def _post(service, token, payload, session=None):
    h = {"content-type": "application/json"}
    if session:
        h["mcp-session-id"] = session
    return service.handle("POST", token, h, json.dumps(payload).encode())


def _session(service, token):
    status, headers, _ = _post(service, token, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                "params": {"protocolVersion": "2025-03-26"}})
    assert status == 200
    return headers["mcp-session-id"]


def _call(service, token, session, name, args):
    _, _, body = _post(service, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                        "params": {"name": name, "arguments": args}}, session)
    result = body["result"]
    text = result["content"][0]["text"]
    return result["isError"], (text if result["isError"] else json.loads(text))


def test_new_permissions_default_off_and_legacy_view(env):
    _, store, ws, _, _ = env
    assert ws["permissions"] == {"read": True, "write": False, "shell": False,
                                 "office": False, "memory": False}
    legacy = store.public_view({"id": "x", "token": "t", "permissions": {"read": True, "write": True}})
    assert legacy["permissions"]["office"] is False
    assert legacy["permissions"]["write"] is True
    assert "token" not in legacy


def test_office_requires_permission(env):
    service, _, _, token, _ = env
    s = _session(service, token)
    err, text = _call(service, token, s, "office_read", {"path": "docs/a.docx"})
    assert err
    assert text.startswith("PERMISSION_DENIED")


def test_office_read_summary_and_head(env):
    service, store, ws, token, root = env
    store.update(ws["id"], permissions={"office": True})
    s = _session(service, token)
    err, data = _call(service, token, s, "office_read", {"path": "docs/a.docx"})
    assert not err, data
    assert data["section"] == "summary"
    assert data["path"] == "docs/a.docx"
    err, data = _call(service, token, s, "office_read", {"path": "docs/a.docx", "section": "head"})
    assert not err, data
    dumped = json.dumps(data, ensure_ascii=False)
    assert "hello remote office" in dumped
    assert str(root).replace("\\", "/") not in dumped.replace("\\\\", "/").replace("\\", "/")


@pytest.mark.parametrize(("path", "code"), [
    ("../x.docx", "PATH_DENIED"),
    ("docs/notes.txt", "UNSUPPORTED_FILE_TYPE"),
    ("docs/missing.docx", "PATH_DENIED"),
])
def test_office_read_rejects(env, path, code):
    service, store, ws, token, _ = env
    store.update(ws["id"], permissions={"office": True})
    s = _session(service, token)
    err, text = _call(service, token, s, "office_read", {"path": path})
    assert err, text
    assert text.startswith(code), text


def test_office_lint_word(env):
    service, store, ws, token, _ = env
    store.update(ws["id"], permissions={"office": True})
    s = _session(service, token)
    err, text = _call(service, token, s, "office_lint_word", {"path": "docs/a.docx", "format_spec": {}})
    assert err
    assert text.startswith("INVALID_ARGUMENT")
    err, data = _call(service, token, s, "office_lint_word",
                      {"path": "docs/a.docx", "format_spec": {"page": {"margins_cm": {"top": 2.54}}}})
    assert not err, data
    assert "ok" in data
    assert data["path"] == "docs/a.docx"


def test_fit_truncates_large_payload():
    data = {"summary": {"n": 1}, "paragraphs": ["x" * 1000] * 1000}
    out = knowledge._fit(data, "all")
    assert out["truncated"] is True
    assert len(json.dumps(out)) <= knowledge.MAX_OFFICE_JSON_CHARS
    assert knowledge._fit(data, "summary") == {"summary": {"n": 1}, "section": "summary"}


class _FakeMemory:
    def __init__(self):
        self.calls = []

    def search_memories(self, query, memory_type, limit, session_id=None, scope=None):
        self.calls.append((query, memory_type, limit, session_id, scope))
        return [{"id": "1", "memory_type": "semantic", "content": "y" * 5000, "secret_field": 1},
                {"id": "2", "memory_type": "working", "content": "w"}]


def test_memory_search_scoped_and_filtered(env, monkeypatch):
    service, store, ws, token, _ = env
    fake = _FakeMemory()
    monkeypatch.setattr(knowledge, "_memory_getter", lambda: fake)
    s = _session(service, token)
    err, text = _call(service, token, s, "memory_search", {"query": "q"})
    assert err
    assert text.startswith("PERMISSION_DENIED")
    store.update(ws["id"], permissions={"memory": True})
    err, text = _call(service, token, s, "memory_search", {"query": "q", "scope": "session"})
    assert err
    assert text.startswith("INVALID_ARGUMENT")
    err, text = _call(service, token, s, "memory_search", {"query": "q", "memory_type": "working"})
    assert err
    assert text.startswith("INVALID_ARGUMENT")
    err, data = _call(service, token, s, "memory_search", {"query": "q", "limit": 500})
    assert not err, data
    assert fake.calls[-1] == ("q", None, knowledge.MAX_MEMORY_RESULTS, None, "user")
    assert [r["id"] for r in data["results"]] == ["1"]
    assert "secret_field" not in data["results"][0]
    assert len(data["results"][0]["content"]) == knowledge.MAX_MEMORY_TEXT + 1


def test_wiki_search(env, monkeypatch):
    service, store, ws, token, root = env
    seen = {}

    def fake_search(project_root, query, limit=20):
        seen["args"] = (str(project_root), query, limit)
        hit = SimpleNamespace(title="T", path="wiki/t.md", snippet="s", score=1.0)
        return SimpleNamespace(results=[hit], total=1)

    import backend.wiki.search as wiki_search

    monkeypatch.setattr(wiki_search, "search_wiki", fake_search)
    store.update(ws["id"], permissions={"memory": True})
    s = _session(service, token)
    err, data = _call(service, token, s, "wiki_search", {"query": "abc", "limit": 999})
    assert not err, data
    assert seen["args"] == (ws["root"], "abc", 100)
    assert data == {"results": [{"title": "T", "path": "wiki/t.md", "snippet": "s", "score": 1.0}],
                    "total": 1}


def test_approval_rules_for_knowledge_tools():
    auto = {"approval": "auto"}
    ask = {"approval": "ask"}
    assert needs_approval(auto, "memory_search", {}) is None
    assert needs_approval(ask, "memory_search", {}) == "private"
    assert needs_approval(ask, "office_read", {}) is None
    assert needs_approval(ask, "wiki_search", {}) is None
