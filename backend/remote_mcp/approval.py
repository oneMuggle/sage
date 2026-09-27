"""远程工具调用审批（M5a）：桥接到 Sage 全局 ``ApprovalGate``。

- gate 的 Future 属于主后端事件循环；远程工具在监听器线程池中同步执行，
  经 ``asyncio.run_coroutine_threadsafe`` 把 ``gate.request`` 提交到主循环并阻塞等待。
- 主循环由管理 API 的 async 依赖捕获（:func:`capture_main_loop`）。
- 工具名改写为 ``remote_mcp.<tool>``：“记住选择”即使被持久化为规则，也不会命中
  Sage 自身 agent 的同名工具。
- 任何环节不可用一律 fail-closed。

见 docs/plans/2026-09-26-workspace-mcp-m5a-approval.md
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import logging
import threading
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_S = 120.0
TOOL_PREFIX = "remote_mcp."
WRITE_TOOLS = frozenset({"write_file", "edit_file", "apply_patch"})
SHELL_TOOLS = frozenset({"run_command"})

#: (approved, reason_code) —— reason 仅在拒绝时有意义
Decision = Tuple[bool, str]
Approver = Callable[[Dict[str, Any], str, Dict[str, Any], str], Decision]

_loop_lock = threading.Lock()
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def capture_main_loop() -> None:
    """在主后端事件循环内调用（async 依赖），记录该循环供跨线程提交审批。"""
    global _main_loop
    loop = asyncio.get_running_loop()
    with _loop_lock:
        _main_loop = loop


def set_main_loop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """测试用。"""
    global _main_loop
    with _loop_lock:
        _main_loop = loop


def _get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    with _loop_lock:
        return _main_loop


def command_risk(command: Any) -> str:
    """``validate_bash`` 风险等级字符串；无法判定时按 ``unknown``。"""
    if not isinstance(command, str):
        return "unknown"
    try:
        from backend.tools.bash_validation import validate_bash

        result = validate_bash(command)
        risk = getattr(result, "risk", None)
        return str(getattr(risk, "value", risk) or "safe")
    except Exception:  # noqa: BLE001 — 校验器异常时保守处理
        logger.warning("remote_mcp: validate_bash failed", exc_info=True)
        return "unknown"


def needs_approval(workspace: Dict[str, Any], tool_name: str, args: Dict[str, Any]) -> Optional[str]:
    """返回风险标签表示需要审批；``None`` 表示直接执行。"""
    mode = workspace.get("approval", "auto")
    if tool_name in SHELL_TOOLS:
        risk = command_risk(args.get("command"))
        if risk in ("destructive", "unknown"):
            return risk
        return risk if mode == "ask" else None
    if tool_name in WRITE_TOOLS and mode == "ask":
        return "write"
    return None


def _default_gate() -> Any:
    from backend.services.permission_gate import get_permission_gate

    return get_permission_gate()


class GateApprover:
    """把远程调用挂进 Sage 审批队列（GUI ApprovalDialog / Telegram 网关）。"""

    def __init__(self, gate_getter: Callable[[], Any] = _default_gate,
                 loop_getter: Callable[[], Optional[asyncio.AbstractEventLoop]] = _get_main_loop,
                 timeout: float = APPROVAL_TIMEOUT_S) -> None:
        self._gate_getter = gate_getter
        self._loop_getter = loop_getter
        self._timeout = timeout

    def __call__(self, workspace: Dict[str, Any], tool_name: str, args: Dict[str, Any],
                 risk: str) -> Decision:
        gate = self._gate_getter()
        loop = self._loop_getter()
        if gate is None or loop is None or loop.is_closed():
            return False, "APPROVAL_UNAVAILABLE"
        try:
            from backend.services.permission_gate import ApprovalRequest

            name = workspace.get("name") or workspace.get("id")
            message = f"远程工作区「{name}」请求 {tool_name}"
            if tool_name in SHELL_TOOLS:
                message += "（命令执行不是沙箱）"
            # 前端 PermissionRequest.risk 只认 safe / suspicious / destructive
            ui_risk = risk if risk in ("safe", "suspicious", "destructive") else "suspicious"
            request = ApprovalRequest.create(tool_name, args, ui_risk, message,
                                             workspace_root=workspace.get("root"))
            request = dataclasses.replace(request, tool_name=TOOL_PREFIX + tool_name)
            future = asyncio.run_coroutine_threadsafe(gate.request(request, self._timeout), loop)
            answer = future.result(timeout=self._timeout + 10)
        except concurrent.futures.TimeoutError:
            return False, "timeout"
        except Exception:  # noqa: BLE001 — 审批通道故障 fail-closed
            logger.warning("remote_mcp: approval channel failed", exc_info=True)
            return False, "APPROVAL_UNAVAILABLE"
        if getattr(answer, "approved", False):
            return True, ""
        return False, "timeout" if getattr(answer, "answered_by", "") == "timeout" else "denied"


__all__ = [
    "APPROVAL_TIMEOUT_S",
    "Approver",
    "GateApprover",
    "TOOL_PREFIX",
    "capture_main_loop",
    "command_risk",
    "needs_approval",
    "set_main_loop",
]
