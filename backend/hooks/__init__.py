"""M6 生态扩展: 工具执行钩子系统 (user-defined hooks around tool execution).

设计改编自 claw-code ``rust/crates/runtime/src/hooks.rs`` — PreToolUse /
PostToolUse 事件, allow/deny/modify 决策, JSON over STDIN 协议。

核心契约: **fail-open** — 钩子自身的任何故障 (超时 / 非零退出 / 非 JSON
输出) 都降级为 no-op 并记录 warning, 永不阻断 agent 循环; 唯有钩子显式
输出 ``{"decision": "deny"}`` 才会拦截工具执行。
"""

from __future__ import annotations

from backend.hooks.config import (
    DEFAULT_TIMEOUT_SECONDS,
    HOOK_EVENTS,
    MAX_HOOKS,
    HookConfig,
    HookConfigError,
    load_hooks,
    validate_hooks,
)
from backend.hooks.runner import (
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_MODIFY,
    DECISION_NOOP,
    HookOutcome,
    build_payload,
    matches_tool,
    run_event_hooks,
    run_hook,
    validate_modified_args,
)

__all__ = [
    "DECISION_ALLOW",
    "DECISION_DENY",
    "DECISION_MODIFY",
    "DECISION_NOOP",
    "DEFAULT_TIMEOUT_SECONDS",
    "HOOK_EVENTS",
    "MAX_HOOKS",
    "HookConfig",
    "HookConfigError",
    "HookOutcome",
    "build_payload",
    "load_hooks",
    "matches_tool",
    "run_event_hooks",
    "run_hook",
    "validate_hooks",
    "validate_modified_args",
]
