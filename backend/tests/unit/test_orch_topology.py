"""topology 模块单测：Kahn 分层、环检测、级联闭包。"""

from __future__ import annotations

import pytest

from backend.orchestration.topology import (
    DependencyCycleError,
    build_waves,
    downstream_closure,
    find_cycle,
)

pytestmark = pytest.mark.unit


def test_build_waves_linear_chain():
    waves = build_waves(["t1", "t2", "t3"], {"t1": [], "t2": ["t1"], "t3": ["t2"]})
    assert waves == [["t1"], ["t2"], ["t3"]]


def test_build_waves_diamond():
    deps = {"t1": [], "t2": ["t1"], "t3": ["t1"], "t4": ["t2", "t3"]}
    waves = build_waves(["t1", "t2", "t3", "t4"], deps)
    assert waves == [["t1"], ["t2", "t3"], ["t4"]]


def test_build_waves_no_deps_single_wave():
    waves = build_waves(["t1", "t2"], {"t1": [], "t2": []})
    assert waves == [["t1", "t2"]]


def test_build_waves_empty():
    assert build_waves([], {}) == []


def test_build_waves_unknown_dep_treated_satisfied():
    # deps 引用不在本批的 id → 视为已满足，不阻塞
    waves = build_waves(["t1"], {"t1": ["tX"]})
    assert waves == [["t1"]]


def test_build_waves_cycle_raises_with_path():
    deps = {"t1": ["t2"], "t2": ["t3"], "t3": ["t1"]}
    with pytest.raises(DependencyCycleError) as ei:
        build_waves(["t1", "t2", "t3"], deps)
    assert ei.value.cycle[0] == ei.value.cycle[-1]  # 环路径首尾相同
    assert set(ei.value.cycle) == {"t1", "t2", "t3"}


def test_find_cycle_none_when_acyclic():
    assert find_cycle({"t1": [], "t2": ["t1"]}) is None


def test_downstream_closure_direct_and_transitive():
    deps = {"t1": [], "t2": ["t1"], "t3": ["t2"], "t4": []}
    assert downstream_closure(deps, {"t1"}) == {"t2", "t3"}
    assert downstream_closure(deps, {"t4"}) == set()
    assert downstream_closure(deps, {"t2"}) == {"t3"}
