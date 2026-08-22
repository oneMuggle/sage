"""depends_on 拓扑工具 —— Kahn 分层波次 + 环检测 + 级联闭包。

P1 (spec 2026-08-21)：dispatch 内部确定性分波，不依赖 LLM 行为。
deps 引用不在本批的 task_id 时视为已满足（宽松处理，兼容跨批派发
与 conductor 动态加任务）。
"""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Set


class DependencyCycleError(ValueError):
    """depends_on 图存在环。cycle 为环路径（首尾相同）。"""

    def __init__(self, cycle: List[str]) -> None:
        super().__init__("dependency cycle: " + " -> ".join(cycle))
        self.cycle = cycle


def find_cycle(deps_by_id: Dict[str, List[str]]) -> Optional[List[str]]:
    """DFS 找环；返回路径如 ["t2","t3","t2"]，无环 None。"""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {k: WHITE for k in deps_by_id}
    path: List[str] = []

    def visit(node: str) -> Optional[List[str]]:
        color[node] = GRAY
        path.append(node)
        for dep in deps_by_id.get(node, []):
            if dep not in deps_by_id:
                continue  # 外部引用视为已满足
            if color.get(dep, WHITE) == GRAY:
                idx = path.index(dep)
                return path[idx:] + [dep]
            if color.get(dep, WHITE) == WHITE:
                found = visit(dep)
                if found:
                    return found
        path.pop()
        color[node] = BLACK
        return None

    for node in deps_by_id:
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def build_waves(
    task_ids: List[str], deps_by_id: Dict[str, List[str]]
) -> List[List[str]]:
    """Kahn 分层：第 i 波的所有依赖都在前 i-1 波内完成。

    Raises:
        DependencyCycleError: 图中存在环（含环路径）。
    """
    id_set = set(task_ids)
    indeg: Dict[str, int] = {tid: 0 for tid in task_ids}
    dependents: Dict[str, List[str]] = {tid: [] for tid in task_ids}
    for tid in task_ids:
        for dep in deps_by_id.get(tid, []):
            if dep in id_set:
                indeg[tid] += 1
                dependents[dep].append(tid)

    wave: List[str] = [tid for tid in task_ids if indeg[tid] == 0]
    waves: List[List[str]] = []
    done_count = 0
    while wave:
        waves.append(list(wave))
        done_count += len(wave)
        nxt: List[str] = []
        for tid in wave:
            for child in dependents[tid]:
                indeg[child] -= 1
                if indeg[child] == 0:
                    nxt.append(child)
        wave = nxt
    if done_count < len(task_ids):
        cycle = find_cycle(deps_by_id)
        raise DependencyCycleError(cycle or [t for t in task_ids if indeg[t] > 0])
    return waves


def downstream_closure(
    deps_by_id: Dict[str, List[str]], seeds: Set[str]
) -> Set[str]:
    """seeds 的全部传递下游（依赖 seeds 的任务，间接含）。不含 seeds 自身。"""
    dependents: Dict[str, List[str]] = {}
    for tid, deps in deps_by_id.items():
        for dep in deps:
            dependents.setdefault(dep, []).append(tid)

    result: Set[str] = set()
    queue: deque = deque(seeds)
    while queue:
        node = queue.popleft()
        for child in dependents.get(node, []):
            if child not in result and child not in seeds:
                result.add(child)
                queue.append(child)
    return result
