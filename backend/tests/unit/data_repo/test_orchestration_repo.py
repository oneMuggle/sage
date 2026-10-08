"""R185 — 编排持久层单元测试（`backend/data/orchestration_repo.py`）。

真实临时库（conftest autouse `setup_test_db`），不 mock SQL。
含 get_ready_tasks 依赖判定修复的回归用例（修复前带依赖任务永远
ready 不了）。
"""

from __future__ import annotations

import pytest

from backend.data.orchestration_repo import TaskRepository, TeamRepository
from backend.orchestration.models import (
    EscalationPolicy,
    RecoveryPolicy,
    Task,
    TaskPacket,
    TaskStatus,
    Team,
    TeamStatus,
)

pytestmark = pytest.mark.unit


def _task(task_id: str, **overrides) -> Task:
    defaults = {
        "task_id": task_id,
        "name": f"task-{task_id}",
        "description": "desc",
        "status": TaskStatus.CREATED,
        "priority": 1,
        "executor_type": "agent",
        "parameters": {"k": "v"},
        "packet": None,
        "blocks": [],
        "blocked_by": [],
        "result": None,
        "created_at": 1000,
        "started_at": None,
        "completed_at": None,
        "team_id": None,
    }
    defaults.update(overrides)
    return Task(**defaults)


@pytest.fixture()
def task_repo() -> TaskRepository:
    return TaskRepository()


@pytest.fixture()
def team_repo() -> TeamRepository:
    return TeamRepository()


# ---------------------------------------------------------------------------
# TaskRepository CRUD
# ---------------------------------------------------------------------------


def test_task_create_get_roundtrip(task_repo: TaskRepository) -> None:
    packet = TaskPacket(
        objective="目标",
        scope=["a"],
        acceptance_tests=["t1"],
        model="m1",
        permission_profile="workspace-write",
        timeout_secs=120,
        recovery_policy=RecoveryPolicy(),
        escalation_policy=EscalationPolicy(),
    )
    task_repo.create(_task("t1", packet=packet, result={"ok": True}))

    loaded = task_repo.get("t1")
    assert loaded is not None
    assert loaded.name == "task-t1"
    assert loaded.status is TaskStatus.CREATED
    assert loaded.parameters == {"k": "v"}
    # create 的 INSERT 列清单不含 result —— result 只经 update 落库
    assert loaded.result is None
    assert loaded.packet is not None
    assert loaded.packet.objective == "目标"
    assert loaded.packet.timeout_secs == 120
    assert loaded.packet.recovery_policy == RecoveryPolicy()


def test_task_create_idempotent_on_same_id(task_repo: TaskRepository) -> None:
    task_repo.create(_task("t1", name="first"))
    task_repo.create(_task("t1", name="second"))  # INSERT OR REPLACE
    loaded = task_repo.get("t1")
    assert loaded is not None
    assert loaded.name == "second"
    assert len(task_repo.list()) == 1


def test_task_get_missing_returns_none(task_repo: TaskRepository) -> None:
    assert task_repo.get("ghost") is None


def test_task_update(task_repo: TaskRepository) -> None:
    task_repo.create(_task("t1"))
    task = task_repo.get("t1")
    assert task is not None
    task.status = TaskStatus.COMPLETED
    task.result = {"answer": 42}
    task.completed_at = 2000
    assert task_repo.update(task) is True

    loaded = task_repo.get("t1")
    assert loaded is not None
    assert loaded.status is TaskStatus.COMPLETED
    assert loaded.result == {"answer": 42}
    assert loaded.completed_at == 2000


def test_task_update_missing_returns_false(task_repo: TaskRepository) -> None:
    assert task_repo.update(_task("ghost")) is False


def test_task_delete(task_repo: TaskRepository) -> None:
    task_repo.create(_task("t1"))
    assert task_repo.delete("t1") is True
    assert task_repo.delete("t1") is False
    assert task_repo.get("t1") is None


def test_task_list_filters_and_ordering(task_repo: TaskRepository) -> None:
    task_repo.create(_task("low", priority=1, status=TaskStatus.CREATED, created_at=100))
    task_repo.create(_task("high", priority=9, status=TaskStatus.CREATED, created_at=200))
    task_repo.create(_task("done", priority=5, status=TaskStatus.COMPLETED, created_at=300))
    task_repo.create(_task("other-team", priority=5, team_id="team-b", created_at=400))

    # priority DESC 优先，同优先级按 created_at ASC
    assert [t.task_id for t in task_repo.list()] == ["high", "done", "other-team", "low"]

    by_status = task_repo.list(status=TaskStatus.COMPLETED)
    assert [t.task_id for t in by_status] == ["done"]

    by_team = task_repo.list(team_id="team-b")
    assert [t.task_id for t in by_team] == ["other-team"]

    paged = task_repo.list(limit=2, offset=1)
    assert [t.task_id for t in paged] == ["done", "other-team"]


