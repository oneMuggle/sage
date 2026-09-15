"""SessionSearchTool 单元测试（Round 2）"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from backend.tools.session_search_tool import SessionSearchTool

pytestmark = pytest.mark.unit


class FakeIndex:
    def __init__(self, results=None):
        self.results = results or []
        self.calls: List[Dict[str, Any]] = []

    def search(self, query, session_id=None, limit=10):
        self.calls.append({"query": query, "session_id": session_id, "limit": limit})
        return self.results


@pytest.fixture()
def tool():
    return SessionSearchTool(index=FakeIndex())


class TestSessionSearchTool:
    def test_basic_search(self):
        idx = FakeIndex(
            results=[
                {
                    "message_id": "m1",
                    "session_id": "s1",
                    "role": "user",
                    "created_at": 1700000000,
                    "excerpt": "…构建报错的解决方案…",
                }
            ]
        )
        tool = SessionSearchTool(index=idx)
        result = tool.execute(query="构建报错")
        assert result.success is True
        assert result.content["total"] == 1
        assert result.content["matches"][0]["message_id"] == "m1"
        assert idx.calls[0]["limit"] == 10

    def test_empty_query_rejected(self, tool):
        result = tool.execute(query="   ")
        assert result.success is False
        assert "query" in (result.error or "")

    def test_limit_clamped(self):
        idx = FakeIndex()
        tool = SessionSearchTool(index=idx)
        tool.execute(query="x", limit=999)
        assert idx.calls[0]["limit"] == 50
        tool.execute(query="x", limit=0)
        assert idx.calls[1]["limit"] == 1

    def test_session_id_passthrough(self):
        idx = FakeIndex()
        tool = SessionSearchTool(index=idx)
        tool.execute(query="配置", session_id="sess-42")
        assert idx.calls[0]["session_id"] == "sess-42"

    def test_index_exception_surfaces_as_error(self):
        class BrokenIndex:
            def search(self, *args, **kwargs):
                raise RuntimeError("boom")

        tool = SessionSearchTool(index=BrokenIndex())
        result = tool.execute(query="x")
        assert result.success is False
        assert "会话搜索失败" in (result.error or "")
