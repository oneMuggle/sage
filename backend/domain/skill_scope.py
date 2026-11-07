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

<<<<<<< HEAD
from typing import Iterable, List, Optional, Set

__all__ = ["resolve_skill_allowlist", "is_skill_allowed"]
=======
import contextvars
from typing import Any, FrozenSet, Iterable, List, Optional, Set, Tuple

__all__ = [
    "resolve_skill_allowlist",
    "is_skill_allowed",
    "set_turn_skill_allowlist",
    "reset_turn_skill_allowlist",
    "peek_turn_skill_allowlist",
]
>>>>>>> origin/main


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
<<<<<<< HEAD
=======


# --------------------------------------------------------------------------- #
# 本轮执行器的技能作用域（M1，spec §5.1）
#
# hex ChatService 与多个会话共享同一工具注册表，构造期注入无法表达
# "本轮是哪个专家"。执行器在跑 tool_calls 前把解析好的允许集写入
# ContextVar，适配器侧读取；ContextVar 随 ``py_compat.to_thread``
# （py38 走 copy_context）传入工具线程，并发会话互不串扰。
#
# 放在 domain 层是为了让 application 不静态依赖 tools/adapters
# （六边形架构契约：application 不得导入 adapters）。
# --------------------------------------------------------------------------- #

_UNSET = object()

_TURN_SKILL_ALLOWLIST: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "turn_skill_allowlist", default=_UNSET
)


def set_turn_skill_allowlist(allowed: Optional[Iterable[str]]) -> Any:
    """设置本轮技能允许集，返回用于恢复的 token（配合 ``reset_*``）。

    ``allowed=None`` 表示公开技能不受限（私有技能仍被遮罩）。
    """
    value = None if allowed is None else frozenset(allowed)
    return _TURN_SKILL_ALLOWLIST.set(value)


def reset_turn_skill_allowlist(token: Any) -> None:
    """恢复 ``set_turn_skill_allowlist`` 之前的作用域。"""
    _TURN_SKILL_ALLOWLIST.reset(token)


def peek_turn_skill_allowlist() -> Tuple[bool, Optional[FrozenSet[str]]]:
    """读取本轮作用域，返回 ``(是否已设置, 允许集)``。

    ``是否已设置=False`` 表示调用方应回落到构造期作用域/无限制。
    """
    value = _TURN_SKILL_ALLOWLIST.get()
    if value is _UNSET:
        return False, None
    return True, value
>>>>>>> origin/main
