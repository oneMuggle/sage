"""PUT /memory/{memory_id} 记忆编辑端点测试（2026-11-17 记忆详情化）。

用假 MemoryManager 覆盖路由行为：
- 空 payload → 422；
- episodic 优先命中，成功后返回与列表一致形状（含 title 兜底）；
- episodic 未命中时落 semantic；语义层无 importance → 显式 422；
- 两层都不存在 → 404。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

# 2026-11-17: 更新端点已拆分为独立模块（legacy_memory_update_routes）。
from backend.api import legacy_memory_update_routes as legacy_routes

pytestmark = pytest.mark.unit


class _Store:
    def __init__(self) -> None:
        self.update_calls: List[Dict[str, Any]] = []
        self.update_result = True
        self.records: Dict[str, Dict[str, Any]] = {}

    def update(self, memory_id: str, **kwargs: Any) -> bool:
        self.update_calls.append({"memory_id": memory_id, **kwargs})
        if self.update_result and memory_id in self.records:
            # 模拟真实存储层：非 None 字段落到记录上，供 get_by_id 回读。
            for key, value in kwargs.items():
                if value is not None:
                    self.records[memory_id][key] = value
        return self.update_result

    def get_by_id(self, memory_id: str) -> Optional[Dict[str, Any]]:
        return self.records.get(memory_id)


class _Manager:
    def __init__(self) -> None:
        self.episodic = _Store()
        self.semantic = _Store()


def _install(monkeypatch) -> _Manager:
    manager = _Manager()
    monkeypatch.setattr(legacy_routes, "get_memory_manager", lambda: manager)
    return manager


def test_update_rejects_empty_payload(monkeypatch) -> None:
    manager = _install(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        legacy_routes.update_memory("m1", legacy_routes.MemoryUpdateRequest())
    assert exc.value.status_code == 422
    assert manager.episodic.update_calls == []


def test_update_episodic_returns_enriched_record(monkeypatch) -> None:
    manager = _install(monkeypatch)
    manager.episodic.records["m1"] = {
        "id": "m1",
        "content": "修正后的内容",
        "title": "",
        "importance": 7,
        "created_at": 1700000000000,
        "session_id": "sess-1",
    }

    response = legacy_routes.update_memory(
        "m1",
        legacy_routes.MemoryUpdateRequest(content="修正后的内容", title="新标题"),
    )

    assert manager.episodic.update_calls == [
        {
            "memory_id": "m1",
            "content": "修正后的内容",
            "title": "新标题",
            "tags": None,
            "importance": None,
        }
    ]
    assert manager.semantic.update_calls == []
    assert response["id"] == "m1"
    assert response["title"] == "新标题"
    assert response["source"] == "episodic"
    assert response["layer"] == "episodic"


def test_update_falls_back_to_semantic(monkeypatch) -> None:
    manager = _install(monkeypatch)
    manager.episodic.update_result = False
    manager.semantic.records["m2"] = {
        "id": "m2",
        "content": "Rust 是编译型系统语言",
        "title": "Rust 是编译型系统语言",
        "created_at": 1700000000000,
    }

    response = legacy_routes.update_memory(
        "m2",
        legacy_routes.MemoryUpdateRequest(content="Rust 是编译型系统语言"),
    )

    assert manager.episodic.update_calls[0]["memory_id"] == "m2"
    assert manager.semantic.update_calls == [
        {
            "memory_id": "m2",
            "content": "Rust 是编译型系统语言",
            "title": None,
            "tags": None,
        }
    ]
    assert response["source"] == "semantic"


def test_update_semantic_rejects_importance(monkeypatch) -> None:
    manager = _install(monkeypatch)
    manager.episodic.update_result = False
    manager.semantic.records["m2"] = {"id": "m2", "content": "某语义事实"}

    with pytest.raises(HTTPException) as exc:
        legacy_routes.update_memory(
            "m2", legacy_routes.MemoryUpdateRequest(importance=8)
        )
    assert exc.value.status_code == 422
    # 语义层 update 不应被调用（避免"看起来改了"的静默忽略）
    assert manager.semantic.update_calls == []


def test_update_missing_memory_returns_404(monkeypatch) -> None:
    manager = _install(monkeypatch)
    manager.episodic.update_result = False

    with pytest.raises(HTTPException) as exc:
        legacy_routes.update_memory(
            "missing", legacy_routes.MemoryUpdateRequest(content="x")
        )
    assert exc.value.status_code == 404
