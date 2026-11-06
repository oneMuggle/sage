"""LLM 后台任务完成唤醒工具（2026-11-06 Phase 1）。

配合 ``bash(run_in_background=true)``：把「任务结束后自动回来」变成
LLM 可直接表达的语义——登记一条 COMPLETION wake，后台 shell 退出时由
``BashSessionRegistry`` 退出观察器调用 ``WakeStore.complete_job``，
``WakeScheduler`` 在下一 tick 恢复会话并注入续跑消息。

- 复用 ``WakeStore`` 单一事实源，不另起调度器；
- 目标会话恒绑定 ``ToolExecutionContext.session_id``，拒绝跨会话；
- shell 已结束：退化为立即到期的 TIMER wake（下一 tick 恢复）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.application.services.wake_store import get_wake_store
from backend.domain.risk import RiskClass
from backend.domain.wake import Wake, WakeKind, to_utc_iso
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.bash_session import STATUS_EXITED, get_registry
from backend.tools.context import current_tool_context

logger = logging.getLogger(__name__)

NO_CONTEXT_ERROR = "无法确定目标会话：当前没有工具执行上下文（session_id 缺失）。"
MAX_NOTE_CHARS = 2000


class WakeOnBackgroundTool(BaseTool):
    """后台 shell 完成时自动恢复当前会话。"""

    risk: RiskClass = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="wake_on_background",
            description=(
                "登记后台任务完成唤醒：当指定的后台 shell 结束时，自动恢复当前"
                "会话并注入续跑消息（例如「测试跑完了，检查结果」）。"
                "配合 bash(run_in_background=true) 使用；登记后无需手动轮询 "
                "bash_output，任务结束会自动回来。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "shell_id": {
                        "type": "string",
                        "description": "bash(run_in_background=true) 返回的 shell_id。",
                    },
                    "note": {
                        "type": "string",
                        "description": (
                            "唤醒后注入对话的续跑说明（不超过 2000 字符），"
                            "例如「检查测试结果，失败则汇总报错」。"
                        ),
                    },
                },
                "required": ["shell_id"],
            },
        )

    def execute(self, shell_id: str = "", note: str = "", **kwargs: Any) -> ToolResult:  # noqa: PLR0911 — 参数校验多出口
        ctx = current_tool_context()
        session_id = (ctx.session_id or None) if ctx is not None else None
        if session_id is None:
            return ToolResult(success=False, error=NO_CONTEXT_ERROR)
        if not isinstance(shell_id, str) or not shell_id.strip():
            return ToolResult(success=False, error="shell_id 必须是非空字符串。")
        if not isinstance(note, str):
            return ToolResult(success=False, error="note 必须是字符串。")
        if len(note) > MAX_NOTE_CHARS:
            return ToolResult(success=False, error=f"note 过长（上限 {MAX_NOTE_CHARS} 字符）。")

        registry = get_registry()
        session = registry.get(shell_id)
        if session is None:
            return ToolResult(
                success=False,
                error="未知的 shell_id（可能已结束并被清理，或从未启动）。",
            )

        store = get_wake_store()
        note = note.strip()
        try:
            if session.status() == STATUS_EXITED:
                # 已结束：注册立即到期的 TIMER wake，下一 tick 恢复会话
                wake = Wake.create(
                    session_id,
                    WakeKind.TIMER,
                    fire_at=to_utc_iso(datetime.now(timezone.utc)),  # noqa: UP017
                    note=note,
                )
                store.add_wake(wake)
                mode = "immediate"
            else:
                wake = Wake.create(
                    session_id, WakeKind.COMPLETION, job_id=shell_id, note=note
                )
                store.add_wake(wake)
                # 退出时把 COMPLETION wake 标记为 DUE。
                registry.register_watcher(
                    shell_id, lambda _finished_id, _code: store.complete_job(_finished_id)
                )
                mode = "completion"
        except Exception:  # noqa: BLE001 — 工具边界，异常不穿透
            logger.exception("wake_on_background 执行异常")
            return ToolResult(success=False, error="登记后台唤醒失败：内部错误，请查看后端日志。")

        return ToolResult(
            success=True,
            content={
                "wake_id": wake.id,
                "shell_id": shell_id,
                "mode": mode,
                "note": note,
                "message": (
                    "已登记：后台任务结束时会自动恢复当前会话。"
                    if mode == "completion"
                    else "后台任务已结束，将立即恢复当前会话。"
                ),
            },
        )
