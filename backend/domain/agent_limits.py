"""Agent 迭代次数上限的单一真相源。

历史教训：``50`` 这个魔法数曾散落在四处硬编码 —— 后端 PATCH/POST 路由
校验（``legacy_agent_routes.py``）、LLM 工具 ``update_sage_config`` 的运行时
校验（``tools/config_tool.py``）、工具 schema 文案、前端智能体编辑表单的
``<input max="50">``。它与系统自身的动态预算硬顶（``budget_hard_cap=1000``、
``budget_long=400``）以及编排设置页**无上界**的 ``maxIterations`` 自相矛盾，
是历史遗留物而非设计约束 —— 用户在智能体页把 primary 调到 50 以上即报
422，且前端把 422 结构化 detail 吞成"保存失败"，排查成本极高。

本模块把上下界收敛为常量，调用方一律引用，不再各自写字面量：

- ``MIN_ITERATIONS``：下界。0 会让 ``for i in range(0)`` 静默失效，
  语义上等同"不迭代"，任何层都不接受。
- ``MAX_ITERATIONS_CEILING``：上界。对齐动态预算的硬顶默认值
  （``BudgetConfig.hard_cap``），使"单个 agent profile 的固定上限"与
  "动态预算能自动延长到的天花板"处于同一量级 —— 用户不必理解两套
  预算体系就能拿到一个自洽的直觉。

放在 domain 层（import-linter 六边形契约的最内层，零外部依赖），
使 api / tools / core 各层都能安全向内引用，模式同 ``domain/tool_names.py``。
"""

from __future__ import annotations

#: 迭代次数下界。0 会让迭代循环静默失效，不接受。
MIN_ITERATIONS = 1

#: 迭代次数上界。与动态预算硬顶默认值（``BudgetConfig.hard_cap``）对齐。
MAX_ITERATIONS_CEILING = 1000


def is_valid_iteration_count(value: object) -> bool:
    """``value`` 是否是落在允许区间内的迭代次数。

    判定口径与所有调用方的报错文案共享同一份边界定义，避免"后端拒绝
    的值前端能填"这类双份边界漂移。``bool`` 被显式排除 —— Python 里
    ``True == 1``，若放行会被当作 1 次迭代落库。
    """
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return MIN_ITERATIONS <= value <= MAX_ITERATIONS_CEILING


__all__ = [
    "MAX_ITERATIONS_CEILING",
    "MIN_ITERATIONS",
    "is_valid_iteration_count",
]
