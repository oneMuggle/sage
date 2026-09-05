"""Tests for the SQLite-backed orchestration step repository."""

from __future__ import annotations

from backend.data.orch_run_repo import OrchRun, OrchRunRepository
from backend.data.orch_steps_repo import OrchStep, OrchStepRepository
from backend.data.orch_task_repo import OrchTaskRepository


def _seed_parents(run_id: str = "run-1", task_id: str = "task-1") -> None:
    OrchRunRepository().upsert(
        OrchRun(run_id=run_id, session_id="session-1", status="running", created_at=1, plan_json="{}")
    )
    OrchTaskRepository().upsert_state(task_id, run_id, "agent-1", "goal", "queued")


def test_upsert_and_get_step_roundtrip(tmp_db_path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_DB_PATH", tmp_db_path)
    repo = OrchStepRepository()
    _seed_parents()
    step = OrchStep(
        step_id="step-1", run_id="run-1", task_id="task-1", name="search",
        status="running", input_summary='{"q":"sage"}', output_preview=None,
        error_code=None, started_at=100,
    )

    repo.upsert(step)
    assert repo.get("step-1") == step


def test_upsert_updates_mutable_state(tmp_db_path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_DB_PATH", tmp_db_path)
    repo = OrchStepRepository()
    _seed_parents()
    repo.upsert(OrchStep("step-1", "run-1", "task-1", "search"))
    repo.upsert(OrchStep(
        "step-1", "run-1", "task-1", "search", status="succeeded",
        output_preview='{"hits":2}', finished_at=200,
    ))

    row = repo.get("step-1")
    assert row is not None
    assert row.status == "succeeded"
    assert row.output_preview == '{"hits":2}'
    assert row.finished_at == 200


def test_list_by_task_orders_steps(tmp_db_path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_DB_PATH", tmp_db_path)
    repo = OrchStepRepository()
    _seed_parents()
    _seed_parents("run-2", "task-2")
    repo.upsert(OrchStep("step-2", "run-1", "task-1", "step-2", sequence=2))
    repo.upsert(OrchStep("step-1", "run-1", "task-1", "step-1", sequence=1))
    repo.upsert(OrchStep("step-3", "run-2", "task-2", "step-3"))

    assert [step.step_id for step in repo.list_by_task("task-1")] == ["step-1", "step-2"]
    assert repo.get("missing") is None
