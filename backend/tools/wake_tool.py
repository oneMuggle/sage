"""LLM 会话唤醒工具（2026-11-05）。

把既有的 A4 Suspend-Resume 能力（``Wake`` + ``WakeScheduler``）暴露给
LLM：让当前会话在指定时刻自动恢复，注入一条注明原因的续跑消息。
此前 ``ChatService.sleep_for/sleep_until`` 只有单元测试调用，agent 在
"等 CI / 等部署 / 稍后再检查" 场景无法把会话挂到后台。

- 复用 ``WakeStore``（SQLite ``wakes`` 表），不另起调度器；
- 目标会话恒绑定 ``ToolExecutionContext.session_id``，拒绝跨会话；
- ``at`` 接受 ISO-8601、epoch 毫秒，或相对时间 ``in:600s`` / ``in:5m``。

设计约束与 ``schedule_tool`` 一致：仅 primary 主助手注册，子代理白名单
不含本工具。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.application.services.wake_store import get_wake_store
from backend.domain.risk import RiskClass
from backend.domain.wake import Wake, WakeKind, to_utc_iso
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context
from backend.tools.schedule_tool import _parse_once_timestamp

logger = logging.getLogger(__name__)

NO_CONTEXT_ERROR = "无法确定目标会话：当前没有工具执行上下文（session_id 缺失）。"

#: 相对时间后缀 → 秒数
_RELATIVE_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86_400.0}

#: note 长度上限（注入对话上下文，与 schedule_task 的 prompt 上限对齐减半）
MAX_NOTE_CHARS = 2000


def parse_wake_at(value: Any) -> str:
    """把 ``at`` 归一为 UTC ISO-8601 字符串。

    接受：
    - ``in:<数字><s|m|h|d>``：相对当前时刻，如 ``in:600s`` / ``in:5m``；
    - ISO-8601 字符串（``Z`` 后缀支持）；
    - epoch 毫秒整数。

    Raises:
        ValueError: 无法解析或超出可表示范围。
    """
    if isinstance(value, str):
        raw = value.strip()
        if raw.lower().startswith("in:"):
            spec = raw[3:].strip().lower()
            unit = spec[-1:] if spec else ""
            multiplier = _RELATIVE_UNITS.get(unit)
            if multiplier is None:
                raise ValueError(
                    f"无法解析相对时间 {raw!r}：格式应为 in:<数字><s|m|h|d>，如 in:600s。"
                )
            try:
                amount = float(spec[:-1])
            except ValueError as exc:
                raise ValueError(
                    f"无法解析相对时间 {raw!r}：'in:' 后应为数字+单位，如 in:600s。"
                ) from exc
            if amount < 0:
                raise ValueError("相对时间不能为负数。")
            fire_at = datetime.now(timezone.utc) + timedelta(seconds=amount * multiplier)  # noqa: UP017
            return to_utc_iso(fire_at)

    at_ms = _parse_once_timestamp(value)
    return to_utc_iso(datetime.fromtimestamp(at_ms / 1000, tz=timezone.utc))  # noqa: UP017


class WakeSessionAtTool(BaseTool):
    """让当前会话在指定时刻自动唤醒。"""

    risk: RiskClass = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="wake_session_at",
            description=(
                "让当前会话在指定时间自动恢复一次对话（注入一条续跑消息）。"
                "适用于耗时任务挂到后台后再回来检查：如「等 CI 跑完后继续」"
                "「10 分钟后再检查部署状态」。"
                "本工具只注册唤醒；当前回合会正常结束，空闲期间零成本，"
                "到点后由调度器自动发起新回合。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "at": {
                        "type": "string",
                        "description": (
                            "唤醒时间：相对时间 'in:600s' / 'in:5m'，"
                            "或 ISO-8601 '2026-11-05T15:30:00+08:00'，"
                            "或 epoch 毫秒整数。"
                        ),
                    },
                    "note": {
                        "type": "string",
                        "description": (
                            "唤醒后注入对话的续跑说明（不超过 2000 字符），"
                            "例如「检查 CI 结果，失败则汇总报错」。"
                        ),
                    },
                },
                "required": ["at"],
            },
        )

    def execute(self, at: Any = "", note: str = "", **kwargs: Any) -> ToolResult:  # noqa: PLR0911 — 参数校验多出口
        ctx = current_tool_context()
        session_id = (ctx.session_id or None) if ctx is not None else None
        if session_id is None:
            return ToolResult(success=False, error=NO_CONTEXT_ERROR)

        if not isinstance(at, (str, int)) or (isinstance(at, str) and not at.strip()):  # noqa: UP038 — py38 runtime
            return ToolResult(success=False, error="at 必须是非空字符串或 epoch 毫秒整数。")
        if not isinstance(note, str):
            return ToolResult(success=False, error="note 必须是字符串。")
        if len(note) > MAX_NOTE_CHARS:
            return ToolResult(success=False, error=f"note 过长（上限 {MAX_NOTE_CHARS} 字符）。")

        try:
            fire_at = parse_wake_at(at)
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))

        try:
            wake = Wake.create(session_id, WakeKind.TIMER, fire_at=fire_at, note=note.strip())
            get_wake_store().add_wake(wake)
        except Exception:  # noqa: BLE001 — 工具边界，异常不穿透
            logger.exception("wake_session_at 执行异常")
            return ToolResult(success=False, error="注册唤醒失败：内部错误，请查看后端日志。")

        return ToolResult(
            success=True,
            content={
                "wake_id": wake.id,
                "session_id": session_id,
                "fire_at": wake.fire_at,
                "note": wake.note,
                "message": f"已注册唤醒：{wake.fire_at} 自动恢复当前会话。",
            },
        )
