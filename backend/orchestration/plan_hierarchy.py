"""Task hierarchy validation and depth normalization."""

from __future__ import annotations

from typing import Any, Dict, List

MAX_TASK_DEPTH = 8


class HierarchyError(ValueError):
    """Raised when a task hierarchy is invalid."""


def normalize_task_hierarchy(plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate parent references and return a copied plan with canonical depths."""
    task_map = {task["task_id"]: task for task in plan}
    for task in plan:
        task_id = task["task_id"]
        parent_id = task.get("parent_task_id")
        if parent_id is None:
            continue
        if parent_id == task_id:
            raise HierarchyError(f"Task {task_id} has self-reference parent_task_id")
        if parent_id not in task_map:
            raise HierarchyError(
                f"Task {task_id} references non-existent parent {parent_id}"
            )

    depths: Dict[str, int] = {}

    def depth_for(task_id: str, visiting: List[str]) -> int:
        cached = depths.get(task_id)
        if cached is not None:
            return cached
        if task_id in visiting:
            cycle = " -> ".join(visiting[visiting.index(task_id) :] + [task_id])
            raise HierarchyError(f"Parent cycle detected: {cycle}")
        visiting.append(task_id)
        parent_id = task_map[task_id].get("parent_task_id")
        depth = 0 if parent_id is None else depth_for(parent_id, visiting) + 1
        visiting.pop()
        if depth > MAX_TASK_DEPTH:
            raise HierarchyError(
                f"Task {task_id} depth {depth} exceeds max depth {MAX_TASK_DEPTH}"
            )
        depths[task_id] = depth
        return depth

    for task in plan:
        depth_for(task["task_id"], [])

    return [{**task, "depth": depths[task["task_id"]]} for task in plan]
