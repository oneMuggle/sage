"""LLM tools for work-log capture (P2).

Two tools that wrap :class:`WorklogService` for LLM consumption:

- :class:`AddWorklogTool`    -- record what the user just did (WRITE_LOCAL)
- :class:`ListWorklogsTool`  -- query the work-log stream (READ)

These are the agent-facing half of the work-log subsystem. The HTTP half
(:mod:`backend.api.worklog_router`) lets the user curate records by hand;
the two halves share one table (``work_logs``) and one service.

Distinct from :class:`TodoWriteTool` (``todo_tool.py``), which is the
claw-code session-scratch list (full-replace semantics, in-memory,
per-session) and never touches SQLite.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy  # noqa: F401 -- for type hint
from backend.services.worklog_models import WORKLOG_KINDS
from backend.services.worklog_service import WorklogService
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


WorklogServiceGetter = Callable[[], Optional[WorklogService]]  # noqa: UP045 — Py3.8 compat (UP007/UP035 already disabled)

NO_SERVICE_ERROR = "工作日志服务未初始化，无法执行本操作。"


def _default_worklog_service_getter() -> Optional[WorklogService]:  # noqa: UP045 — Py3.8 compat
    """Return no service unless the application composition root injects one.

    Mirrors ``todo_mgmt_tool._default_todo_service_getter``: tools are wired
    up via ``register_all_tools(..., worklog_service_getter=...)``. In tests
    and isolated fixtures the getter returns None and the tools degrade to a
    friendly "未初始化" ``ToolResult`` instead of an ``AttributeError``.
    """
    return None


class _WorklogServiceMixin:
    """Shared constructor for the work-log-backed tools.

    The service is resolved lazily per execute call, so an uninitialised
    ``WorklogService`` yields a friendly "未初始化" ``ToolResult`` instead of
    a ``None`` AttributeError.
    """

    def __init__(
        self,
        *,
        policy: Optional[ToolPolicy] = None,  # noqa: UP045 — Py3.8 compat
        worklog_service_getter: Optional[WorklogServiceGetter] = None,  # noqa: UP045 — Py3.8 compat
        **kwargs: Any,
    ) -> None:
        # Forward to BaseTool.__init__ (which accepts policy). Extra kwargs are
        # accepted but not used -- allows forward-compatible kwarg expansion.
        super().__init__(policy=policy, **kwargs)  # type: ignore[arg-type]
        self._worklog_service_getter: WorklogServiceGetter = (
            worklog_service_getter or _default_worklog_service_getter
        )

    def _get_service(self) -> Optional[WorklogService]:  # noqa: UP045 — Py3.8 compat
        """Resolve the service lazily (per execute call)."""
        return self._worklog_service_getter()


class AddWorklogTool(_WorklogServiceMixin, BaseTool):
    """Record one work-log entry.

    Records land as ``status='pending'`` — the user confirms them in the
    inbox before they count towards a daily/weekly report.
    """

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="add_worklog",
            description=(
                "记录一条工作日志（当天做了什么、进展、阻塞、下一步）。"
                "用于在对话中随手沉淀工作痕迹，之后生成日报/周报。"
                "记录会以「待确认」状态入库，用户确认后才计入报告。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "一句话陈述这件事（≤200 字）",
                    },
                    "kind": {
                        "type": "string",
                        "enum": list(WORKLOG_KINDS),
                        "description": (
                            "分类：progress（进展）/ done（已完成）/ "
                            "blocker（阻塞）/ next（下一步）；默认 progress"
                        ),
                    },
                    "todo_id": {
                        "type": "integer",
                        "description": "关联的待办 ID（可选）",
                    },
                    "project_tag": {
                        "type": "string",
                        "description": "项目标签（可选）",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "来源会话 ID（可选）",
                    },
                    "progress_text": {
                        "type": "string",
                        "description": "补充的进展细节（可选）",
                    },
                    "blocker": {
                        "type": "string",
                        "description": "阻塞说明（kind=blocker 时填写）",
                    },
                },
                "required": ["content"],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        service = self._get_service()
        if service is None:
            return ToolResult(success=False, error=NO_SERVICE_ERROR)
        try:
            worklog = service.create_worklog(
                content=kwargs["content"],
                kind=kwargs.get("kind", "progress"),
                session_id=kwargs.get("session_id"),
                progress_text=kwargs.get("progress_text"),
                blocker=kwargs.get("blocker"),
                todo_id=kwargs.get("todo_id"),
                project_tag=kwargs.get("project_tag"),
                source_type="agent",
            )
            return ToolResult(
                success=True,
                content={
                    "id": worklog.id,
                    "content": worklog.content,
                    "kind": worklog.kind,
                    "status": worklog.status,
                },
                output=worklog,
            )
        except Exception as exc:  # noqa: BLE001 -- tool boundary: surface as ToolResult
            logger.error("add_worklog failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class ListWorklogsTool(_WorklogServiceMixin, BaseTool):
    """Query the work-log stream."""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="list_worklogs",
            description=(
                "查询工作日志。可按日期区间、分类、状态筛选，用于回答"
                "「我这两天做了什么」「今天完成了哪些事」。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": "起始日期，YYYY-MM-DD（含当天，可选）",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "结束日期，YYYY-MM-DD（含当天，可选）",
                    },
                    "kind": {
                        "type": "string",
                        "enum": list(WORKLOG_KINDS),
                        "description": "分类筛选（可选）",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "confirmed", "dismissed", "all"],
                        "description": "状态筛选（默认 all）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制（默认 50）",
                    },
                },
                "required": [],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        service = self._get_service()
        if service is None:
            return ToolResult(success=False, error=NO_SERVICE_ERROR)
        try:
            status = kwargs.get("status")
            if status == "all":
                status = None
            worklogs = service.list_worklogs(
                status=status,
                kind=kwargs.get("kind"),
                date_from=kwargs.get("date_from"),
                date_to=kwargs.get("date_to"),
                limit=kwargs.get("limit", 50),
            )
            return ToolResult(
                success=True,
                content={
                    "worklogs": [
                        {
                            "id": w.id,
                            "content": w.content,
                            "kind": w.kind,
                            "status": w.status,
                            "project_tag": w.project_tag,
                            "created_at": w.created_at,
                        }
                        for w in worklogs
                    ],
                    "count": len(worklogs),
                },
            )
        except Exception as exc:  # noqa: BLE001 -- tool boundary
            logger.error("list_worklogs failed: %s", exc)
            return ToolResult(success=False, error=str(exc))
