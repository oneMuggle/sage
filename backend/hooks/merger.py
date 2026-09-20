"""钩子配置合并 (Phase 4): 项目级 + 用户级 → 单一执行列表。

**合并语义**

执行顺序 = 列表顺序, 且 ``deny`` 会短路。因此:

1. **项目级在前** —— 团队策略优先裁决。若项目策略 deny 某工具, 即使
   用户级配置了 allow 类钩子也无法绕过 (deny 先命中即返回)。
2. **用户级在后且完整保留** —— 项目配置无法删除、替换或遮蔽用户自定义
   钩子; 两级共存, 各自独立生效。
3. **总条数上限** —— 合并后超过 ``MAX_HOOKS`` 时截断, 项目级优先保留
   (团队策略完整性优先), 后续用户钩子被挤出并记 warning。

**不做的事**

- 不做"同名去重" —— 钩子没有稳定标识, 且两级各配一条同类钩子通常是
  有意的 (如项目检查 + 个人检查)。
- 不改变任何钩子的字段 —— 合并是纯拼接, 语义完全由 ``runner`` 决定。
"""

from __future__ import annotations

import logging
from typing import List

from backend.hooks.config import MAX_HOOKS, HookConfig

logger = logging.getLogger(__name__)


def merge_hooks(
    project_hooks: List[HookConfig],
    user_hooks: List[HookConfig],
    max_hooks: int = MAX_HOOKS,
) -> List[HookConfig]:
    """合并项目级与用户级钩子, 返回执行顺序列表。

    Args:
        project_hooks: 项目级钩子 (来自 ``.sage/hooks.json``, 已通过信任门禁)
        user_hooks: 用户级钩子 (来自 preferences ``hooks``)
        max_hooks: 合并后条数上限

    Returns:
        项目级在前、用户级在后的列表; 超出上限时截断并记 warning。
    """
    merged = list(project_hooks) + list(user_hooks)
    if len(merged) <= max_hooks:
        return merged

    logger.warning(
        "hooks: merged %d hooks exceeds limit %d — truncating (project hooks kept first)",
        len(merged),
        max_hooks,
    )
    return merged[:max_hooks]
