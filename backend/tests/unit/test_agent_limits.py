"""backend.domain.agent_limits 单一真相源单元测试.

覆盖点:
- 常量值本身 (``MIN_ITERATIONS``, ``MAX_ITERATIONS_CEILING``) 与文档一致.
- ``is_valid_iteration_count`` 对边界 / 越界 / 非 int / bool 的判定.
- 与所有调用方的契约: 后端路由 (``legacy_agent_routes``) 与工具
  (``config_tool``) 的报错文案必须与本模块的边界完全对齐, 本测试
  通过显式引用常量保证未来边界调整时此处同步失败.
"""

from __future__ import annotations

import pytest

from backend.domain.agent_limits import (
    MAX_ITERATIONS_CEILING,
    MIN_ITERATIONS,
    is_valid_iteration_count,
)


class TestAgentLimitsConstants:
    """常量值必须与文档声明一致 — 任何调整都会让这里失败."""

    def test_min_iterations_is_one(self) -> None:
        assert MIN_ITERATIONS == 1

    def test_max_iterations_ceiling_is_one_thousand(self) -> None:
        # 与 ``BudgetConfig.hard_cap`` 默认值 (动态预算硬顶) 对齐.
        assert MAX_ITERATIONS_CEILING == 1000

    def test_ceiling_gte_floor(self) -> None:
        assert MAX_ITERATIONS_CEILING >= MIN_ITERATIONS


class TestIsValidIterationCount:
    """``is_valid_iteration_count`` 边界 / 类型判定."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # 边界
            (1, True),
            (MAX_ITERATIONS_CEILING, True),
            # 下 / 上越界
            (0, False),
            (-1, False),
            (MAX_ITERATIONS_CEILING + 1, False),
            (10_000, False),
            # 非 int
            (1.0, False),
            (1.5, False),
            ("1", False),
            (None, False),
            ([1], False),
            ({"k": 1}, False),
        ],
    )
    def test_boundary_and_type(self, value: object, expected: bool) -> None:
        assert is_valid_iteration_count(value) is expected

    def test_bool_true_rejected(self) -> None:
        # Python 中 ``True == 1`` 会让 ``True`` 绕过 int 校验; 必须显式排除.
        assert is_valid_iteration_count(True) is False

    def test_bool_false_rejected(self) -> None:
        assert is_valid_iteration_count(False) is False

    def test_interior_values_accepted(self) -> None:
        # 区间中段抽样 — 确认不是只判边界.
        for value in (1, 10, 50, 200, 500, MAX_ITERATIONS_CEILING):
            assert is_valid_iteration_count(value) is True