# ---------------------------------------------------------------------------
# get_ready_tasks（含依赖判定修复回归）
# ---------------------------------------------------------------------------


def test_ready_task_without_dependencies(task_repo: TaskRepository) -> None:
    task_repo.create(_task("free"))
    assert [t.task_id for t in task_repo.get_ready_tasks()] == ["free"]


def test_ready_task_with_completed_dependency(task_repo: TaskRepository) -> None:
    # 回归：修复前 dep=COMPLETED 不在 CREATED 集合里 → main 永远不 ready
    task_repo.create(_task("dep", status=TaskStatus.COMPLETED))
    task_repo.create(_task("main", blocked_by=["dep"]))
    assert [t.task_id for t in task_repo.get_ready_tasks()] == ["main"]


def test_not_ready_while_dependency_created(task_repo: TaskRepository) -> None:
    task_repo.create(_task("dep", status=TaskStatus.CREATED))
    task_repo.create(_task("main", blocked_by=["dep"]))
    ready = {t.task_id for t in task_repo.get_ready_tasks()}
    # dep 自身无依赖 → ready；main 的依赖未完成 → 不 ready
    assert ready == {"dep"}


def test_not_ready_when_dependency_failed_or_missing(task_repo: TaskRepository) -> None:
    task_repo.create(_task("broken", status=TaskStatus.FAILED))
    task_repo.create(_task("main", blocked_by=["broken"]))
    task_repo.create(_task("main2", blocked_by=["ghost-dep"]))
    ready = {t.task_id for t in task_repo.get_ready_tasks()}
    assert ready == set()


def test_ready_tasks_team_filter(task_repo: TaskRepository) -> None:
    task_repo.create(_task("a", team_id="team-a"))
    task_repo.create(_task("b", team_id="team-b"))
    ready = {t.task_id for t in task_repo.get_ready_tasks(team_id="team-a")}
    assert ready == {"a"}


def test_completed_task_never_returned_as_ready(task_repo: TaskRepository) -> None:
    task_repo.create(_task("done", status=TaskStatus.COMPLETED))
    assert task_repo.get_ready_tasks() == []


# ---------------------------------------------------------------------------
# TeamRepository
# ---------------------------------------------------------------------------


def _team(team_id: str, **overrides) -> Team:
    defaults = {
        "team_id": team_id,
        "name": f"team-{team_id}",
        "task_ids": ["t1", "t2"],
        "status": TeamStatus.CREATED,
        "created_at": 1000,
        "updated_at": 1000,
        "metadata": {"source": "test"},
    }
    defaults.update(overrides)
    return Team(**defaults)


def test_team_create_get_roundtrip(team_repo: TeamRepository) -> None:
    team_repo.create(_team("tm1"))
    loaded = team_repo.get("tm1")
    assert loaded is not None
    assert loaded.task_ids == ["t1", "t2"]
    assert loaded.status is TeamStatus.CREATED
    assert loaded.metadata == {"source": "test"}


def test_team_get_missing(team_repo: TeamRepository) -> None:
    assert team_repo.get("ghost") is None


def test_team_update(team_repo: TeamRepository) -> None:
    team_repo.create(_team("tm1"))
    team = team_repo.get("tm1")
    assert team is not None
    team.status = TeamStatus.RUNNING
    team.task_ids = ["t9"]
    team.updated_at = 2000
    assert team_repo.update(team) is True
    loaded = team_repo.get("tm1")
    assert loaded is not None
    assert loaded.status is TeamStatus.RUNNING
    assert loaded.task_ids == ["t9"]
    assert loaded.updated_at == 2000


def test_team_update_missing_returns_false(team_repo: TeamRepository) -> None:
    assert team_repo.update(_team("ghost")) is False


def test_team_delete(team_repo: TeamRepository) -> None:
    team_repo.create(_team("tm1"))
    assert team_repo.delete("tm1") is True
    assert team_repo.delete("tm1") is False


def test_team_list_status_filter_and_limit(team_repo: TeamRepository) -> None:
    team_repo.create(_team("a", status=TeamStatus.CREATED, created_at=100))
    team_repo.create(_team("b", status=TeamStatus.RUNNING, created_at=200))
    team_repo.create(_team("c", status=TeamStatus.CREATED, created_at=300))

    rows = team_repo.list()
    assert [t.team_id for t in rows] == ["c", "b", "a"]  # created_at DESC

    created = team_repo.list(status=TeamStatus.CREATED)
    assert {t.team_id for t in created} == {"a", "c"}

    assert [t.team_id for t in team_repo.list(limit=1)] == ["c"]
