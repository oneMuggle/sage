"""M3-Task 7: ``/memory/save`` 的 agent_id 透传契约。

资产中心「手动追加专家私有记忆」依赖 ``agent_id`` 从请求体一路透传到
``MemoryManager.memorize`` / ``memorize_with_conflict_check``：
- 显式 ``agent_id`` → 写入该专家私有层；
- 缺省 ``None`` → 共享层（历史行为不变）。
"""

from typing import Any, Dict, List, Tuple

from backend.api import legacy_memory_routes as legacy_routes


class _RecordingManager:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def memorize(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "memory-private-1"

    def memorize_with_conflict_check(self, **kwargs: Any) -> Tuple[str, str]:
        self.calls.append(kwargs)
        return "memory-private-1", "add"


def _install(monkeypatch) -> _RecordingManager:
    manager = _RecordingManager()
    monkeypatch.setattr(legacy_routes, "get_memory_manager", lambda: manager)
    return manager


def test_save_memory_forwards_agent_id_to_private_layer(monkeypatch) -> None:
    manager = _install(monkeypatch)

    response = legacy_routes.save_memory(
        legacy_routes.MemorySaveRequest(
            content="项目代号必须拼成 SAGE",
            memory_type="semantic",
            agent_id="specialist-writer",
        )
    )

    assert response == {"id": "memory-private-1", "status": "ok"}
    assert manager.calls[0]["agent_id"] == "specialist-writer"


def test_save_memory_defaults_agent_id_to_shared_layer(monkeypatch) -> None:
    manager = _install(monkeypatch)

    legacy_routes.save_memory(legacy_routes.MemorySaveRequest(content="共享事实"))

    assert manager.calls[0]["agent_id"] is None


def test_save_memory_conflict_check_forwards_agent_id(monkeypatch) -> None:
    manager = _install(monkeypatch)

    response = legacy_routes.save_memory(
        legacy_routes.MemorySaveRequest(
            content="偏好中文",
            memory_type="episodic",
            conflict_check=True,
            agent_id="specialist-writer",
        )
    )

    assert response["op"] == "add"
    assert manager.calls[0]["agent_id"] == "specialist-writer"
