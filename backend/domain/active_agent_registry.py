"""M2: 活跃主 agent 注册表（域层）—— 反转 tools → api 依赖。

后台子代理完成时需要把结果注入"当前 run 的主 agent"。``backend.tools``
不允许导入 ``backend.api``（六边形架构契约）；由 api 层在模块加载时注册
解析器，tools 层只读域层注册表。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

_resolver: Optional[Callable[[Optional[str]], Any]] = None
#: M3.2: 按 session_id 解析主 agent（dispatcher 只知道 session_id）。
_session_resolver: Optional[Callable[[Optional[str]], Any]] = None


def set_main_agent_resolver(fn: Optional[Callable[[Optional[str]], Any]]) -> None:
    """由 api 层注册：``(stream_id) -> 主 agent | None``。"""
    global _resolver
    _resolver = fn


def resolve_main_agent(stream_id: Optional[str]) -> Any:
    """按 stream_id 解析主 agent；未注册/无匹配返回 None。"""
    resolver = _resolver
    if resolver is None:
        return None
    try:
        return resolver(stream_id)
    except Exception:  # noqa: BLE001 — 解析失败按"无主 agent"处理
        return None


def set_main_agent_session_resolver(
    fn: Optional[Callable[[Optional[str]], Any]],
) -> None:
    """由 api 层注册：``(session_id) -> 主 agent | None``。"""
    global _session_resolver
    _session_resolver = fn


def resolve_main_agent_for_session(session_id: Optional[str]) -> Any:
    """按 session_id 解析当前主 agent；未注册/无匹配返回 None。"""
    resolver = _session_resolver
    if resolver is None:
        return None
    try:
        return resolver(session_id)
    except Exception:  # noqa: BLE001 — 解析失败按"无主 agent"处理
        return None
