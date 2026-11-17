"""startup_status 注册表单元测试（Progressive Readiness）。"""

import pytest

from backend.services.startup_status import (
    STATE_DEGRADED,
    STATE_FAILED,
    STATE_READY,
    STATE_WARMING,
    StartupStatusRegistry,
)


def _registry_with_all_modules() -> StartupStatusRegistry:
    registry = StartupStatusRegistry()
    for name in ("database", "memory", "sessions", "chat_service", "llm", "mcp", "storage"):
        registry.declare(name)
    return registry


def test_phase_l1_when_layer1_ready() -> None:
    registry = _registry_with_all_modules()
    for name in ("database", "memory", "sessions"):
        registry.mark(name, STATE_READY)

    snap = registry.snapshot()
    assert snap["phase"] == "L1"
    assert snap["status"] == "warming"
    assert snap["modules"]["database"]["state"] == "ready"
    assert isinstance(snap["modules"]["database"]["elapsed_ms"], int)
    assert snap["warmup"] == {"done": 3, "total": 7}


def test_phase_l2_requires_chat_and_llm() -> None:
    registry = _registry_with_all_modules()
    for name in ("database", "memory", "sessions", "chat_service"):
        registry.mark(name, STATE_READY)
    # llm 仍未就绪 → L2 尚未完整，停留在 L1
    assert registry.snapshot()["phase"] == "L1"

    registry.mark("llm", STATE_READY)
    snap = registry.snapshot()
    assert snap["phase"] == "L2"  # L3 尚未全部终态
    assert snap["status"] == "warming"


def test_l3_ready_when_all_terminal_and_clean() -> None:
    registry = _registry_with_all_modules()
    for name in ("database", "memory", "sessions", "chat_service", "llm", "mcp", "storage"):
        registry.mark(name, STATE_READY)

    snap = registry.snapshot()
    assert snap["phase"] == "L3"
    assert snap["status"] == "ready"
    assert snap["warmup"] == {"done": 7, "total": 7}


def test_l3_degraded_when_any_module_degraded_or_failed() -> None:
    registry = _registry_with_all_modules()
    for name in ("database", "memory", "sessions", "chat_service", "llm", "storage"):
        registry.mark(name, STATE_READY)
    registry.mark("mcp", STATE_DEGRADED, {"servers": []})

    snap = registry.snapshot()
    assert snap["phase"] == "L3"
    assert snap["status"] == "degraded"
    assert snap["modules"]["mcp"]["state"] == STATE_DEGRADED

    registry.mark("storage", STATE_FAILED)
    assert registry.snapshot()["status"] == "degraded"


def test_warming_records_started_at_and_detail() -> None:
    registry = StartupStatusRegistry()
    registry.mark("mcp", STATE_WARMING, {"servers": [{"name": "demo", "state": "discovering"}]})
    snap = registry.snapshot()
    entry = snap["modules"]["mcp"]
    assert entry["state"] == STATE_WARMING
    assert entry["layer"] == 3
    assert isinstance(entry["elapsed_ms"], int)
    assert entry["detail"]["servers"][0]["name"] == "demo"


def test_unknown_state_raises() -> None:
    registry = StartupStatusRegistry()
    with pytest.raises(ValueError, match="exploded"):
        registry.mark("database", "exploded")


def test_terminal_state_cannot_regress_to_warming() -> None:
    """迟到的 warming 上报（如后台观察协程晚于 finalize 启动）不得把
    已终态的模块拉回未完成——否则 phase 会从 L3 回退、elapsed 被冻结。"""
    registry = StartupStatusRegistry()
    registry.mark("mcp", STATE_READY, {"servers": []})
    ready_snapshot = registry.snapshot()
    finished = ready_snapshot["modules"]["mcp"]["elapsed_ms"]

    registry.mark("mcp", STATE_WARMING, {"servers": []})
    snap = registry.snapshot()
    assert snap["modules"]["mcp"]["state"] == STATE_READY
    assert snap["modules"]["mcp"]["elapsed_ms"] == finished
