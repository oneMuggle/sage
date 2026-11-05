"""专家技能作用域原语（M1，spec §5.1）。

专家的 ``skills`` 字段声明技能允许集，语义：

- ``None`` 或空列表 → 不受限（主助手 / 未配置专家）；
- 非空列表 → fail-closed：只有解析出的技能名可见、可执行；
- 通配语法：``plugin__<name>__*`` 等以 ``*`` 结尾的模式按前缀展开
  （对 ``available_names`` 做前缀匹配），其余条目按技能名逐字加入。

解析发生在 adapter 层（``InprocSkillAdapter`` 与 ``SkillTool``），
本模块只做纯函数计算，不触碰注册表或磁盘。
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Set

__all__ = ["resolve_skill_allowlist", "is_skill_allowed"]


def resolve_skill_allowlist(
    patterns: Optional[Iterable[str]],
    available_names: Iterable[str],
) -> Optional[Set[str]]:
    """把 expert 的 ``skills`` 模式列表解析为具体技能名集合。

    Args:
        patterns: agent 档案中的 ``skills`` 列表；``None`` / 空 → 返回
            ``None``（不受限）。
        available_names: 当前注册表里的全部技能名（用于展开 ``*`` 前缀）。

    Returns:
        ``None`` 表示不受限；否则为允许集（可能为空集合 → 全部拒绝）。
    空字符串/纯空白模式被忽略；非空模式里的 ``*`` 视为后缀通配。
    """
    if patterns is None:
        return None
    cleaned: List[str] = [p.strip() for p in patterns if isinstance(p, str) and p.strip()]
    if not cleaned:
        # 调用方传了非 None 但没有任何有效条目：视为未配置 → 不受限。
        return None
    names = set(available_names)
    resolved: Set[str] = set()
    for pattern in cleaned:
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            resolved.update(name for name in names if name.startswith(prefix))
        else:
            resolved.add(pattern)
    return resolved


def is_skill_allowed(allowlist: Optional[Set[str]], skill_name: str) -> bool:
    """``allowlist is None`` 永远放行；否则要求技能名在集合内。"""
    if allowlist is None:
        return True
    return skill_name in allowlist
