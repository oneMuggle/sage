"""M6 生态扩展: 工具执行钩子系统 (user-defined hooks around tool execution).

设计改编自 claw-code ``rust/crates/runtime/src/hooks.rs`` — PreToolUse /
PostToolUse 事件, allow/deny/modify 决策, JSON over STDIN 协议。

核心契约: **fail-open** — 钩子自身的任何故障 (超时 / 非零退出 / 非 JSON
输出) 都降级为 no-op 并记录 warning, 永不阻断 agent 循环; 唯有钩子显式
输出 ``{"decision": "deny"}`` 才会拦截工具执行。
"""

from __future__ import annotations

from backend.hooks.builtin import (
    BUILTIN_HOOKS,
    get_builtin,
    list_builtins,
    make_hook_entry,
)
from backend.hooks.config import (
    DEFAULT_TIMEOUT_SECONDS,
    HOOK_EVENTS,
    HOOK_TYPES,
    MAX_HOOKS,
    HookConfig,
    HookConfigError,
    load_hooks,
    validate_hooks,
)
from backend.hooks.http_client import resolve_header_value, resolve_headers, send_http_hook
from backend.hooks.merger import merge_hooks
from backend.hooks.project_config import (
    PROJECT_CONFIG_REL_PATH,
    TRUSTED_WORKSPACES_KEY,
    is_workspace_trusted,
    load_project_hooks,
    load_trusted_workspaces,
    trust_workspace,
    untrust_workspace,
    validate_project_hooks,
)
from backend.hooks.runner import (
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_MODIFY,
    DECISION_NOOP,
    HookOutcome,
    build_error_payload,
    build_payload,
    build_session_payload,
    matches_tool,
    run_event_hooks,
    run_event_hooks_sync,
    run_hook,
    validate_modified_args,
)

__all__ = [
    "BUILTIN_HOOKS",
    "DECISION_ALLOW",
    "DECISION_DENY",
    "DECISION_MODIFY",
    "DECISION_NOOP",
    "DEFAULT_TIMEOUT_SECONDS",
    "HOOK_EVENTS",
    "HOOK_TYPES",
    "MAX_HOOKS",
    "PROJECT_CONFIG_REL_PATH",
    "TRUSTED_WORKSPACES_KEY",
    "HookConfig",
    "HookConfigError",
    "HookOutcome",
    "build_error_payload",
    "build_payload",
    "build_session_payload",
    "get_builtin",
    "is_workspace_trusted",
    "list_builtins",
    "load_hooks",
    "load_project_hooks",
    "load_trusted_workspaces",
    "make_hook_entry",
    "matches_tool",
    "merge_hooks",
    "resolve_headers",
    "resolve_header_value",
    "run_event_hooks",
    "run_event_hooks_sync",
    "run_hook",
    "send_http_hook",
    "trust_workspace",
    "untrust_workspace",
    "validate_hooks",
    "validate_modified_args",
    "validate_project_hooks",
]
