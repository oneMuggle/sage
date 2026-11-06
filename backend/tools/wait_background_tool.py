"""LLM 后台任务等待工具（2026-11-06 Phase 1）。

与 ``bash_output`` 的"非阻塞读"互补：``wait_background`` 在指定窗口内
等待后台 shell 结束（默认 10s、上限 60s），返回最终状态与本次新增输出。
适合要拿到"这一步跑完"结果才能继续的短等待；长任务应改用
``wake_on_background`` 登记完成唤醒，避免占用工具线程。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.bash_session import STATUS_EXITED, get_registry

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10
MAX_TIMEOUT_S = 60
POLL_INTERVAL_S = 0.5
MAX_READ_BYTES = 8192


class WaitBackgroundTool(BaseTool):
    """等待后台 shell 结束（有界窗口）。"""

    risk: RiskClass = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="wait_background",
            description=(
                "等待后台 shell 结束或超时（默认 10 秒，上限 60 秒），返回状态、"
                "退出码与本次新增输出。适合需要立刻拿到结果的短等待；"
                "长任务请改用 wake_on_background 登记完成唤醒，避免阻塞。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "shell_id": {
                        "type": "string",
                        "description": "bash(run_in_background=true) 返回的 shell_id。",
                    },
                    "timeout_s": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_TIMEOUT_S,
                        "description": f"等待秒数（1–{MAX_TIMEOUT_S}，默认 {DEFAULT_TIMEOUT_S}）。",
                    },
                },
                "required": ["shell_id"],
            },
        )

    def execute(
        self, shell_id: str = "", timeout_s: Any = DEFAULT_TIMEOUT_S, **kwargs: Any
    ) -> ToolResult:
        if not isinstance(shell_id, str) or not shell_id.strip():
            return ToolResult(success=False, error="shell_id 必须是非空字符串。")
        try:
            timeout = int(timeout_s)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_S
        timeout = max(1, min(timeout, MAX_TIMEOUT_S))

        registry = get_registry()
        deadline = time.monotonic() + timeout
        while True:
            session = registry.get(shell_id)
            if session is None:
                return ToolResult(
                    success=False,
                    error="未知的 shell_id（可能已结束并被 kill_shell 清理）。",
                )
            if session.status() == STATUS_EXITED:
                return ToolResult(
                    success=True,
                    content=self._payload(registry, shell_id, exited=True),
                )
            if time.monotonic() >= deadline:
                return ToolResult(
                    success=True,
                    content=self._payload(registry, shell_id, exited=False),
                )
            time.sleep(POLL_INTERVAL_S)

    @staticmethod
    def _payload(registry: Any, shell_id: str, *, exited: bool) -> dict:
        try:
            increment = registry.read_increment(shell_id, cap=MAX_READ_BYTES) or {}
        except Exception:  # noqa: BLE001 — 读取失败不影响状态返回
            logger.exception("wait_background 读取输出失败: %s", shell_id)
            increment = {}
        return {
            "shell_id": shell_id,
            "status": STATUS_EXITED if exited else "running",
            "timed_out": not exited,
            "exit_code": increment.get("exit_code"),
            "stdout": increment.get("stdout", ""),
            "stderr": increment.get("stderr", ""),
            "truncated": bool(increment.get("truncated", False)),
        }
