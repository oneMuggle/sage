"""EvolutionRunRegistry 单元测试（2026-11-26 进化任务进度可见）。"""
from __future__ import annotations

from backend.scheduler.evolution_run_registry import (
    STATE_CANCELLED,
    STATE_FAILED,
    STATE_RUNNING,
    STATE_SUCCEEDED,
    EvolutionRunRegistry,
    serialize_evolution_result,
)


def test_begin_creates_running_snapshot() -> None:
    reg = EvolutionRunRegistry()
    run_id = reg.begin("memory_reflection", "manual")

    assert run_id
    snap = reg.snapshot("memory_reflection")
    assert snap is not None
    assert snap["run_id"] == run_id
    assert snap["state"] == STATE_RUNNING
    assert snap["trigger"] == "manual"
    assert snap["phase"] == "start"
    assert isinstance(snap["started_at"], int)
    assert snap["finished_at"] is None
    assert reg.is_running("memory_reflection") is True


def test_begin_is_mutually_exclusive_until_finish() -> None:
    reg = EvolutionRunRegistry()
    first = reg.begin("memory_pruning")
    assert first is not None

    assert reg.begin("memory_pruning") is None

    reg.finish("memory_pruning", first)
    second = reg.begin("memory_pruning")
    assert second is not None
    assert second != first


def test_update_applies_only_to_current_run() -> None:
    reg = EvolutionRunRegistry()
    old = reg.begin("memory_reflection")
    assert old is not None
    reg.finish("memory_reflection", old)
    new = reg.begin("memory_reflection")
    assert new is not None

    # 旧 run 的迟到上报必须被丢弃
    reg.update("memory_reflection", old, "llm", "陈旧阶段", {"llm_done": 99})
    snap = reg.snapshot("memory_reflection")
    assert snap["phase"] == "start"
    assert snap["progress"] == {}

    reg.update("memory_reflection", new, "collect", "扫描记忆", {"scanned": 5})
    snap = reg.snapshot("memory_reflection")
    assert snap["phase"] == "collect"
    assert snap["phase_label"] == "扫描记忆"
    assert snap["progress"] == {"scanned": 5}

    # 进度是增量合并
    reg.update("memory_reflection", new, "llm", "LLM 合并", {"llm_done": 1, "llm_total": 2})
    snap = reg.snapshot("memory_reflection")
    assert snap["progress"] == {"scanned": 5, "llm_done": 1, "llm_total": 2}


def test_update_ignored_after_finish() -> None:
    reg = EvolutionRunRegistry()
    run_id = reg.begin("daily_summary")
    assert run_id is not None
    reg.finish("daily_summary", run_id, result=None)

    reg.update("daily_summary", run_id, "llm", "迟到的阶段")
    snap = reg.snapshot("daily_summary")
    assert snap["state"] == STATE_SUCCEEDED
    assert snap["phase"] == "done"


def test_finish_success_records_duration_and_result() -> None:
    reg = EvolutionRunRegistry()
    run_id = reg.begin("memory_consolidation")
    assert run_id is not None
    reg.finish("memory_consolidation", run_id, result={"promoted": 2, "decayed": 1})

    snap = reg.snapshot("memory_consolidation")
    assert snap["state"] == STATE_SUCCEEDED
    assert snap["result"] == {"promoted": 2, "decayed": 1}
    assert snap["error"] is None
    assert snap["finished_at"] is not None
    assert isinstance(snap["duration_ms"], int)
    assert snap["duration_ms"] >= 0
    assert reg.is_running("memory_consolidation") is False


def test_finish_failure_records_error() -> None:
    reg = EvolutionRunRegistry()
    run_id = reg.begin("memory_pruning")
    assert run_id is not None
    reg.finish("memory_pruning", run_id, error="boom")

    snap = reg.snapshot("memory_pruning")
    assert snap["state"] == STATE_FAILED
    assert snap["error"] == "boom"
    assert snap["phase_label"] == "失败"


def test_snapshot_is_defensive_copy() -> None:
    reg = EvolutionRunRegistry()
    run_id = reg.begin("memory_reflection")
    assert run_id is not None
    reg.update("memory_reflection", run_id, "collect", "扫描记忆", {"scanned": 1})

    snap = reg.snapshot("memory_reflection")
    assert snap is not None
    snap["progress"]["scanned"] = 99
    snap["state"] = "hacked"

    fresh = reg.snapshot("memory_reflection")
    assert fresh["progress"]["scanned"] == 1
    assert fresh["state"] == STATE_RUNNING


def test_serialize_result_variants() -> None:
    class ConsolidationLike(int):
        def as_dict(self) -> dict:
            return {"promoted": 1, "decayed": 2, "total": 3}

    assert serialize_evolution_result(ConsolidationLike(3)) == {
        "promoted": 1,
        "decayed": 2,
        "total": 3,
    }
    assert serialize_evolution_result(4) == {"total": 4}
    assert serialize_evolution_result({"a": 1}) == {"a": 1}
    assert serialize_evolution_result(None) is None
    assert serialize_evolution_result(True) == {"value": True}
    assert serialize_evolution_result("x") == {"value": "x"}


def test_snapshots_returns_all_known_runs() -> None:
    reg = EvolutionRunRegistry()
    reg.begin("a")
    reg.begin("b")

    snaps = reg.snapshots()
    assert set(snaps.keys()) == {"a", "b"}


def test_request_cancel_sets_flag_only_while_running() -> None:
    reg = EvolutionRunRegistry()
    run_id = reg.begin("memory_reflection")
    assert run_id is not None

    assert reg.request_cancel("memory_reflection") is True
    snap = reg.snapshot("memory_reflection")
    assert snap["cancel_requested"] is True
    assert reg.is_cancel_requested("memory_reflection", run_id) is True

    reg.finish("memory_reflection", run_id, cancelled=True)
    assert reg.request_cancel("memory_reflection") is False


def test_is_cancel_requested_scoped_to_run_id() -> None:
    reg = EvolutionRunRegistry()
    run_id = reg.begin("memory_reflection")
    assert run_id is not None
    reg.request_cancel("memory_reflection")

    assert reg.is_cancel_requested("memory_reflection", "other-run") is False
    assert reg.is_cancel_requested("memory_reflection", run_id) is True


def test_finish_cancelled_state_wins_over_error() -> None:
    reg = EvolutionRunRegistry()
    run_id = reg.begin("memory_pruning")
    assert run_id is not None

    reg.finish("memory_pruning", run_id, error="ignored", cancelled=True)
    snap = reg.snapshot("memory_pruning")
    assert snap["state"] == STATE_CANCELLED
    assert snap["phase_label"] == "已取消"
    assert snap["error"] is None
