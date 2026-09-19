"""Hook 配置模型与校验 (M6 生态扩展)。

用户自定义钩子以 JSON 列表存储在 settings ``hooks`` 键下。设计改编自
claw-code ``rust/crates/runtime/src/hooks.rs`` (PreToolUse / PostToolUse
事件 + allow/deny/modify 决策)。

单个钩子条目形状::

    {
        "event": "pre_tool_use" | "post_tool_use"
                 | "user_prompt_submit" | "stop",
        "matcher": "tool-name glob",   # 可选, 默认 "*"
        "command": "shell command",    # hook_type="shell" 时必填
        "hook_type": "shell" | "python",  # 可选, 默认 "shell"
        "handler": "dotted.path.func", # hook_type="python" 时必填
        "builtin_id": "security_guard",  # 可选, 内置钩子标识
        "config": {...},               # 可选, 内置钩子参数覆盖
        "timeout_seconds": 10          # 可选, 默认 10
    }

校验策略: 加载时严格 (结构非法 → 空列表 + warning, fail-open), 运行时
同样 fail-open — 坏配置永远不能阻断 agent。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# L11 (批次 C-2): 新增 user_prompt_submit(提示词提交, deny 可拦截消息)
# 与 stop(run 结束通知, observe-only)。
# Phase 2 (2026-09-19): 新增 session_start / session_stop / error_occurred 生命周期事件
HOOK_EVENTS = (
    "pre_tool_use",
    "post_tool_use",
    "user_prompt_submit",
    "stop",
    "session_start",
    "session_stop",
    "error_occurred",
)
HOOK_TYPES = ("shell", "python")
MAX_HOOKS = 20
DEFAULT_TIMEOUT_SECONDS = 10.0
_MIN_TIMEOUT_SECONDS = 0.1
# 审查加固: 20 条钩子串行执行, 无上限的病态配置可拖死 agent 循环
MAX_TIMEOUT_SECONDS = 300.0


class HookConfigError(ValueError):
    """hooks 配置结构非法时抛出。"""


@dataclass
class HookConfig:
    """一条已校验的钩子 (用户自定义或内置)。"""

    event: str
    command: str = ""
    matcher: str = "*"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    # Phase 1 扩展: python 内置钩子
    hook_type: str = "shell"  # "shell" | "python"
    handler: str = ""  # python hook 的 dotted path
    builtin_id: str = ""  # 内置钩子 ID (空 = 用户自定义)
    config_override: Dict[str, Any] = field(default_factory=dict)  # 内置钩子参数覆盖


def _coerce_one(raw: Any, index: int) -> HookConfig:
    """校验并规范化单个钩子条目。"""
    if not isinstance(raw, dict):
        raise HookConfigError(f"hooks[{index}] must be an object, got {type(raw).__name__}")

    event = raw.get("event")
    if event not in HOOK_EVENTS:
        raise HookConfigError(f"hooks[{index}].event {event!r} not in {list(HOOK_EVENTS)}")

    hook_type = raw.get("hook_type", "shell")
    if hook_type not in HOOK_TYPES:
        raise HookConfigError(f"hooks[{index}].hook_type {hook_type!r} not in {list(HOOK_TYPES)}")

    # shell hook: command 必填; python hook: handler 必填
    command = raw.get("command", "")
    handler = raw.get("handler", "")
    if hook_type == "shell" and (not isinstance(command, str) or not command.strip()):
        raise HookConfigError(f"hooks[{index}].command must be a non-empty string for shell hooks")
    if hook_type == "python" and (not isinstance(handler, str) or not handler.strip()):
        raise HookConfigError(f"hooks[{index}].handler must be a non-empty string for python hooks")

    matcher = raw.get("matcher", "*")
    if not isinstance(matcher, str) or not matcher.strip():
        raise HookConfigError(f"hooks[{index}].matcher must be a non-empty glob string")

    timeout = raw.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    # noqa UP038: isinstance 元组是 py3.8 兼容写法 (X | Y 需 3.10+)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):  # noqa: UP038
        raise HookConfigError(f"hooks[{index}].timeout_seconds must be a number")
    if timeout < _MIN_TIMEOUT_SECONDS:
        raise HookConfigError(f"hooks[{index}].timeout_seconds must be >= {_MIN_TIMEOUT_SECONDS}")
    if timeout > MAX_TIMEOUT_SECONDS:
        raise HookConfigError(f"hooks[{index}].timeout_seconds must be <= {MAX_TIMEOUT_SECONDS}")

    builtin_id = raw.get("builtin_id", "")
    if not isinstance(builtin_id, str):
        builtin_id = ""

    config_override = raw.get("config", {})
    if not isinstance(config_override, dict):
        config_override = {}

    return HookConfig(
        event=event,
        command=command.strip() if isinstance(command, str) else "",
        matcher=matcher.strip(),
        timeout_seconds=float(timeout),
        hook_type=hook_type,
        handler=handler.strip() if isinstance(handler, str) else "",
        builtin_id=builtin_id.strip(),
        config_override=config_override,
    )


def validate_hooks(raw: Any) -> List[HookConfig]:
    """把 settings 原始值校验为 HookConfig 列表。

    结构问题 (未知 event / 空 command / 超过 MAX_HOOKS 条) 抛
    HookConfigError; ``None`` → 空列表。
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HookConfigError(f"hooks must be a JSON list, got {type(raw).__name__}")
    if len(raw) > MAX_HOOKS:
        raise HookConfigError(f"too many hooks: {len(raw)} > {MAX_HOOKS}")
    return [_coerce_one(item, i) for i, item in enumerate(raw)]


def load_hooks(settings_repo: Any) -> List[HookConfig]:
    """从 settings 仓储加载并校验钩子 (fail-open)。

    任何问题 (读失败 / 坏 JSON / 非法条目) 都返回空列表并记 warning,
    保证钩子子系统永远不拖累 agent 主循环。
    """
    try:
        raw = settings_repo.get_json("hooks")
    except Exception as exc:
        logger.warning("hooks: failed to read settings (fail-open): %s", exc)
        return []
    try:
        return validate_hooks(raw)
    except HookConfigError as exc:
        logger.warning("hooks: invalid configuration ignored (fail-open): %s", exc)
        return []
