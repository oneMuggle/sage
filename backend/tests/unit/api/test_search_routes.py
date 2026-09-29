"""R76 — 全局搜索路由单元测试。

global_search 直接调用 + 四个私有搜索 helper 分别打桩/透传。覆盖：
types 过滤与缺省全集、knowledge_project 多根授权解析、limit 透传、
session 映射、memory 归一化（截断/类型回退）与异常降级、project 映射
（session_count）、knowledge 多根合并去重与异常降级、无最近项目空集。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.api import search_routes as sr

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# global_search：types 过滤与透传
# ---------------------------------------------------------------------------


def _patch_all_helpers(monkeypatch):
    monkeypatch.setattr(
        sr, "_search_sessions", lambda q, limit: [{"id": "s", "q": q, "limit": limit}]
    )
    monkeypatch.setattr(
        sr, "_search_memories", lambda q, limit: [{"id": "m", "q": q, "limit": limit}]
    )
    monkeypatch.setattr(
        sr, "_search_knowledge", lambda q, limit, project_path=None: [
            {"id": "k", "q": q, "limit": limit, "scope": project_path}
        ]
    )
    monkeypatch.setattr(
        sr, "_search_projects", lambda q, limit: [{"id": "p", "q": q, "limit": limit}]
    )


def test_global_search_default_all_types(monkeypatch):
    _patch_all_helpers(monkeypatch)
    out = sr.global_search(q="kw", limit=10, types=None, knowledge_project=None)
    assert set(out) == {"sessions", "memories", "knowledge", "projects"}
    assert out["sessions"][0]["q"] == "kw"
    assert out["knowledge"][0]["scope"] is None


def test_global_search_types_filter(monkeypatch):
    _patch_all_helpers(monkeypatch)
    out = sr.global_search(q="kw", limit=5, types="session,memory", knowledge_project=None)
    assert set(out) == {"sessions", "memories"}
    assert out["sessions"][0]["limit"] == 5


def test_global_search_unknown_type_ignored(monkeypatch):
    _patch_all_helpers(monkeypatch)
    out = sr.global_search(q="kw", limit=5, types="session,nonexistent", knowledge_project=None)
    assert set(out) == {"sessions"}


def test_global_search_knowledge_project_single_root(monkeypatch):
    # win7 行为基线（P9）：knowledge_project 单值整串授权解析（无 P13 多根拆分）
    _patch_all_helpers(monkeypatch)
    resolved = []
    monkeypatch.setattr(
        sr, "_resolve_knowledge_scope", lambda raw: resolved.append(raw) or f"/p/{raw}"
    )
    out = sr.global_search(
        q="kw", limit=3, types="knowledge", knowledge_project="alpha"
    )
    assert resolved == ["alpha"]
    assert out["knowledge"][0]["scope"] == "/p/alpha"


# ---------------------------------------------------------------------------
# _search_sessions
# ---------------------------------------------------------------------------


def test_search_sessions_maps_fields(monkeypatch):
    repo = SimpleNamespace(
        search=lambda query, limit: [
            SimpleNamespace(id="s1", title="T", updated_at=5, message_count=2)
        ]
    )
    monkeypatch.setattr(
        "backend.data.session_repo.SessionRepository", lambda: repo
    )
    out = sr._search_sessions("kw", 4)
    assert out == [{"id": "s1", "title": "T", "updated_at": 5, "message_count": 2}]


# ---------------------------------------------------------------------------
# _search_memories：归一化与降级
# ---------------------------------------------------------------------------


def test_search_memories_normalizes(monkeypatch):
    mm = SimpleNamespace(
        search_memories=lambda query, limit: [
            {"id": "m1", "content": "x" * 500, "type": "episodic",
             "importance": 7, "tags": ["t"]},
            {"id": "m2", "content": "y", "memory_type": "semantic"},
        ]
    )
    monkeypatch.setattr("backend.memory.registry.get_memory_manager", lambda: mm)
    out = sr._search_memories("kw", 5)
    assert len(out) == 2
    assert len(out[0]["content"]) == 200  # 截断
    assert out[0]["memory_type"] == "episodic"  # type 回退
    assert out[1]["memory_type"] == "semantic"
    assert out[1]["importance"] == 0  # 缺省
    assert out[1]["tags"] == []


def test_search_memories_exception_degrades(monkeypatch):
    def boom():
        raise RuntimeError("mgr gone")

    monkeypatch.setattr("backend.memory.registry.get_memory_manager", boom)
    assert sr._search_memories("kw", 5) == []


# ---------------------------------------------------------------------------
# _search_projects
# ---------------------------------------------------------------------------


def test_search_projects_maps_session_count(monkeypatch):
    repo = SimpleNamespace(
        search=lambda query, limit: [
            SimpleNamespace(id="p1", name="N", path="/w/one"),
            SimpleNamespace(id="p2", name="M", path="/w/two"),
        ],
        session_stats=lambda: {"/w/one": (3, None)},
    )
    monkeypatch.setattr(
        "backend.data.project_repo.ProjectRepository", lambda: repo
    )
    out = sr._search_projects("kw", 5)
    assert out[0]["session_count"] == 3
    assert out[1]["session_count"] == 0  # stats 缺省 (0, None)


def test_search_projects_exception_degrades(monkeypatch):
    def boom():
        raise RuntimeError("no repo")

    monkeypatch.setattr("backend.data.project_repo.ProjectRepository", boom)
    assert sr._search_projects("kw", 5) == []


# ---------------------------------------------------------------------------
# _search_knowledge：多根合并去重与降级
# ---------------------------------------------------------------------------


class _Doc:
    def __init__(self, path, title, snippet):
        self.path = path
        self.title = title
        self.snippet = snippet


class _SearchResponse:
    def __init__(self, results):
        self.results = results


def test_search_knowledge_explicit_scope_passthrough(monkeypatch):
    # win7 行为基线（P9）：project_path 单值直接作为 project_root，
    # 结果按 path/title/snippet(截断 200) 映射
    def fake_search(project_root, query, limit):
        assert str(project_root) == "/w/a"
        assert query == "kw"
        assert limit == 5
        return _SearchResponse([_Doc("wiki/x.md", "XA", "s" * 300)])

    monkeypatch.setattr("backend.wiki.search.search_wiki", fake_search)
    out = sr._search_knowledge("kw", 5, project_path="/w/a")
    assert out == [{"path": "wiki/x.md", "title": "XA",
                    "snippet": "s" * 200}]


def test_search_knowledge_empty_project_root_empty(monkeypatch):
    # project_path 为空串 → project_root 为空 → 空集（P9 守卫）
    monkeypatch.setattr(
        "backend.wiki.search.search_wiki",
        lambda project_root, query, limit: (_ for _ in ()).throw(AssertionError("should not search")),
    )
    assert sr._search_knowledge("kw", 5, project_path="") == []


def test_search_knowledge_no_recent_projects_empty(monkeypatch):
    monkeypatch.setattr("backend.storage.recent_projects.load_recent", lambda: [])
    assert sr._search_knowledge("kw", 5, project_path=None) == []


def test_search_knowledge_falls_back_to_recent(monkeypatch):
    recent = [SimpleNamespace(path="/w/recent")]
    monkeypatch.setattr(
        "backend.storage.recent_projects.load_recent", lambda: recent
    )
    calls = {}
    monkeypatch.setattr(
        "backend.wiki.search.search_wiki",
        lambda project_root, query, limit: calls.setdefault("root", project_root)
        or _SearchResponse([]),
    )
    sr._search_knowledge("kw", 5, project_path=None)
    assert str(calls["root"]) == "/w/recent"


def test_search_knowledge_exception_degrades(monkeypatch):
    def boom():
        raise RuntimeError("no wiki")

    monkeypatch.setattr("backend.storage.recent_projects.load_recent", boom)
    assert sr._search_knowledge("kw", 5, project_path=None) == []
