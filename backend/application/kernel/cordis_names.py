# ruff: noqa: UP006, UP007, UP035, UP045
"""Cordis（DeepSeek Harness）名称映射表——**只读常量，R78 不参与运行时**。

存在意义：把"如果我们哪天要接 dsh 插件，名字怎么对"这件事**固化成数据**，
避免将来重新调研。本轮只被测试与文档引用，不接入任何执行路径。

三个约束：

1. **不引入 Cordis**，只保留名字映射（决策见
   ``docs/mcp-dsh-plugin-adoption-decision-20261021.md``：学机制，不接生态）。
2. 映射表是**单向可见**的：``CORDIS_EVENT_ALIASES`` 描述 dsh 事件如何落到 sage，
   反向查询用 ``to_cordis_event``。
3. 兼容等级 ``COMPAT_GRADES`` 是对外口径（A 原生 / B 需 shim / C 需改造 / D 拒绝），
   与兼容设计文档保持一致，改动需同步文档。
"""

from __future__ import annotations

from typing import Dict, Optional

# dsh 服务名 → sage 概念名
CORDIS_SERVICE_ALIASES: Dict[str, str] = {
    "tools": "tool",
    "llm": "llm",
    "agents": "agent",
    "sessions": "session",
    "storage": "storage",
    "shell": "shell",
    "web": "web",
    "cmdlineArgs": "cmdline",
}

# dsh Cordis 事件名 → sage 内核事件名（``namespace/action``）
CORDIS_EVENT_ALIASES: Dict[str, str] = {
    "tool/call": "tool/call",
    "tools/result": "tool/post",
    "agent/pre-step": "agent/step",
    "agent/request": "agent/request",
    "agent/request-error": "agent/error",
    "session/event": "session/event",
}

# sage 内核事件名 → 存量 hook 事件名（迁移期别名，R79 使用）
LEGACY_HOOK_ALIASES: Dict[str, str] = {
    "tool/pre": "PreToolUse",
    "tool/post": "PostToolUse",
}

# 兼容等级（对外口径，见 docs/mcp-dsh-plugin-compat-design-20261021.md）
COMPAT_GRADES: Dict[str, str] = {
    "tool": "A",
    "hook": "A",
    "service": "A",
    "storage": "B",
    "llm": "B",
    "ui": "C",
    "agent_loop": "D",
    "session_log": "D",
    "sandbox": "D",
}


def to_sage_event(cordis_event: str) -> Optional[str]:
    """dsh 事件名 → sage 事件名；未知返回 ``None``（调用方自行决定忽略或告警）。"""
    return CORDIS_EVENT_ALIASES.get(cordis_event)


def to_cordis_event(sage_event: str) -> Optional[str]:
    """sage 事件名 → dsh 事件名；未知返回 ``None``。"""
    for cordis_name, sage_name in CORDIS_EVENT_ALIASES.items():
        if sage_name == sage_event:
            return cordis_name
    return None


def to_legacy_hook(sage_event: str) -> Optional[str]:
    """sage 内核事件名 → 存量 ``.sage/hooks.json`` 事件名；无别名返回 ``None``。"""
    return LEGACY_HOOK_ALIASES.get(sage_event)


def service_alias(cordis_service: str) -> Optional[str]:
    """dsh 服务名 → sage 概念名；未知返回 ``None``。"""
    return CORDIS_SERVICE_ALIASES.get(cordis_service)


def compat_grade(capability: str) -> str:
    """查询某能力类别的兼容等级（默认 ``"D"``，即未知即拒绝）。"""
    return COMPAT_GRADES.get(capability, "D")


__all__ = [
    "COMPAT_GRADES",
    "CORDIS_EVENT_ALIASES",
    "CORDIS_SERVICE_ALIASES",
    "LEGACY_HOOK_ALIASES",
    "compat_grade",
    "service_alias",
    "to_cordis_event",
    "to_legacy_hook",
    "to_sage_event",
]
