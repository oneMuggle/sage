from __future__ import annotations

import pytest

from backend.orchestration.plan_hierarchy import (
    MAX_TASK_DEPTH,
    HierarchyError,
    normalize_task_hierarchy,
)


def task(task_id: str, parent_task_id: str | None = None) -> dict:
    value = {"task_id": task_id, "agent_id": "agent", "goal": task_id}
    if parent_task_id is not None:
        value["parent_task_id"] = parent_task_id
    return value


def test_root_depth_is_zero():
    result = normalize_task_hierarchy([task("t1")])
    assert result[0]["depth"] == 0


def test_child_depth_is_parent_plus_one():
    result = normalize_task_hierarchy([task("t1"), task("t2", "t1")])
    assert [item["depth"] for item in result] == [0, 1]


def test_rejects_missing_parent():
    with pytest.raises(HierarchyError, match="non-existent parent"):
        normalize_task_hierarchy([task("t1", "missing")])


def test_rejects_self_reference():
    with pytest.raises(HierarchyError, match="self-reference"):
        normalize_task_hierarchy([task("t1", "t1")])


def test_rejects_parent_cycle():
    with pytest.raises(HierarchyError, match="cycle"):
        normalize_task_hierarchy([task("t1", "t2"), task("t2", "t1")])


def test_rejects_depth_over_limit():
    plan = [
        task(f"t{i}", f"t{i - 1}") if i else task("t0")
        for i in range(MAX_TASK_DEPTH + 2)
    ]
    with pytest.raises(HierarchyError, match="exceeds max depth"):
        normalize_task_hierarchy(plan)


def test_preserves_fields_and_does_not_mutate_input():
    plan = [task("t1")]
    plan[0]["depends_on"] = ["other"]
    result = normalize_task_hierarchy(plan)
    assert result[0]["depends_on"] == ["other"]
    assert "depth" not in plan[0]
