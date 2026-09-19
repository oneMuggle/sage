"""Task 7 — Planner 层级解析：LLM 父级引用映射到真实 task_id。"""

from __future__ import annotations

from backend.orchestration.planner import (
    resolve_plan_hierarchy,
    sanitize_llm_plan_tasks,
)


def test_sanitize_resolves_parent_to_earlier_placeholder():
    tasks = sanitize_llm_plan_tasks(
        [
            {"id": "t1", "title": "root", "description": "d1"},
            {
                "id": "t2",
                "title": "child",
                "description": "d2",
                "parent_task_id": "t1",
            },
        ]
    )
    assert tasks[0]["_parent_placeholder"] is None
    assert tasks[1]["_parent_placeholder"] == tasks[0]["_placeholder"]


def test_sanitize_prunes_unknown_or_forward_parent():
    tasks = sanitize_llm_plan_tasks(
        [
            {
                "id": "t1",
                "title": "a",
                "description": "d",
                "parent_task_id": "t9",
            },
            {
                "id": "t2",
                "title": "b",
                "description": "d",
                "parent_task_id": "t3",
            },
        ]
    )
    assert tasks[0]["_parent_placeholder"] is None
    assert tasks[1]["_parent_placeholder"] is None


def test_resolve_plan_hierarchy_maps_ids_and_depth():
    tasks = sanitize_llm_plan_tasks(
        [
            {"id": "t1", "title": "root", "description": "d1"},
            {
                "id": "t2",
                "title": "child",
                "description": "d2",
                "parent_task_id": "t1",
            },
            {
                "id": "t3",
                "title": "grand",
                "description": "d3",
                "parent_task_id": "t2",
            },
        ]
    )
    mapping = {t["_placeholder"]: f"task-{i}" for i, t in enumerate(tasks)}
    result = resolve_plan_hierarchy(tasks, mapping)

    assert result["task-0"]["parent_task_id"] is None
    assert result["task-0"]["depth"] == 0
    assert result["task-1"]["parent_task_id"] == "task-0"
    assert result["task-1"]["depth"] == 1
    assert result["task-2"]["parent_task_id"] == "task-1"
    assert result["task-2"]["depth"] == 2


def test_resolve_plan_hierarchy_is_fail_open_without_parents():
    tasks = sanitize_llm_plan_tasks(
        [{"id": "t1", "title": "root", "description": "d1"}]
    )
    result = resolve_plan_hierarchy(tasks, {tasks[0]["_placeholder"]: "task-0"})
    assert result["task-0"] == {"parent_task_id": None, "depth": 0}
