"""Hook 配置模型与校验 (M6 生态扩展)。

用户自定义钩子以 JSON 列表存储在 settings ``hooks`` 键下。设计改编自
claw-code ``rust/crates/runtime/src/hooks.rs`` (PreToolUse / PostToolUse
事件 + allow/deny/modify 决策)。

单个钩子条目形状::

    {
        "event": "pre_tool_use" | "post_tool_use",
        "matcher": "tool-name glob",   # 可选, 默认 "*"
        "command": "shell command",    # 必填; STDIN 收 JSON payload
        "timeout_seconds": 10          # 可选, 默认 10
    }

校验策略: 加载时严格 (结构非法 → 空列表 + warning, fail-open), 运行时
同样 fail-open — 坏配置永远不能阻断 agent。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List

logger = logging.getLogger(__name__)

HOOK_EVENTS = ("pre_tool_use", "post_tool_use")
MAX_HOOKS = 20
DEFAULT_TIMEOUT_SECONDS = 10.0
_MIN_TIMEOUT_SECONDS = 0.1


class HookConfigError(ValueError):
    """hooks 配置结构非法时抛出。"""


@dataclass
class HookConfig:
    """一条已校验的用户自定义钩子。"""

    event: str
    command: str
    matcher: str = "*"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


def _coerce_one(raw: Any, index: int) -> HookConfig:
    """校验并规范化单个钩子条目。"""
    if not isinstance(raw, dict):
        raise HookConfigError(f"hooks[{index}] must be an object, got {type(raw).__name__}")

    event = raw.get("event")
    if event not in HOOK_EVENTS:
        raise HookConfigError(f"hooks[{index}].event {event!r} not in {list(HOOK_EVENTS)}")

    command = raw.get("command")
    if not isinstance(command, str) or not command.strip():
        raise HookConfigError(f"hooks[{index}].command must be a non-empty string")

    matcher = raw.get("matcher", "*")
    if not isinstance(matcher, str) or not matcher.strip():
        raise HookConfigError(f"hooks[{index}].matcher must be a non-empty glob string")

    timeout = raw.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    # noqa UP038: isinstance 元组是 py3.8 兼容写法 (X | Y 需 3.10+)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):  # noqa: UP038
        raise HookConfigError(f"hooks[{index}].timeout_seconds must be a number")
    if timeout < _MIN_TIMEOUT_SECONDS:
        raise HookConfigError(f"hooks[{index}].timeout_seconds must be >= {_MIN_TIMEOUT_SECONDS}")

    return HookConfig(
        event=event,
        command=command.strip(),
        matcher=matcher.strip(),
        timeout_seconds=float(timeout),
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
