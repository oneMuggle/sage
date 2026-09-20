"""Memory route contract tests for persistence boundaries."""

from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from backend.api import legacy_routes


class _MemoryManager:
    def __init__(self, result: str = "memory-1") -> None:
        self.result = result
        self.calls: List[Dict[str, Any]] = []

    def memorize(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self.result

    def search_memories(self, **kwargs: Any) -> List[Dict[str, Any]]:
        self.calls.append(kwargs)
        return [{"id": "memory-1", "content": "match"}]


def test_save_request_rejects_invalid_importance() -> None:
    with pytest.raises(ValidationError):
        legacy_routes.MemorySaveRequest(content="x", importance=0)


def test_save_request_rejects_empty_content() -> None:
    with pytest.raises(ValidationError):
        legacy_routes.MemorySaveRequest(content="")


def test_save_memory_forwards_session_id_and_returns_stable_envelope(monkeypatch) -> None:
    manager = _MemoryManager()
    monkeypatch.setattr(legacy_routes, "get_memory_manager", lambda: manager)

    response = legacy_routes.save_memory(
        legacy_routes.MemorySaveRequest(
            content="prefers dark mode",
            memory_type="semantic",
            importance=8,
            tags=["preference"],
            session_id="session-1",
        )
    )

    assert response == {"id": "memory-1", "status": "ok"}
    assert manager.calls == [
        {
            "content": "prefers dark mode",
            "memory_type": "semantic",
            "importance": 8,
            "tags": ["preference"],
            "session_id": "session-1",
        }
    ]


def test_search_memory_forwards_session_id_and_normalizes_limit(monkeypatch) -> None:
    manager = _MemoryManager()
    monkeypatch.setattr(legacy_routes, "get_memory_manager", lambda: manager)

    response = legacy_routes.search_memory(
        query="dark",
        limit=999,
        type="semantic",
        session_id="session-1",
    )

    assert response == [{"id": "memory-1", "content": "match"}]
    assert manager.calls == [
        {
            "query": "dark",
            "memory_type": "semantic",
            "limit": 100,
            "session_id": "session-1",
        }
    ]


def test_save_memory_rejects_unknown_type() -> None:
    with pytest.raises(legacy_routes.HTTPException) as exc_info:
        legacy_routes.save_memory(
            legacy_routes.MemorySaveRequest(content="x", memory_type="unknown")
        )

    assert exc_info.value.status_code == 422


def test_search_memory_error_message_does_not_leak_query(monkeypatch) -> None:
    class _ExplodingManager:
        def search_memories(self, **_: Any) -> List[Dict[str, Any]]:
            raise RuntimeError("internal FTS failure mentioning user query: 秘密口令")

    monkeypatch.setattr(legacy_routes, "get_memory_manager", lambda: _ExplodingManager())

    with pytest.raises(legacy_routes.HTTPException) as exc_info:
        legacy_routes.search_memory(query="秘密口令", limit=20)

    assert exc_info.value.status_code == 500
    # 错误详情必须稳定为通用提示,绝不携带原始查询或下游异常原文
    assert "秘密口令" not in exc_info.value.detail
    assert "internal FTS failure" not in exc_info.value.detail


class _DeletableManager:
    def __init__(self) -> None:
        self.calls: List[tuple] = []

    def delete_memory(self, memory_id: str, memory_type: str) -> bool:
        self.calls.append((memory_id, memory_type))
        return memory_type == "working"


def test_delete_memory_tries_working_layer(monkeypatch) -> None:
    manager = _DeletableManager()
    monkeypatch.setattr(legacy_routes, "get_memory_manager", lambda: manager)

    response = legacy_routes.delete_memory(legacy_routes.MemoryDeleteRequest(id="wm:s1:7"))

    assert response == {"status": "ok"}
    # 路由按 ["episodic", "semantic", "working"] 顺序依次尝试
    assert manager.calls == [
        ("wm:s1:7", "episodic"),
        ("wm:s1:7", "semantic"),
        ("wm:s1:7", "working"),
    ]
