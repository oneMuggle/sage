"""R17-E: memory_used 流事件构造 helper 单元测试

覆盖 backend/api/legacy_routes.py::_build_memory_used_event:
- 无 memory_manager / 无 recall 方法 → None（不产事件）
- 正常 recall 命中 → 事件含 state/session_id/memories 结构
- 多类型命中截断（总体 5 条）与 preview 截断（80 字）
- recall 抛异常 → None（fail-safe，不影响对话主流程）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from backend.api.legacy_routes import _build_memory_used_event

pytestmark = pytest.mark.unit


class _FakeMemoryManager:
    def __init__(self, hits: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                 error: Optional[Exception] = None) -> None:
        self._hits = hits or {}
        self._error = error

    def recall(self, query: str, limit: int = 5,
               session_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        if self._error is not None:
            raise self._error
        return self._hits


def test_returns_none_without_memory_manager():
    assert _build_memory_used_event(None, query="你好", session_id="s1") is None


def test_returns_none_when_recall_missing():
    class _NoRecall:
        pass

    assert _build_memory_used_event(_NoRecall(), query="你好", session_id="s1") is None


def test_builds_event_from_hits():
    mgr = _FakeMemoryManager(
        {
            "semantic": [
                {"id": "m1", "memory_type": "semantic", "content": "用户偏好深色主题"},
                {"id": "m2", "content": "项目代号 Sage"},  # 无 memory_type → 用分组名
            ],
            "working": [{"id": "w1", "content": "正在做记忆功能"}],
        }
    )
    evt = _build_memory_used_event(mgr, query="主题设置", session_id="s1")
    assert evt is not None
    assert evt["state"] == "memory_used"
    assert evt["session_id"] == "s1"
    assert len(evt["memories"]) == 3
    first = evt["memories"][0]
    assert first == {"id": "m1", "memory_type": "semantic", "preview": "用户偏好深色主题"}
    assert evt["memories"][1]["memory_type"] == "semantic"  # 分组名兜底


def test_per_type_top3_and_80_char_preview():
    hits = {
        "semantic": [
            {"id": f"m{i}", "content": "长" * 200} for i in range(10)
        ],
        "working": [
            {"id": f"w{i}", "content": "短"} for i in range(4)
        ],
    }
    evt = _build_memory_used_event(_FakeMemoryManager(hits), query="q", session_id="s1")
    assert evt is not None
    # 每类 top3: semantic 3 + working 3 = 6 → 总体截断 5
    assert len(evt["memories"]) == 5
    assert all(len(m["preview"]) <= 80 for m in evt["memories"])


def test_skips_blank_entries_and_non_dicts():
    hits = {
        "semantic": [
            "not-a-dict",
            {"id": "m1", "content": "   "},  # 空白内容跳过
            {"id": "m2", "content": "有效内容"},
        ]
    }
    evt = _build_memory_used_event(_FakeMemoryManager(hits), query="q", session_id="s1")
    assert evt is not None
    assert evt["memories"] == [
        {"id": "m2", "memory_type": "semantic", "preview": "有效内容"}
    ]


def test_returns_none_on_recall_error():
    mgr = _FakeMemoryManager(error=RuntimeError("db locked"))
    assert _build_memory_used_event(mgr, query="q", session_id="s1") is None
