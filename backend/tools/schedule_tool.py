"""LLM 定时任务工具三件套（feat/llm-schedule-tool, 2026-09-19）。

把既有的 ``SchedulerService``（APScheduler + JSON 持久化）暴露给 LLM——
此前该能力只能经 REST API 由前端 UI 消费，用户在对话里表达"每 5 分钟检查
部署状态"时 LLM 无工具可调。

- ``schedule_task``         创建一次性 / 周期性任务（WRITE_LOCAL，审批）
- ``list_scheduled_tasks``  列出当前会话的定时任务（READ）
- ``cancel_scheduled_task`` 取消当前会话的定时任务（WRITE_LOCAL，审批）

设计约束（详见 ``docs/technical/92-llm-scheduled-task-tool.md``）：

1. **复用 ``SchedulerService``，不另起调度器** —— 工具创建的任务与 UI 创建的
   任务落在同一 JSON、同一 APScheduler jobstore，前端 ScheduledTasks 页立即
   可见、可编辑、可停用。单一调度事实源是本模块最重要的约束。
2. **目标会话恒绑定 ``ToolExecutionContext.session_id``** —— 普通聊天路径
   始终设置该 ContextVar。不要求 LLM 传会话 id，避免幻觉 id 把提醒注入错
   会话；显式传入的 ``session_id`` 必须等于当前会话，否则拒绝（防 prompt
   injection 借模型之手向他人会话投递消息）。
3. **``once`` 接受 ISO-8601 字符串或 epoch 毫秒** —— 5 段 cron 对一次性提醒
   表达能力不足且易错。无时区信息的 ISO 串按后端本地时区解释。
4. **不设 ``requires_tool_context``** —— 无上下文时本工具应可见并给出可读
   错误（便于排障），而非静默从工具面消失。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.services.scheduler import (
    SchedulerService,
    TaskNotFoundError,
    ValidationError,
    get_scheduler_service,
)
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context

logger = logging.getLogger(__name__)

#: 服务解析器签名 —— 返回进程内的 ``SchedulerService``，未初始化时为 ``None``。
ServiceGetter = Callable[[], Optional[SchedulerService]]

NO_CONTEXT_ERROR = (
    "无法确定目标会话：当前没有工具执行上下文（session_id 缺失）。"
    "请在具体的对话会话中调用本工具，或显式传入 session_id。"
)
NO_SERVICE_ERROR = "定时任务服务未初始化，无法执行本操作。"


def _default_service_getter() -> Optional[SchedulerService]:
    return get_scheduler_service()


def _resolve_session_id(explicit: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """解析目标会话，返回 ``(session_id, error)``（二者互斥）。

    会话恒绑定到当前 ``ToolExecutionContext``：无上下文即失败。显式传入的
    ``session_id`` **必须等于**当前会话 —— 之所以允许显式传参，只是为了在
    LLM 主动指定时给出可读的拒绝理由，而非静默忽略。跨会话创建/查询定时
    任务会让被 prompt injection 操纵的模型把消息注入他人会话，故一律拒绝。
    """
    ctx = current_tool_context()
    ctx_session = (ctx.session_id or None) if ctx is not None else None
    if ctx_session is None:
        return None, NO_CONTEXT_ERROR
    explicit = (explicit or "").strip()
    if explicit and explicit != ctx_session:
        # 2026-09-19 安全审查修复: 不回显实际 session_id — 防止 prompt injection
        # 借模型之手探测有效会话标识符。仅告知"不一致"即可。
        return None, (
            "拒绝跨会话操作：显式 session_id 与当前会话不一致。"
            "定时任务只能在当前会话内创建/查询/取消。"
        )
    return ctx_session, None


def _parse_once_timestamp(value: Any) -> int:
    """把 ``at`` 归一为 epoch 毫秒（int）。

    接受：
    - int / 数字字符串：直接视为 epoch 毫秒；
    - ISO-8601 字符串：如 ``2026-09-20T15:00:00+08:00``（``Z`` 后缀亦支持）。

    无法解析或超出平台可表示范围时抛 ``ValueError``，调用方转成可读
    ``ToolResult``。
    """
    if isinstance(value, bool):  # bool 是 int 子类，先拦
        raise ValueError("at 必须是 ISO-8601 时间字符串或 epoch 毫秒整数。")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise ValueError("at 用数值表达时必须是整数（epoch 毫秒），收到浮点数。")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("at 必须是 ISO-8601 时间字符串或 epoch 毫秒整数。")
    raw = value.strip()
    try:
        return int(raw)
    except ValueError:
        pass
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"无法解析时间 {raw!r}：请用 ISO-8601（如 2026-09-20T15:00:00+08:00）"
            "或 epoch 毫秒整数。"
        ) from exc
    try:
        if dt.tzinfo is None:
            # 无时区信息 → 按后端本地时区解释
            dt = dt.astimezone()
        return int(dt.timestamp() * 1000)
    except (OSError, OverflowError, ValueError) as exc:
        # Windows 上早于 1970 的时间戳会抛 OSError；超范围抛 OverflowError
        raise ValueError(f"时间 {raw!r} 超出可表示范围。") from exc


class ScheduleTaskTool(BaseTool):
    """创建定时任务（一次性或周期性），目标会话恒为当前对话会话。"""

    risk: RiskClass = RiskClass.WRITE_LOCAL

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        service_getter: Optional[ServiceGetter] = None,
    ) -> None:
        super().__init__(policy=policy)
        self._service_getter: ServiceGetter = service_getter or _default_service_getter

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="schedule_task",
            description=(
                "创建定时任务：在指定时间或按周期，自动向当前对话会话注入一条消息"
                "（可理解为「到点自动提醒/自动触发一次对话」）。"
                "适用于周期性检查（如「每 5 分钟检查部署状态」）与一次性提醒"
                "（如「明天下午 3 点提醒我提交报告」）。"
                "任务创建后出现在前端的定时任务列表中，用户可查看、停用或删除。"
                "注意：高频任务会持续消耗算力，请按实际需要设定周期。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "任务名称（不超过 80 字符），用于在任务列表中识别。",
                    },
                    "prompt": {
                        "type": "string",
                        "description": (
                            "任务触发时注入当前会话的消息内容（不超过 4000 字符）。"
                            "写清楚「到点要做什么」，例如「检查部署状态，若有变化请汇总报告」。"
                        ),
                    },
                    "schedule_kind": {
                        "type": "string",
                        "enum": ["once", "recurring"],
                        "description": "'once'=一次性；'recurring'=按 cron 周期重复。",
                    },
                    "cron": {
                        "type": "string",
                        "description": (
                            "schedule_kind='recurring' 时必填：5 段 cron 表达式"
                            "（分 时 日 月 周），如 '*/5 * * * *' 表示每 5 分钟、"
                            "'0 9 * * 1-5' 表示工作日 9:00。按服务器本地时区解释。"
                        ),
                    },
                    "at": {
                        "type": "string",
                        "description": (
                            "schedule_kind='once' 时必填：ISO-8601 时间字符串"
                            "（如 '2026-09-20T15:00:00+08:00'，建议带时区）"
                            "或 epoch 毫秒整数。必须是未来时间。"
                        ),
                    },
                    "session_id": {
                        "type": "string",
                        "description": (
                            "通常无需填写：任务默认绑定当前对话会话。"
                            "若填写则必须与当前会话一致，否则会被拒绝。"
                        ),
                    },
                },
                "required": ["name", "prompt", "schedule_kind"],
            },
        )

    def execute(  # noqa: PLR0911 — 参数校验多出口
        self,
        name: str = "",
        prompt: str = "",
        schedule_kind: str = "",
        cron: Optional[str] = None,
        at: Any = None,
        session_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(name, str) or not name.strip():
            return ToolResult(success=False, error="name 必须是非空字符串。")
        if not isinstance(prompt, str) or not prompt.strip():
            return ToolResult(success=False, error="prompt 必须是非空字符串。")
        if len(name) > 80:
            return ToolResult(success=False, error="name 过长（上限 80 字符）。")
        if len(prompt) > 4000:
            return ToolResult(success=False, error="prompt 过长（上限 4000 字符）。")
        if schedule_kind not in ("once", "recurring"):
            return ToolResult(
                success=False, error="schedule_kind 必须是 'once' 或 'recurring'。"
            )

        resolved_session, session_error = _resolve_session_id(session_id)
        if session_error is not None:
            return ToolResult(success=False, error=session_error)

        if schedule_kind == "recurring":
            if not cron or not str(cron).strip():
                return ToolResult(
                    success=False,
                    error="schedule_kind='recurring' 时必须提供 cron 表达式。",
                )
            schedule: Dict[str, Any] = {"kind": "recurring", "cron": str(cron).strip()}
        else:
            if at is None:
                return ToolResult(
                    success=False,
                    error="schedule_kind='once' 时必须提供 at（ISO-8601 或 epoch 毫秒）。",
                )
            try:
                at_ms = _parse_once_timestamp(at)
            except ValueError as exc:
                return ToolResult(success=False, error=str(exc))
            schedule = {"kind": "once", "at": at_ms}

        service = self._service_getter()
        if service is None:
            return ToolResult(success=False, error=NO_SERVICE_ERROR)

        try:
            task = service.add_task(
                name=name.strip(),
                task_type=schedule_kind,  # type: ignore[arg-type]
                schedule=schedule,
                session_id=resolved_session,
                content=prompt.strip(),
            )
        except ValidationError as exc:
            return ToolResult(success=False, error=f"创建定时任务失败：{exc}")
        except Exception as exc:  # noqa: BLE001 — 工具边界，异常不穿透
            logger.exception("schedule_task 执行异常: %s", exc)
            # 2026-09-19 安全审查修复: 不回显原始异常文本（可能含路径/类名）
            return ToolResult(success=False, error="创建定时任务失败：内部错误，请查看后端日志。")

        schedule_desc = (
            f"每周期 cron={task.schedule.get('cron')}"
            if task.type == "recurring"
            else f"一次性 at={task.schedule.get('at')}"
        )
        summary = (
            f"已创建定时任务 {task.id}（{task.name}）：{schedule_desc}，"
            f"目标会话 {task.session_id}，下次触发 {task.next_run}。"
        )
        return ToolResult(
            success=True,
            content={
                "task_id": task.id,
                "name": task.name,
                "type": task.type,
                "schedule": task.schedule,
                "session_id": task.session_id,
                "next_run": task.next_run,
            },
            output=summary,
        )


class ListScheduledTasksTool(BaseTool):
    """列出当前会话的定时任务。"""

    risk: RiskClass = RiskClass.READ

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        service_getter: Optional[ServiceGetter] = None,
    ) -> None:
        super().__init__(policy=policy)
        self._service_getter: ServiceGetter = service_getter or _default_service_getter

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="list_scheduled_tasks",
            description=(
                "列出当前对话会话已设置的定时任务（含任务 ID、名称、周期/触发时间、"
                "下次触发时间与最近执行状态）。默认只返回当前会话的任务。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": (
                            "通常无需填写：默认列出当前对话会话的任务。"
                            "若填写则必须与当前会话一致，否则会被拒绝。"
                        ),
                    }
                },
            },
        )

    def execute(self, session_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        resolved_session, session_error = _resolve_session_id(session_id)
        if session_error is not None:
            return ToolResult(success=False, error=session_error)
        service = self._service_getter()
        if service is None:
            return ToolResult(success=False, error=NO_SERVICE_ERROR)

        try:
            tasks = [t for t in service.list_tasks() if t.session_id == resolved_session]
        except Exception as exc:  # noqa: BLE001 — 工具边界
            logger.exception("list_scheduled_tasks 执行异常: %s", exc)
            # 2026-09-19 安全审查修复: 不回显原始异常文本
            return ToolResult(success=False, error="查询定时任务失败：内部错误，请查看后端日志。")

        if not tasks:
            return ToolResult(
                success=True,
                content={"tasks": []},
                output=f"当前会话（{resolved_session}）没有定时任务。",
            )

        items: List[Dict[str, Any]] = [
            {
                "task_id": t.id,
                "name": t.name,
                "type": t.type,
                "schedule": t.schedule,
                "next_run": t.next_run,
                "enabled": t.enabled,
                "last_status": t.last_status,
                "last_error": t.last_error,
            }
            for t in tasks
        ]
        lines = [
            f"- {t.id} | {t.name} | {t.type} | {t.schedule} | "
            f"next_run={t.next_run} | enabled={t.enabled} | last={t.last_status}"
            for t in tasks
        ]
        return ToolResult(
            success=True,
            content={"tasks": items},
            output=f"当前会话（{resolved_session}）共有 {len(tasks)} 个定时任务：\n"
            + "\n".join(lines),
        )


class CancelScheduledTaskTool(BaseTool):
    """取消（删除）当前会话的定时任务。"""

    risk: RiskClass = RiskClass.WRITE_LOCAL

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        service_getter: Optional[ServiceGetter] = None,
    ) -> None:
        super().__init__(policy=policy)
        self._service_getter: ServiceGetter = service_getter or _default_service_getter

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="cancel_scheduled_task",
            description=(
                "取消一个定时任务（按任务 ID 删除，不再触发）。任务 ID 可由 "
                "schedule_task 的返回或 list_scheduled_tasks 获得。"
                "只能取消当前会话自己的任务。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "要取消的任务 ID（形如 task-xxxxxxxx）。",
                    }
                },
                "required": ["task_id"],
            },
        )

    def execute(self, task_id: str = "", **kwargs: Any) -> ToolResult:  # noqa: PLR0911 — 防御性拦截多出口
        if not isinstance(task_id, str) or not task_id.strip():
            return ToolResult(success=False, error="task_id 必须是非空字符串。")
        task_id = task_id.strip()

        resolved_session, session_error = _resolve_session_id(None)
        if session_error is not None:
            return ToolResult(success=False, error=session_error)
        service = self._service_getter()
        if service is None:
            return ToolResult(success=False, error=NO_SERVICE_ERROR)

        try:
            # 会话归属由 delete_task 在锁内原子校验（expected_session_id）——
            # 此前"先 get_task 校验 / 再 delete_task"的写法在两次获锁之间留有
            # TOCTOU 窗口：前端 UI 可把任务迁移到别的会话后，本工具仍按旧归属
            # 删除。2026-09-19 安全审查修复。
            service.delete_task(task_id, expected_session_id=resolved_session)
        except ValidationError:
            # 不回显 task.session_id 或 resolved_session（防会话 id 探测）
            return ToolResult(success=False, error="拒绝取消：该任务不属于当前会话。")
        except TaskNotFoundError:
            return ToolResult(success=False, error=f"未找到任务：{task_id}")
        except Exception as exc:  # noqa: BLE001 — 工具边界
            logger.exception("cancel_scheduled_task 执行异常: %s", exc)
            # 2026-09-19 安全审查修复: 不回显原始异常文本
            return ToolResult(success=False, error="取消定时任务失败：内部错误，请查看后端日志。")

        return ToolResult(
            success=True,
            content={"task_id": task_id, "cancelled": True},
            output=f"已取消定时任务 {task_id}。",
        )
