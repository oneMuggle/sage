"""R122 — 子代理嵌套深度防护单元测试。

覆盖：ContextVar 默认深度、enter/exit token 配对置位恢复、env 上限
（合法/空白/非法/零/负数回退）、is_nesting_allowed 三态。
usefixtures 保证 ContextVar 复位，不向其他用例泄漏。
"""

from __future__ import annotations

import pytest

from backend.orchestration.depth import (
    DEFAULT_MAX_SUBAGENT_DEPTH,
    current_subagent_depth,
    enter_subagent_depth,
    exit_subagent_depth,
    is_nesting_allowed,
    max_nested_subagent_depth,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def _clean_depth():
    """隔离 ContextVar：进入用例前复位，退出后强制归零。"""
    token = enter_subagent_depth(0)
    yield
    exit_subagent_depth(token)


def test_default_depth_is_zero():
    assert current_subagent_depth() == 0


@pytest.mark.usefixtures("_clean_depth")
def test_enter_exit_pairwise():
    token = enter_subagent_depth(1)
    try:
        assert current_subagent_depth() == 1
    finally:
        exit_subagent_depth(token)
    assert current_subagent_depth() == 0


@pytest.mark.usefixtures("_clean_depth")
def test_nested_enter_restores_previous_value():
    outer = enter_subagent_depth(1)
    try:
        inner = enter_subagent_depth(2)
        try:
            assert current_subagent_depth() == 2
        finally:
            exit_subagent_depth(inner)
        assert current_subagent_depth() == 1  # 恢复到外层值而非归零
    finally:
        exit_subagent_depth(outer)


def test_default_max_depth():
    assert DEFAULT_MAX_SUBAGENT_DEPTH == 1
    assert max_nested_subagent_depth() == 1


def test_env_override_valid_value(monkeypatch):
    monkeypatch.setenv("SAGE_MAX_SUBAGENT_DEPTH", "3")
    assert max_nested_subagent_depth() == 3


def test_env_override_strips_whitespace(monkeypatch):
    monkeypatch.setenv("SAGE_MAX_SUBAGENT_DEPTH", " 2 ")
    assert max_nested_subagent_depth() == 2


@pytest.mark.parametrize("raw", ["abc", "0", "-1", "1.5", ""])
def test_env_invalid_falls_back_to_default(monkeypatch, raw):
    monkeypatch.setenv("SAGE_MAX_SUBAGENT_DEPTH", raw)
    assert max_nested_subagent_depth() == DEFAULT_MAX_SUBAGENT_DEPTH


@pytest.mark.usefixtures("_clean_depth")
def test_nesting_allowed_at_conductor():
    assert is_nesting_allowed() is True


@pytest.mark.usefixtures("_clean_depth")
def test_nesting_blocked_at_limit():
    token = enter_subagent_depth(1)
    try:
        assert is_nesting_allowed() is False
    finally:
        exit_subagent_depth(token)


@pytest.mark.usefixtures("_clean_depth")
def test_env_relaxation_allows_deeper_nesting(monkeypatch):
    monkeypatch.setenv("SAGE_MAX_SUBAGENT_DEPTH", "2")
    token = enter_subagent_depth(1)
    try:
        assert is_nesting_allowed() is True  # 深度 1 < 上限 2
    finally:
        exit_subagent_depth(token)
    assert is_nesting_allowed() is True  # 退出后回到 conductor
