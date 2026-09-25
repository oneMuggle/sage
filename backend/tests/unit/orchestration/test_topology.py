"""R127 — depends_on 拓扑工具单元测试。

覆盖：find_cycle（无环/双节点环/自环/外部引用宽松处理/间接可达环）、
build_waves（独立单波/链/菱形/外部依赖第 0 波/环抛错带 cycle 路径）、
downstream_closure（直接下游/传递闭包不含 seeds/多 seed 并集/未知 seed）。
"""

from __future__ import annotations

import pytest

from backend.orchestration.topology import (
    DependencyCycleError,
    build_waves,
    downstream_closure,
    find_cycle,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# find_cycle
# ---------------------------------------------------------------------------


def test_find_cycle_acyclic_returns_none():
    assert find_cycle({"a": ["b"], "b": ["c"], "c": []}) is None


def test_find_cycle_two_node_cycle_path_closed():
    cycle = find_cycle({"t1": ["t2"], "t2": ["t3"], "t3": ["t2"]})
    assert cycle is not None
    assert cycle[0] == cycle[-1]  # 首尾相同
    assert set(cycle[:-1]) == {"t2", "t3"}


def test_find_cycle_self_loop():
    assert find_cycle({"t1": ["t1"]}) == ["t1", "t1"]


def test_find_cycle_external_refs_ignored():
    # deps 指向不在本图的任务：宽松处理，视为已满足，不构成环
    assert find_cycle({"a": ["external-1"], "b": ["a", "missing"]}) is None


def test_find_cycle_reachable_only_from_later_start():
    # 环在第二个起点才可达：多起点遍历必须覆盖
    deps = {"a": ["b"], "b": [], "c": ["d"], "d": ["c"]}
    assert find_cycle(deps) is not None


# ---------------------------------------------------------------------------
# build_waves
# ---------------------------------------------------------------------------


def test_build_waves_independent_single_wave():
    waves = build_waves(["a", "b", "c"], {"a": [], "b": [], "c": []})
    assert waves == [["a", "b", "c"]]


def test_build_waves_chain():
    waves = build_waves(["a", "b", "c"], {"a": [], "b": ["a"], "c": ["b"]})
    assert waves == [["a"], ["b"], ["c"]]


def test_build_waves_diamond():
    waves = build_waves(
        ["d", "a", "b", "c"],  # 输入顺序打乱，验证波内按输入序
        {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]},
    )
    assert waves == [["a"], ["b", "c"], ["d"]]


def test_build_waves_external_dep_starts_in_wave_zero():
    waves = build_waves(["x"], {"x": ["not-in-batch"]})
    assert waves == [["x"]]


def test_build_waves_cycle_raises_with_cycle_path():
    deps = {"t1": ["t2"], "t2": ["t1"]}
    with pytest.raises(DependencyCycleError) as excinfo:
        build_waves(["t1", "t2"], deps)
    assert excinfo.value.cycle[0] == excinfo.value.cycle[-1]
    assert "dependency cycle" in str(excinfo.value)


def test_build_waves_partial_cycle_raises():
    deps = {"free": [], "x": ["y"], "y": ["x"]}
    with pytest.raises(DependencyCycleError):
        build_waves(["free", "x", "y"], deps)


# ---------------------------------------------------------------------------
# downstream_closure
# ---------------------------------------------------------------------------


def test_closure_direct_dependents():
    deps = {"a": [], "b": ["a"], "c": ["a"]}
    assert downstream_closure(deps, {"a"}) == {"b", "c"}


def test_closure_transitive_excludes_seeds():
    deps = {"a": [], "b": ["a"], "c": ["b"]}
    assert downstream_closure(deps, {"a"}) == {"b", "c"}


def test_closure_seed_dependent_on_another_seed_excluded():
    deps = {"a": [], "b": ["a"]}
    # seeds = {a, b}：b 虽是 a 的下游但已在 seeds，不重复出现在结果
    assert downstream_closure(deps, {"a", "b"}) == set()


def test_closure_multiple_seeds_union():
    deps = {"a": [], "b": [], "c": ["a"], "d": ["b"], "e": []}
    assert downstream_closure(deps, {"a", "b"}) == {"c", "d"}


def test_closure_unknown_seed_returns_empty():
    deps = {"a": ["b"], "b": []}
    assert downstream_closure(deps, {"nope"}) == set()
