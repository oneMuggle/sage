"""M3-Task 6: ``/memory/list?agent_id=`` 路由参数过滤契约测试。

覆盖范围:
- ``_filter_items_by_agent`` helper 的三种语义(None / 'shared' / 精确值)。
- ``list_memories`` 路由在 episodic / semantic / all 三个分支下的 agent_id
  过滤,以及 total 字段在过滤后以过滤后条数为准。
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.api import legacy_memory_list_routes as list_routes

# ---------------------------------------------------------------------------
# _filter_items_by_agent helper
# ---------------------------------------------------------------------------


class TestFilterItemsByAgent:
    """Helper 的三种语义(None / 'shared' / 精确值)。"""

    SAMPLE = [
        {"id": "a", "content": "shared row"},
        {"id": "b", "content": "primary row", "agent_id": "primary"},
        {"id": "c", "content": "specialist row", "agent_id": "specialist-x"},
        {"id": "d", "content": "another shared"},
    ]

    def test_none_returns_all(self) -> None:
        result = list_routes._filter_items_by_agent(self.SAMPLE, None)
        assert result == self.SAMPLE

    def test_shared_returns_only_null_agent_id(self) -> None:
        result = list_routes._filter_items_by_agent(self.SAMPLE, "shared")
        assert [it["id"] for it in result] == ["a", "d"]

    def test_exact_match_returns_only_that_agent(self) -> None:
        result = list_routes._filter_items_by_agent(self.SAMPLE, "specialist-x")
        assert [it["id"] for it in result] == ["c"]

    def test_exact_match_miss_returns_empty(self) -> None:
        result = list_routes._filter_items_by_agent(self.SAMPLE, "specialist-z")
        assert result == []


# ---------------------------------------------------------------------------
# list_memories route — agent_id query parameter
# ---------------------------------------------------------------------------


def _make_episodic_row(
    mem_id: str, content: str, agent_id: str | None = None
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": mem_id,
        "content": content,
        "importance": 5,
        "tags": [],
        "created_at": 1_700_000_000,
        "accessed_at": 1_700_000_000,
        "access_count": 0,
    }
    if agent_id is not None:
        row["agent_id"] = agent_id
    return row


class _FakeEpisodicStore:
    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = rows

    def get_recent(self, *, limit: int, session_id: str | None = None) -> List[Dict[str, Any]]:
        return self._rows[:limit]

    def count(self, *, session_id: str | None = None) -> int:
        return len(self._rows)


class _FakeSemanticStore:
    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = rows

    def get_recent(self, *, limit: int, session_id: str | None = None) -> List[Dict[str, Any]]:
        return self._rows[:limit]

    def count(self, *, session_id: str | None = None) -> int:
        return len(self._rows)


class _FakeWorkingMemory:
    messages: List[Dict[str, Any]] = []

    def get_context(self, *, session_id: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
        return []


class _FakeMemoryManager:
    def __init__(
        self,
        episodic_rows: List[Dict[str, Any]],
        semantic_rows: List[Dict[str, Any]] | None = None,
    ) -> None:
        self.episodic = _FakeEpisodicStore(episodic_rows)
        self.semantic = _FakeSemanticStore(semantic_rows or [])
        self.working = _FakeWorkingMemory()
        self.summary_store = None


def _install_fake_manager(monkeypatch, episodic_rows, semantic_rows=None):
    fake = _FakeMemoryManager(episodic_rows, semantic_rows)
    monkeypatch.setattr(list_routes, "get_memory_manager", lambda: fake)
    return fake


class TestListMemoriesAgentFilter:
    """list_memories 路由的 agent_id query 参数过滤。"""

    def test_no_filter_returns_all_rows(self, monkeypatch) -> None:
        _install_fake_manager(
            monkeypatch,
            [
                _make_episodic_row("a", "shared"),
                _make_episodic_row("b", "primary", agent_id="primary"),
            ],
        )

        resp = list_routes.list_memories(page=1, page_size=20, type="episodic")

        ids = [it["id"] for it in resp["items"]]
        assert ids == ["a", "b"]
        assert resp["total"] == 2

    def test_agent_id_shared_returns_only_null_rows(self, monkeypatch) -> None:
        _install_fake_manager(
            monkeypatch,
            [
                _make_episodic_row("a", "shared"),
                _make_episodic_row("b", "primary", agent_id="primary"),
                _make_episodic_row("c", "also shared"),
            ],
        )

        resp = list_routes.list_memories(
            page=1, page_size=20, type="episodic", agent_id="shared"
        )

        ids = [it["id"] for it in resp["items"]]
        assert ids == ["a", "c"]
        # M3-Task 6 契约: 过滤后 total 以过滤后条数为准(不泄漏未过滤总数)
        assert resp["total"] == 2

    def test_agent_id_exact_returns_only_that_agent(self, monkeypatch) -> None:
        _install_fake_manager(
            monkeypatch,
            [
                _make_episodic_row("a", "shared"),
                _make_episodic_row("b", "primary", agent_id="primary"),
                _make_episodic_row("c", "specialist", agent_id="specialist-x"),
            ],
        )

        resp = list_routes.list_memories(
            page=1, page_size=20, type="episodic", agent_id="specialist-x"
        )

        ids = [it["id"] for it in resp["items"]]
        assert ids == ["c"]
        assert resp["total"] == 1

    def test_agent_id_miss_returns_empty(self, monkeypatch) -> None:
        _install_fake_manager(
            monkeypatch,
            [_make_episodic_row("a", "shared")],
        )

        resp = list_routes.list_memories(
            page=1, page_size=20, type="episodic", agent_id="nonexistent"
        )

        assert resp["items"] == []
        assert resp["total"] == 0

    def test_agent_id_works_in_all_branch(self, monkeypatch) -> None:
        """type='all' 合并四层时,agent_id 同样生效。"""
        _install_fake_manager(
            monkeypatch,
            episodic_rows=[
                _make_episodic_row("e1", "shared epi"),
                _make_episodic_row("e2", "primary epi", agent_id="primary"),
            ],
            semantic_rows=[
                _make_episodic_row("s1", "shared sem"),
                _make_episodic_row("s2", "primary sem", agent_id="primary"),
            ],
        )

        resp = list_routes.list_memories(
            page=1, page_size=20, type=None, agent_id="shared"
        )

        ids = sorted(it["id"] for it in resp["items"])
        assert ids == ["e1", "s1"]
        assert resp["total"] == 2
        assert resp["layer"] == "all"

    def test_all_branch_source_breakdown_follows_filter(self, monkeypatch) -> None:
        """type='all' 过滤态下 source_breakdown 必须与 filtered total 同源。

        计数若用未过滤的行数，会把其它专家的私有行数量泄漏给当前 UI。
        """
        _install_fake_manager(
            monkeypatch,
            episodic_rows=[
                _make_episodic_row("e1", "shared epi"),
                _make_episodic_row("e2", "other epi", agent_id="primary"),
                _make_episodic_row("e3", "mine epi", agent_id="specialist-x"),
            ],
            semantic_rows=[
                _make_episodic_row("s1", "shared sem"),
                _make_episodic_row("s2", "mine sem", agent_id="specialist-x"),
            ],
        )

        resp = list_routes.list_memories(
            page=1, page_size=20, type=None, agent_id="specialist-x"
        )

        assert resp["total"] == 2
        assert resp["source_breakdown"] == {
            "working": 0,
            "session_summary": 0,
            "episodic": 1,
            "semantic": 1,
        }
        # 不变式：过滤态下各来源计数之和必须等于 total
        assert sum(resp["source_breakdown"].values()) == resp["total"]

    def test_all_branch_source_breakdown_unfiltered_counts_all(self, monkeypatch) -> None:
        """无过滤时 source_breakdown 仍按各来源真实行数统计（回归护栏）。"""
        _install_fake_manager(
            monkeypatch,
            episodic_rows=[
                _make_episodic_row("e1", "shared epi"),
                _make_episodic_row("e2", "other epi", agent_id="primary"),
            ],
            semantic_rows=[
                _make_episodic_row("s1", "shared sem"),
            ],
        )

        resp = list_routes.list_memories(page=1, page_size=20, type=None)

        assert resp["total"] == 3
        assert resp["source_breakdown"] == {
            "working": 0,
            "session_summary": 0,
            "episodic": 2,
            "semantic": 1,
        }
